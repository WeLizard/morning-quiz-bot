"""
FastAPI веб-интерфейс для управления Morning Quiz Bot
"""
import os
import json
import subprocess
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import io
import csv
from datetime import datetime
import shutil

# Настройка логирования (перед загрузкой .env, чтобы можно было логировать процесс загрузки)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения из .env файла
try:
    from dotenv import load_dotenv
    # Определяем путь к .env файлу (в корне проекта)
    BASE_DIR_FOR_ENV = Path(__file__).parent.parent
    env_path = BASE_DIR_FOR_ENV / '.env'
    
    # Также пробуем загрузить из текущей рабочей директории (для systemd)
    if not env_path.exists():
        env_path = Path('.env')
    
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        logger.info(f"Переменные окружения загружены из: {env_path.absolute()}")
        # Проверяем, что BOT_TOKEN загружен
        bot_token_check = os.getenv("BOT_TOKEN")
        if bot_token_check:
            logger.info("BOT_TOKEN успешно загружен из .env файла")
        else:
            logger.warning("BOT_TOKEN не найден в .env файле после загрузки")
    else:
        logger.warning(f"Файл .env не найден. Пробовались пути: {BASE_DIR_FOR_ENV / '.env'}, {Path('.env').absolute()}")
except ImportError:
    # python-dotenv не установлен, пропускаем загрузку .env
    logger.warning("Модуль python-dotenv не установлен. Переменные окружения из .env файла не будут загружены.")
except Exception as e:
    logger.error(f"Ошибка при загрузке .env файла: {e}", exc_info=True)

# Инициализация FastAPI
app = FastAPI(
    title="Morning Quiz Bot Admin",
    description="Веб-интерфейс для управления вопросами и статистикой",
    version="2.0.0"
)

# Register PostgreSQL routes before legacy JSON handlers with the same paths.
from web.postgres_admin import install_postgres_admin
install_postgres_admin(app)
from web.admin_auth import install_admin_auth
install_admin_auth(app)

# Пути
# Определяем базовую директорию проекта
# Если запускается из systemd, рабочая директория уже установлена в WorkingDirectory
BASE_DIR = Path(__file__).parent.parent
# Если BASE_DIR не существует, используем текущую рабочую директорию
if not BASE_DIR.exists():
    BASE_DIR = Path.cwd()
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
QUESTIONS_DIR = DATA_DIR / "questions"
CATEGORIES_FILE = DATA_DIR / "global" / "categories.json"
STATS_DIR = DATA_DIR / "statistics"
CHATS_DIR = DATA_DIR / "chats"
GLOBAL_DIR = DATA_DIR / "global"
SYSTEM_DIR = DATA_DIR / "system"
BOT_MODE_FILE = DATA_DIR / "bot_mode.json"
MAINTENANCE_STATUS_FILE = CONFIG_DIR / "maintenance_status.json"
IMAGES_DIR = DATA_DIR / "images"
PHOTO_QUIZ_METADATA = DATA_DIR / "photo_quiz_metadata.json"
LOGS_DIR = BASE_DIR / "logs"

# Templates directory
TEMPLATES_DIR = BASE_DIR / "web" / "templates"

# Подключение статических файлов
STATIC_DIR = BASE_DIR / "web" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Модели данных
class Question(BaseModel):
    question: str
    options: List[str] = Field(..., min_length=2, max_length=10)
    correct: str
    explanation: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None

class QuestionUpdate(BaseModel):
    question: Optional[str] = None
    options: Optional[List[str]] = None
    correct: Optional[str] = None
    explanation: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None

class CategoryInfo(BaseModel):
    name: str
    question_count: int
    file_path: str

class DailyQuizSettings(BaseModel):
    enabled: bool
    times_msk: List[Dict[str, int]]
    categories_mode: Optional[str] = "random"
    num_random_categories: Optional[int] = 3
    specific_categories: Optional[List[str]] = []
    num_questions: Optional[int] = 10
    interval_seconds: Optional[int] = 60
    poll_open_seconds: Optional[int] = 600

class ChatSettingsUpdate(BaseModel):
    daily_quiz: Optional[DailyQuizSettings] = None
    default_num_questions: Optional[int] = None
    default_open_period_seconds: Optional[int] = None
    enabled_categories: Optional[List[str]] = None
    disabled_categories: Optional[List[str]] = None

# Вспомогательные функции
def check_bot_service_status() -> bool:
    """
    Проверяет статус бота через PID файл, systemd и альтернативные методы.
    Возвращает True если бот работает, False если нет.
    """
    # Метод 1: Проверка через PID файл (САМЫЙ НАДЕЖНЫЙ)
    try:
        # Путь к PID файлу относительно корня проекта
        project_root = DATA_DIR.parent
        pid_file = project_root / "bot.pid"
        
        if pid_file.exists():
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Проверяем, жив ли процесс
            try:
                # Посылаем сигнал 0 (не убивает процесс, только проверяет существование)
                import os
                os.kill(pid, 0)
                # Дополнительно проверяем, что это действительно bot.py
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    cmdline = ' '.join(proc.cmdline())
                    if 'bot.py' in cmdline:
                        return True  # Это наш бот!
                except:
                    return True  # psutil недоступен, но процесс существует
            except (ProcessLookupError, OSError):
                # Процесс не существует, удаляем устаревший PID файл
                try:
                    pid_file.unlink()
                except:
                    pass
    except Exception as e:
        # Логируем ошибку для отладки
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Ошибка при проверке PID файла: {e}")
    
    # Метод 2: Проверка через pgrep
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'python.*bot\\.py'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            return True  # Процесс найден
    except:
        pass
    
    # Метод 3: Проверка через systemctl с sudo
    try:
        result = subprocess.run(
            ['sudo', '-n', 'systemctl', 'is-active', 'quiz-bot'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if status == 'active':
                return True
    except:
        pass
    
    # Метод 4: Проверка через systemctl без sudo
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', 'quiz-bot'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if status == 'active':
                return True
    except:
        pass
    
    # Метод 5: Обычный systemctl
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'quiz-bot'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if status == 'active':
                return True
    except:
        pass
    
    # Если все методы не сработали, возвращаем False
    return False

def load_category_questions(category_name: str) -> List[Dict[str, Any]]:
    """Загружает вопросы категории"""
    category_file = QUESTIONS_DIR / f"{category_name}.json"
    if not category_file.exists():
        return []
    
    try:
        with open(category_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки категории: {str(e)}")

def save_category_questions(category_name: str, questions: List[Dict[str, Any]]) -> bool:
    """Сохраняет вопросы категории"""
    category_file = QUESTIONS_DIR / f"{category_name}.json"
    try:
        with open(category_file, 'w', encoding='utf-8') as f:
            json.dump(questions, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {str(e)}")

def get_all_categories() -> List[str]:
    """Получает список всех категорий"""
    categories = []
    if CATEGORIES_FILE.exists():
        try:
            with open(CATEGORIES_FILE, 'r', encoding='utf-8') as f:
                cats_data = json.load(f)
                categories = list(cats_data.keys())
        except:
            pass
    
    # Если файл категорий пуст, получаем из файлов
    if not categories:
        categories = [f.stem for f in QUESTIONS_DIR.glob("*.json")]
    
    return sorted(categories)

def load_malformed_questions() -> List[Dict[str, Any]]:
    """Загружает бракованные вопросы из файла"""
    malformed_file = SYSTEM_DIR / "malformed_questions.json"
    
    # Создаем директорию, если её нет
    try:
        SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"Не удалось создать директорию {SYSTEM_DIR}: {e}")
    
    if not malformed_file.exists():
        logger.debug(f"Файл бракованных вопросов не найден: {malformed_file}")
        # Создаем пустой файл для будущего использования
        try:
            with open(malformed_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Не удалось создать файл бракованных вопросов: {e}")
        return []
    
    try:
        with open(malformed_file, 'r', encoding='utf-8') as f:
            malformed_data = json.load(f)
            if isinstance(malformed_data, list):
                logger.debug(f"Загружено {len(malformed_data)} бракованных вопросов")
                return malformed_data
            else:
                logger.warning(f"Файл бракованных вопросов содержит не список, а {type(malformed_data)}")
                return []
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON в файле бракованных вопросов: {e}")
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки бракованных вопросов: {e}", exc_info=True)
        return []

# API Routes
@app.get("/", response_class=HTMLResponse)
async def index():
    """Главная страница"""
    html_file = TEMPLATES_DIR / "index.html"
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()
    if os.getenv("STORAGE_BACKEND", "postgres").strip().lower() == "postgres":
        # PG adapters use local scripts only; legacy chart/AI widgets are hidden.
        import re
        # Server-side marker applies the theme before JS/auth finishes (no white flash).
        html = html.replace('<html lang="ru">', '<html lang="ru" data-admin-theme="night">', 1)
        html = html.replace('<body>', '<body class="pg-admin">', 1)
        html = re.sub(r'<script\b[^>]*src="https?://[^>]*>\s*</script>', '', html)
        html = re.sub(r'<link\b[^>]*href="https?://[^>]*>', '', html)
        html = re.sub(r'<script>(.*?)</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'\s+on[a-z]+="[^"]*"', '', html, flags=re.IGNORECASE)
    return HTMLResponse(content=html)

@app.get("/api/categories")
async def get_categories():
    """Получить список всех категорий"""
    categories = get_all_categories()
    result = []
    
    for cat_name in categories:
        questions = load_category_questions(cat_name)
        result.append({
            "name": cat_name,
            "question_count": len(questions),
            "file_path": f"questions/{cat_name}.json"
        })
    
    return {"categories": result}

@app.post("/api/categories")
async def create_category(category_name: str):
    """Создать новую категорию"""
    if not category_name or not category_name.strip():
        raise HTTPException(status_code=400, detail="Имя категории не может быть пустым")
    
    category_name = category_name.strip()
    category_file = QUESTIONS_DIR / f"{category_name}.json"
    
    if category_file.exists():
        raise HTTPException(status_code=400, detail=f"Категория '{category_name}' уже существует")
    
    try:
        # Создаем пустой файл категории
        with open(category_file, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return {"message": f"Категория '{category_name}' успешно создана", "name": category_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при создании категории: {str(e)}")

@app.delete("/api/categories/{category_name}")
async def delete_category(category_name: str):
    """Удалить категорию и все ее вопросы"""
    category_file = QUESTIONS_DIR / f"{category_name}.json"
    
    if not category_file.exists():
        raise HTTPException(status_code=404, detail=f"Категория '{category_name}' не найдена")
    
    try:
        # Удаляем файл категории
        category_file.unlink()
        return {"message": f"Категория '{category_name}' и все ее вопросы успешно удалены"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении категории: {str(e)}")

@app.get("/api/questions")
async def get_all_questions():
    """Получить все вопросы из всех категорий"""
    categories = get_all_categories()
    all_questions = []
    
    for cat_name in categories:
        questions = load_category_questions(cat_name)
        # Отладочный вывод для первой категории
        if cat_name == categories[0] and questions:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"DEBUG: Loaded {len(questions)} questions from {cat_name}")
            logger.warning(f"DEBUG: First question keys: {list(questions[0].keys()) if questions else 'no questions'}")
            logger.warning(f"DEBUG: First question has options: {'options' in questions[0] if questions else False}")
            logger.warning(f"DEBUG: First question options: {questions[0].get('options') if questions else 'no questions'}")
        
        for question_idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
                
            # Поддерживаем оба формата: старый (answers, correct_answer) и новый (options, correct)
            # Явно проверяем наличие options или answers
            options = []
            # Сначала проверяем options
            if "options" in q:
                opt_value = q["options"]
                if isinstance(opt_value, list):
                    options = opt_value
                elif opt_value is not None:
                    # Если options не список, но есть, пробуем преобразовать
                    options = []
            # Если options пустой, проверяем answers
            if not options and "answers" in q:
                ans_value = q["answers"]
                if isinstance(ans_value, list):
                    options = ans_value
            
            # Отладочный вывод для первого вопроса первой категории
            if cat_name == categories[0] and question_idx == 0:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"DEBUG get_all_questions: Processing first question from {cat_name}")
                logger.warning(f"DEBUG: q keys = {list(q.keys())}")
                logger.warning(f"DEBUG: q.get('options') = {q.get('options')}, type = {type(q.get('options'))}")
                logger.warning(f"DEBUG: q.get('correct') = {q.get('correct')}, type = {type(q.get('correct'))}")
                logger.warning(f"DEBUG: options after processing = {options}, len = {len(options)}")
            
            # Получаем правильный ответ - может быть строкой или числом (индексом)
            correct = ""
            if "correct" in q:
                correct_value = q["correct"]
                if correct_value is not None:
                    if isinstance(correct_value, (int, float)) and options and len(options) > 0:
                        # Если это число, используем его как индекс
                        correct_idx = int(correct_value)
                        if 0 <= correct_idx < len(options):
                            correct = options[correct_idx]
                        else:
                            correct = str(correct_value)
                    else:
                        # Это строка или другой тип
                        correct = str(correct_value)
            elif "correct_answer" in q:
                correct_value = q["correct_answer"]
                if correct_value is not None:
                    if isinstance(correct_value, (int, float)) and options and len(options) > 0:
                        # Если это число, используем его как индекс
                        correct_idx = int(correct_value)
                        if 0 <= correct_idx < len(options):
                            correct = options[correct_idx]
                        else:
                            correct = str(correct_value)
                    else:
                        # Это строка или другой тип
                        correct = str(correct_value)
            
            # Формируем объект вопроса - всегда добавляем все поля, даже если они пустые
            question_data = {
                "category": str(cat_name),
                "original_category": str(cat_name),
                "index": int(question_idx),
                "question": str(q.get("question", "")),
                "options": list(options) if options else [],  # Всегда список
                "answers": list(options) if options else [],  # Для совместимости (старый формат)
                "correct": correct if correct else "",  # Всегда строка
                "correct_answer": correct if correct else "",  # Для совместимости (старый формат)
                "explanation": str(q.get("explanation", "")),
                "difficulty": q.get("difficulty"),
                "tags": list(q.get("tags", [])) if q.get("tags") else []
            }
            
            all_questions.append(question_data)
    
    # ВРЕМЕННАЯ ОТЛАДКА: проверяем, что возвращается
    if all_questions and len(all_questions) > 0:
        first_q = all_questions[0]
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"DEBUG FINAL: First question keys: {list(first_q.keys())}")
        logger.warning(f"DEBUG FINAL: First question has options: {'options' in first_q}")
        logger.warning(f"DEBUG FINAL: First question options: {first_q.get('options')}")
        logger.warning(f"DEBUG FINAL: First question has correct: {'correct' in first_q}")
        logger.warning(f"DEBUG FINAL: First question correct: {first_q.get('correct')}")
    
    return {"questions": all_questions, "total": len(all_questions)}

@app.get("/api/categories/{category_name}/questions")
async def get_questions(category_name: str):
    """Получить все вопросы категории"""
    questions = load_category_questions(category_name)
    return {"category": category_name, "questions": questions, "count": len(questions)}

@app.get("/api/categories/{category_name}/questions/{question_index}")
async def get_question(category_name: str, question_index: int):
    """Получить конкретный вопрос"""
    questions = load_category_questions(category_name)
    if question_index < 0 or question_index >= len(questions):
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    return {"question": questions[question_index], "index": question_index}

@app.post("/api/categories/{category_name}/questions")
async def create_question(category_name: str, question: Question):
    """Добавить новый вопрос в категорию"""
    questions = load_category_questions(category_name)
    
    # Валидация
    if question.correct not in question.options:
        raise HTTPException(status_code=400, detail="Правильный ответ должен быть в списке вариантов")
    
    # Создаем вопрос в правильном формате (только нужные поля)
    question_dict = {
        "question": question.question,
        "options": question.options,
        "correct": question.correct
    }
    
    # Добавляем опциональные поля только если они есть
    if question.explanation:
        question_dict["explanation"] = question.explanation
    if question.difficulty:
        question_dict["difficulty"] = question.difficulty
    if question.tags:
        question_dict["tags"] = question.tags
    
    questions.append(question_dict)
    
    # Сохраняем
    save_category_questions(category_name, questions)
    
    return {"message": "Вопрос добавлен", "question": question_dict, "index": len(questions) - 1}

@app.put("/api/categories/{category_name}/questions/{question_index}")
async def update_question(category_name: str, question_index: int, question_update: QuestionUpdate):
    """Обновить вопрос"""
    questions = load_category_questions(category_name)
    if question_index < 0 or question_index >= len(questions):
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    
    # Получаем текущий вопрос
    current_question = questions[question_index].copy()
    
    # Подготавливаем данные для обновления (только переданные поля)
    update_data = question_update.dict(exclude_none=True)
    
    # Определяем финальные options и correct для валидации
    final_options = update_data.get("options", current_question.get("options", []))
    final_correct = update_data.get("correct", current_question.get("correct", ""))
    
    # Валидация правильного ответа
    if final_correct and final_correct not in final_options:
        raise HTTPException(status_code=400, detail="Правильный ответ должен быть в списке вариантов")
    
    # Обновляем только нужные поля, сохраняя правильный формат
    if "question" in update_data:
        current_question["question"] = update_data["question"]
    if "options" in update_data:
        current_question["options"] = update_data["options"]
    if "correct" in update_data:
        current_question["correct"] = update_data["correct"]
    if "explanation" in update_data:
        if update_data["explanation"]:
            current_question["explanation"] = update_data["explanation"]
        elif "explanation" in current_question:
            del current_question["explanation"]
    if "difficulty" in update_data:
        if update_data["difficulty"]:
            current_question["difficulty"] = update_data["difficulty"]
        elif "difficulty" in current_question:
            del current_question["difficulty"]
    if "tags" in update_data:
        if update_data["tags"]:
            current_question["tags"] = update_data["tags"]
        elif "tags" in current_question:
            del current_question["tags"]
    
    # Удаляем старые поля для совместимости, если они есть
    current_question.pop("answers", None)
    current_question.pop("correct_answer", None)
    current_question.pop("correct_option_text", None)
    current_question.pop("original_category", None)
    
    # Обновляем вопрос в списке
    questions[question_index] = current_question
    
    # Сохраняем
    save_category_questions(category_name, questions)
    
    return {"message": "Вопрос обновлен", "question": current_question}

@app.delete("/api/categories/{category_name}/questions/{question_index}")
async def delete_question(category_name: str, question_index: int):
    """Удалить вопрос"""
    questions = load_category_questions(category_name)
    if question_index < 0 or question_index >= len(questions):
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    
    deleted_question = questions.pop(question_index)
    save_category_questions(category_name, questions)
    
    return {"message": "Вопрос удален", "question": deleted_question}

@app.get("/api/statistics")
async def get_statistics():
    """Получить статистику"""
    stats = {
        "categories": {},
        "total_questions": 0,
        "total_categories": 0
    }
    
    categories = get_all_categories()
    stats["total_categories"] = len(categories)
    
    for cat_name in categories:
        questions = load_category_questions(cat_name)
        stats["categories"][cat_name] = {
            "question_count": len(questions)
        }
        stats["total_questions"] += len(questions)
    
    return stats

@app.get("/api/malformed-questions")
async def get_malformed_questions():
    """Получить список бракованных вопросов"""
    try:
        malformed_questions = load_malformed_questions()
        
        # Группируем по типу ошибки
        grouped_by_error = {}
        for entry in malformed_questions:
            error_type = entry.get("error_type", "unknown")
            if error_type not in grouped_by_error:
                grouped_by_error[error_type] = []
            grouped_by_error[error_type].append(entry)
        
        return {
            "malformed_questions": malformed_questions,
            "total": len(malformed_questions),
            "grouped_by_error": grouped_by_error,
            "error_types": list(grouped_by_error.keys())
        }
    except Exception as e:
        logger.error(f"Ошибка при получении бракованных вопросов: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки бракованных вопросов: {str(e)}")

@app.post("/api/categories/{category_name}/import")
async def import_questions(category_name: str, questions: List[Dict[str, Any]]):
    """Импортировать вопросы в категорию"""
    current_questions = load_category_questions(category_name)
    
    # Валидация
    valid_questions = []
    for q in questions:
        if "question" in q and "options" in q and "correct" in q:
            if q["correct"] in q["options"]:
                valid_questions.append(q)
    
    current_questions.extend(valid_questions)
    save_category_questions(category_name, current_questions)
    
    return {
        "message": f"Импортировано {len(valid_questions)} вопросов",
        "imported": len(valid_questions),
        "total": len(current_questions)
    }

# ===== АНАЛИТИКА =====

@app.get("/api/analytics/chats")
async def get_chats_analytics():
    """Получить аналитику по всем чатам"""
    chats = []
    for chat_dir in CHATS_DIR.iterdir():
        if not chat_dir.is_dir():
            continue
        
        chat_id = chat_dir.name
        settings_file = chat_dir / "settings.json"
        stats_file = chat_dir / "stats.json"
        users_file = chat_dir / "users.json"
        
        chat_data = {"chat_id": chat_id}
        
        # Загружаем настройки
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    chat_data["settings"] = settings
                    chat_data["daily_quiz_enabled"] = settings.get("daily_quiz", {}).get("enabled", False)
            except:
                pass
        
        # Загружаем статистику
        if stats_file.exists():
            try:
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    chat_data["stats"] = stats
            except:
                pass
        
        # Загружаем пользователей
        if users_file.exists():
            try:
                with open(users_file, 'r', encoding='utf-8') as f:
                    users = json.load(f)
                    chat_data["user_count"] = len(users)
            except:
                pass
        
        chats.append(chat_data)
    
    return {"chats": chats, "total": len(chats)}

@app.get("/api/analytics/chats/{chat_id}")
async def get_chat_analytics(chat_id: str):
    """Получить детальную аналитику чата"""
    chat_dir = CHATS_DIR / chat_id
    if not chat_dir.exists():
        raise HTTPException(status_code=404, detail="Чат не найден")
    
    result = {"chat_id": chat_id}
    
    # Настройки
    settings_file = chat_dir / "settings.json"
    if settings_file.exists():
        with open(settings_file, 'r', encoding='utf-8') as f:
            result["settings"] = json.load(f)
    
    # Статистика
    stats_file = chat_dir / "stats.json"
    if stats_file.exists():
        with open(stats_file, 'r', encoding='utf-8') as f:
            result["stats"] = json.load(f)
    
    # Пользователи
    users_file = chat_dir / "users.json"
    if users_file.exists():
        with open(users_file, 'r', encoding='utf-8') as f:
            users = json.load(f)
            result["users"] = users
            result["user_count"] = len(users)
    
    # Статистика категорий
    cat_stats_file = chat_dir / "categories_stats.json"
    if cat_stats_file.exists():
        with open(cat_stats_file, 'r', encoding='utf-8') as f:
            result["categories_stats"] = json.load(f)
    
    return result

@app.get("/api/analytics/global")
async def get_global_analytics():
    """Получить глобальную аналитику"""
    result = {}
    
    # Глобальная статистика
    global_stats_file = STATS_DIR / "global_stats.json"
    if global_stats_file.exists():
        with open(global_stats_file, 'r', encoding='utf-8') as f:
            result["global_stats"] = json.load(f)
    
    # Статистика категорий
    cat_stats_file = STATS_DIR / "categories_stats.json"
    if cat_stats_file.exists():
        with open(cat_stats_file, 'r', encoding='utf-8') as f:
            result["categories_stats"] = json.load(f)
    
    # Глобальные пользователи
    global_users_file = GLOBAL_DIR / "users.json"
    if global_users_file.exists():
        with open(global_users_file, 'r', encoding='utf-8') as f:
            users = json.load(f)
            result["global_users"] = users
            result["total_global_users"] = len(users)
    
    return result

# ===== УПРАВЛЕНИЕ ПОДПИСКАМИ И НАСТРОЙКАМИ =====

@app.get("/api/chats")
async def get_all_chats(use_telegram_api: bool = True):
    """
    Получить список всех чатов с подробной информацией
    
    Args:
        use_telegram_api: Если True, получает актуальные названия чатов через Telegram API
    """
    chats = []
    
    # Создаем экземпляр бота для получения информации через API (если нужно)
    bot = None
    if use_telegram_api:
        try:
            bot_token = os.getenv("BOT_TOKEN")
            if bot_token:
                from telegram import Bot
                bot = Bot(token=bot_token)
        except Exception as e:
            logger.warning(f"Не удалось создать экземпляр бота для получения названий чатов: {e}")
            bot = None
    
    for chat_dir in CHATS_DIR.iterdir():
        if not chat_dir.is_dir():
            continue
        
        chat_id = chat_dir.name
        settings_file = chat_dir / "settings.json"
        users_file = chat_dir / "users.json"
        stats_file = STATS_DIR / f"{chat_id}.json"
        
        chat_info = {
            "id": int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id,
            "title": None,
            "daily_quiz_enabled": False,
            "daily_quiz_times": [],
            "users_count": 0,
            "total_quizzes": 0,
            "enabled_categories": [],
            "disabled_categories": [],
            "chat_type": None
        }
        
        # Пытаемся получить название через Telegram API
        if bot:
            try:
                chat_id_int = int(chat_id) if chat_id.lstrip('-').isdigit() else None
                if chat_id_int:
                    chat = await bot.get_chat(chat_id_int)
                    # Получаем название в зависимости от типа чата
                    if chat.title:
                        chat_info["title"] = chat.title
                    elif chat.first_name:
                        chat_info["title"] = chat.first_name
                        if chat.last_name:
                            chat_info["title"] += f" {chat.last_name}"
                    chat_info["chat_type"] = chat.type
                    
                    # Обновляем название в локальных настройках (если оно изменилось)
                    if settings_file.exists():
                        try:
                            with open(settings_file, 'r', encoding='utf-8') as f:
                                settings = json.load(f)
                            
                            # Обновляем только если название изменилось
                            if settings.get("title") != chat_info["title"]:
                                settings["title"] = chat_info["title"]
                                settings["chat_type"] = chat_info["chat_type"]
                                with open(settings_file, 'w', encoding='utf-8') as f:
                                    json.dump(settings, f, ensure_ascii=False, indent=2)
                                logger.debug(f"Обновлено название чата {chat_id}: {chat_info['title']}")
                        except Exception as e:
                            logger.debug(f"Не удалось обновить настройки чата {chat_id}: {e}")
            except Exception as e:
                # Если не удалось получить через API, используем локальные данные
                error_msg = str(e).lower()
                if "chat not found" in error_msg or "not found" in error_msg:
                    logger.debug(f"Чат {chat_id} не найден в Telegram (возможно, бот удален из чата)")
                else:
                    logger.debug(f"Не удалось получить информацию о чате {chat_id} через Telegram API: {e}")
        
        # Settings (используем как fallback или для дополнительной информации)
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # Используем локальное название только если не получили через API
                    if not chat_info["title"]:
                        chat_info["title"] = settings.get("title")
                    daily_quiz = settings.get("daily_quiz", {})
                    chat_info["daily_quiz_enabled"] = daily_quiz.get("enabled", False)
                    
                    # Читаем times_msk
                    times_msk_raw = daily_quiz.get("times_msk", [])
                    if times_msk_raw and isinstance(times_msk_raw, list):
                        chat_info["daily_quiz_times"] = times_msk_raw
                    else:
                        chat_info["daily_quiz_times"] = []
                    
                    chat_info["enabled_categories"] = settings.get("enabled_categories") or []
                    chat_info["disabled_categories"] = settings.get("disabled_categories", [])
            except Exception as e:
                logger.debug(f"Error loading settings for chat {chat_id}: {e}")
        
        # Если название все еще не получено, используем дефолтное
        if not chat_info["title"]:
            chat_info["title"] = f"Чат {chat_id}"
        
        # Users count
        if users_file.exists():
            try:
                with open(users_file, 'r', encoding='utf-8') as f:
                    users = json.load(f)
                    chat_info["users_count"] = len(users)
            except:
                pass
        
        # Total quizzes
        if stats_file.exists():
            try:
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    chat_info["total_quizzes"] = stats.get("total_quizzes", 0)
            except:
                pass
        
        chats.append(chat_info)
    
    return chats

@app.get("/api/chats/{chat_id}/settings")
async def get_chat_settings(chat_id: str):
    """Получить настройки чата"""
    settings_file = CHATS_DIR / chat_id / "settings.json"
    if not settings_file.exists():
        raise HTTPException(status_code=404, detail="Настройки чата не найдены")
    
    with open(settings_file, 'r', encoding='utf-8') as f:
        return json.load(f)

@app.put("/api/chats/{chat_id}/settings")
async def update_chat_settings(chat_id: str, settings_update: ChatSettingsUpdate):
    """Обновить настройки чата"""
    settings_file = CHATS_DIR / chat_id / "settings.json"
    
    # Загружаем текущие настройки
    if settings_file.exists():
        with open(settings_file, 'r', encoding='utf-8') as f:
            current_settings = json.load(f)
    else:
        current_settings = {}
    
    # Обновляем настройки
    update_data = settings_update.dict(exclude_none=True)
    
    if "daily_quiz" in update_data:
        if "daily_quiz" not in current_settings:
            current_settings["daily_quiz"] = {}
        current_settings["daily_quiz"].update(update_data["daily_quiz"])
    
    if "default_num_questions" in update_data:
        current_settings["default_num_questions"] = update_data["default_num_questions"]
    
    if "default_open_period_seconds" in update_data:
        current_settings["default_open_period_seconds"] = update_data["default_open_period_seconds"]
    
    if "enabled_categories" in update_data:
        current_settings["enabled_categories"] = update_data["enabled_categories"]
    
    if "disabled_categories" in update_data:
        current_settings["disabled_categories"] = update_data["disabled_categories"]
    
    # Сохраняем
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(current_settings, f, ensure_ascii=False, indent=2)
    
    return {"message": "Настройки обновлены", "settings": current_settings}

@app.post("/api/chats/{chat_id}/daily-quiz/toggle")
async def toggle_daily_quiz(chat_id: str, enabled: bool):
    """Включить/выключить ежедневную викторину для чата"""
    settings_file = CHATS_DIR / chat_id / "settings.json"
    
    if settings_file.exists():
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    else:
        settings = {}
    
    if "daily_quiz" not in settings:
        settings["daily_quiz"] = {}
    
    settings["daily_quiz"]["enabled"] = enabled
    
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    
    return {"message": f"Ежедневная викторина {'включена' if enabled else 'выключена'}", "enabled": enabled}

@app.put("/api/chats/{chat_id}/subscription")
async def update_chat_subscription(chat_id: str, data: dict):
    """Обновить расписание викторин для чата"""
    settings_file = CHATS_DIR / chat_id / "settings.json"
    
    if settings_file.exists():
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    else:
        settings = {}
    
    if "daily_quiz" not in settings:
        settings["daily_quiz"] = {}
    
    # Обновляем enabled
    if "enabled" in data:
        settings["daily_quiz"]["enabled"] = data["enabled"]
    
    # Обновляем времена запуска (используем times_msk как в файле)
    if "times_msk" in data:
        settings["daily_quiz"]["times_msk"] = data["times_msk"]
    elif "times" in data:
        settings["daily_quiz"]["times_msk"] = data["times"]
    
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    
    return {"message": "Расписание обновлено", "daily_quiz": settings["daily_quiz"]}

@app.post("/api/chats/{chat_id}/subscription/toggle")
async def toggle_chat_subscription(chat_id: str, data: dict):
    """Включить/выключить подписку на ежедневные викторины"""
    settings_file = CHATS_DIR / chat_id / "settings.json"
    
    if settings_file.exists():
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    else:
        settings = {}
    
    if "daily_quiz" not in settings:
        settings["daily_quiz"] = {}
    
    enabled = data.get("enabled", False)
    settings["daily_quiz"]["enabled"] = enabled
    
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    
    return {"message": f"Подписка {'включена' if enabled else 'выключена'}", "enabled": enabled}

# ===== РЕЖИМ ОБСЛУЖИВАНИЯ =====

@app.get("/api/maintenance")
async def get_maintenance_mode():
    """Получить статус режима обслуживания"""
    # ИСПРАВЛЕНО: Проверяем maintenance_status.json (актуальный файл, который читает бот)
    maintenance_file = DATA_DIR / "maintenance_status.json"
    if maintenance_file.exists():
        try:
            with open(maintenance_file, 'r', encoding='utf-8') as f:
                maintenance_data = json.load(f)
                return {
                    "mode": "maintenance" if maintenance_data.get("maintenance_mode", False) else "main",
                    "maintenance_mode": maintenance_data.get("maintenance_mode", False),
                    "reason": maintenance_data.get("reason", "")
                }
        except:
            pass
    
    # Fallback на bot_mode.json (для обратной совместимости)
    if BOT_MODE_FILE.exists():
        try:
            with open(BOT_MODE_FILE, 'r', encoding='utf-8') as f:
                mode_data = json.load(f)
                return {
                    "mode": mode_data.get("mode", "main"),
                    "maintenance_mode": mode_data.get("mode") == "maintenance",
                    "reason": mode_data.get("reason", "")
                }
        except:
            pass
    
    return {"mode": "main", "maintenance_mode": False, "reason": ""}

@app.post("/api/maintenance/toggle")
async def toggle_maintenance_mode(enabled: bool, reason: Optional[str] = None):
    """Включить/выключить режим обслуживания"""
    from datetime import datetime
    
    mode_data = {
        "mode": "maintenance" if enabled else "main",
        "reason": reason or ("Техническое обслуживание" if enabled else "Работа основного бота"),
        "timestamp": datetime.now().isoformat()
    }
    
    # Синхронизируем bot_mode.json
    with open(BOT_MODE_FILE, 'w', encoding='utf-8') as f:
        json.dump(mode_data, f, ensure_ascii=False, indent=2)
    
    # ИСПРАВЛЕНО: Синхронизируем с maintenance_status.json (который читает бот)
    maintenance_file = MAINTENANCE_STATUS_FILE
    if enabled:
        # Включаем режим обслуживания (создаем файл)
        maintenance_data = {
            "maintenance_mode": True,
            "reason": reason or "Техническое обслуживание",
            "start_time": datetime.now().isoformat(),
            "chats_notified": [],
            "notification_messages": []
        }
        with open(maintenance_file, 'w', encoding='utf-8') as f:
            json.dump(maintenance_data, f, ensure_ascii=False, indent=2)
    else:
        # Выключаем режим обслуживания (удаляем файл)
        if maintenance_file.exists():
            maintenance_file.unlink()
    
    return {
        "message": f"Режим обслуживания {'включен' if enabled else 'выключен'}",
        "maintenance_mode": enabled
    }

# ===== ЭКСПОРТ/ИМПОРТ =====

@app.get("/api/export/questions")
async def export_questions(format: str = "json"):
    """Экспортировать все вопросы в JSON или CSV"""
    try:
        all_questions = []
        
        # Собираем все вопросы
        for category_file in QUESTIONS_DIR.glob("*.json"):
            with open(category_file, 'r', encoding='utf-8') as f:
                questions = json.load(f)
                category = category_file.stem
                
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    
                    # Поддерживаем оба формата: старый (answers, correct_answer) и новый (options, correct)
                    # Сначала проверяем новый формат
                    options = q.get("options", [])
                    correct = q.get("correct", "")
                    
                    # Если новый формат не найден, проверяем старый
                    if not options:
                        options = q.get("answers", [])
                    
                    # Для correct_answer: если это новый формат (строка), находим индекс
                    if correct and isinstance(correct, str):
                        try:
                            correct_answer_index = options.index(correct) if correct in options else 0
                        except:
                            correct_answer_index = 0
                    else:
                        # Старый формат - индекс напрямую
                        correct_answer_index = q.get("correct_answer", 0)
                    
                    # Если correct не указан, но есть correct_answer как индекс
                    if not correct and isinstance(correct_answer_index, int) and correct_answer_index < len(options):
                        correct = options[correct_answer_index] if options else ""
                    
                    question_data = {
                        "category": category,
                        "question": q.get("question", ""),
                        "options": options,  # Новый формат (массив вариантов)
                        "correct": correct,  # Новый формат (текст правильного ответа)
                        "explanation": q.get("explanation", ""),
                        "difficulty": q.get("difficulty", ""),
                        "tags": q.get("tags", [])
                    }
                    
                    # Для обратной совместимости добавляем старые поля только если нужно
                    # (не добавляем answers, чтобы избежать дублирования)
                    if correct_answer_index is not None:
                        question_data["correct_answer"] = correct_answer_index
                    
                    all_questions.append(question_data)
        
        if format.lower() == "json":
            # Экспорт в JSON
            json_str = json.dumps(all_questions, ensure_ascii=False, indent=2)
            return StreamingResponse(
                io.BytesIO(json_str.encode('utf-8')),
                media_type="application/json",
                headers={"Content-Disposition": "attachment; filename=questions_export.json"}
            )
        
        elif format.lower() == "csv":
            # Экспорт в CSV
            output = io.StringIO()
            if all_questions:
                writer = csv.DictWriter(
                    output, 
                    fieldnames=["category", "question", "options", "correct", "correct_answer", "explanation", "difficulty", "tags"]
                )
                writer.writeheader()
                
                for q in all_questions:
                    options = q.get("options", [])
                    writer.writerow({
                        "category": q["category"],
                        "question": q["question"],
                        "options": "; ".join(options) if isinstance(options, list) else str(options),
                        "correct": q.get("correct", ""),
                        "correct_answer": q.get("correct_answer", 0),
                        "explanation": q.get("explanation", ""),
                        "difficulty": q.get("difficulty", ""),
                        "tags": "; ".join(q.get("tags", [])) if isinstance(q.get("tags"), list) else str(q.get("tags", ""))
                    })
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=questions_export.csv"}
            )
        
        else:
            raise HTTPException(status_code=400, detail="Неподдерживаемый формат. Используйте 'json' или 'csv'")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка экспорта: {str(e)}")

@app.post("/api/import/questions")
async def import_questions(file: UploadFile = File(...)):
    """Импортировать вопросы из JSON файла"""
    try:
        contents = await file.read()
        data = json.loads(contents.decode('utf-8'))
        
        if not isinstance(data, list):
            raise HTTPException(status_code=400, detail="Файл должен содержать массив вопросов")
        
        imported_count = 0
        
        # Группируем вопросы по категориям
        questions_by_category = {}
        for q in data:
            category = q.get("category")
            if not category:
                continue
            
            if category not in questions_by_category:
                questions_by_category[category] = []
            
            questions_by_category[category].append({
                "question": q.get("question", ""),
                "answers": q.get("answers", []),
                "correct_answer": q.get("correct_answer", 0),
                "explanation": q.get("explanation", "")
            })
        
        # Сохраняем вопросы
        for category, questions in questions_by_category.items():
            category_file = QUESTIONS_DIR / f"{category}.json"
            
            # Если категория уже существует, добавляем вопросы
            if category_file.exists():
                with open(category_file, 'r', encoding='utf-8') as f:
                    existing_questions = json.load(f)
                existing_questions.extend(questions)
                questions_to_save = existing_questions
            else:
                questions_to_save = questions
            
            with open(category_file, 'w', encoding='utf-8') as f:
                json.dump(questions_to_save, f, ensure_ascii=False, indent=2)
            
            imported_count += len(questions)
        
        return {"message": f"Импортировано {imported_count} вопросов", "imported": imported_count}
    
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Некорректный JSON файл")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка импорта: {str(e)}")

# ===== ПРОДВИНУТАЯ АНАЛИТИКА =====

@app.get("/api/analytics/categories/detailed")
async def get_categories_detailed_stats():
    """Детальная статистика по категориям"""
    try:
        categories_stats_file = STATS_DIR / "categories_stats.json"
        
        if not categories_stats_file.exists():
            return {"categories": []}
        
        with open(categories_stats_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        
        result = []
        for category, data in stats.items():
            result.append({
                "name": category,
                "total_questions": data.get("total_questions", 0),
                "global_usage": data.get("global_usage", 0),
                "chats_count": len(data.get("chats_used_in", [])),
                "last_used": data.get("last_used", 0),
                "chat_usage": data.get("chat_usage", {})
            })
        
        # Сортируем по использованию
        result.sort(key=lambda x: x["global_usage"], reverse=True)
        
        return {"categories": result}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/users/leaderboard")
async def get_users_leaderboard(limit: int = 20):
    """Рейтинг пользователей"""
    try:
        global_stats_file = STATS_DIR / "global_stats.json"
        
        if not global_stats_file.exists():
            return {"users": []}
        
        with open(global_stats_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        
        top_users = stats.get("top_users", [])[:limit]
        
        # Обогащаем данными из чатов
        enriched_users = []
        for user in top_users:
            user_data = {
                "user_id": user["user_id"],
                "name": user["name"],
                "global_score": user["global_score"],
                "total_answers": 0,
                "chats_participated": []
            }
            
            # Ищем пользователя в чатах
            for chat_dir in CHATS_DIR.iterdir():
                if not chat_dir.is_dir():
                    continue
                
                users_file = chat_dir / "users.json"
                if users_file.exists():
                    with open(users_file, 'r', encoding='utf-8') as f:
                        chat_users = json.load(f)
                    
                    if user["user_id"] in chat_users:
                        user_info = chat_users[user["user_id"]]
                        user_data["total_answers"] += len(user_info.get("answered_polls", []))
                        user_data["chats_participated"].append(chat_dir.name)
            
            enriched_users.append(user_data)
        
        return {"users": enriched_users, "total_count": stats.get("total_users", 0)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/activity/overview")
async def get_activity_overview():
    """Обзор активности"""
    try:
        # Глобальная статистика
        global_stats_file = STATS_DIR / "global_stats.json"
        if global_stats_file.exists():
            with open(global_stats_file, 'r', encoding='utf-8') as f:
                global_stats = json.load(f)
        else:
            global_stats = {}
        
        # Статистика по чатам
        chat_stats = []
        total_messages = 0
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id = chat_dir.name
            stats_file = chat_dir / "stats.json"
            settings_file = chat_dir / "settings.json"
            
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)
                
                total_answered = chat_data.get("total_answered", 0)
                total_messages += total_answered
                
                # Получаем название чата из settings.json
                chat_title = f"Чат {chat_id}"
                if settings_file.exists():
                    try:
                        with open(settings_file, 'r', encoding='utf-8') as f:
                            settings = json.load(f)
                            chat_title = settings.get("title", chat_title)
                    except:
                        pass
                
                chat_stats.append({
                    "chat_id": chat_data.get("chat_id", chat_id),
                    "title": chat_title,
                    "users": chat_data.get("total_users", 0),
                    "score": chat_data.get("total_score", 0),
                    "answered": total_answered
                })
        
        # Сортируем чаты по активности
        chat_stats.sort(key=lambda x: x["answered"], reverse=True)
        
        return {
            "global": {
                "total_users": global_stats.get("total_users", 0),
                "active_users": global_stats.get("active_users", 0),
                "total_score": global_stats.get("total_score", 0),
                "total_answered": global_stats.get("total_answered_polls", 0),
                "average_score": global_stats.get("average_score", 0)
            },
            "chats": chat_stats[:10],  # Топ-10 активных чатов
            "total_chats": len(chat_stats),
            "total_messages": total_messages
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/categories/top")
async def get_top_categories(limit: int = 10):
    """Топ категорий по использованию"""
    try:
        categories_stats_file = STATS_DIR / "categories_stats.json"
        
        if not categories_stats_file.exists():
            return {"categories": []}
        
        with open(categories_stats_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        
        categories = []
        for name, data in stats.items():
            categories.append({
                "name": name,
                "usage": data.get("global_usage", 0),
                "questions": data.get("total_questions", 0),
                "chats": len(data.get("chats_used_in", []))
            })
        
        categories.sort(key=lambda x: x["usage"], reverse=True)
        
        return {"categories": categories[:limit], "total": len(categories)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/distribution/scores")
async def get_score_distribution():
    """Распределение баллов пользователей"""
    try:
        global_stats_file = STATS_DIR / "global_stats.json"
        
        if not global_stats_file.exists():
            return {"distribution": {}}
        
        with open(global_stats_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        
        distribution = stats.get("score_distribution", {})
        
        # Преобразуем в формат для графика
        labels = []
        values = []
        for key in sorted(distribution.keys()):
            labels.append(key)
            values.append(distribution[key])
        
        return {
            "distribution": distribution,
            "chart_data": {
                "labels": labels,
                "values": values
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/chat/{chat_id}/detailed")
async def get_chat_detailed_stats(chat_id: str):
    """Детальная статистика чата"""
    try:
        chat_dir = CHATS_DIR / chat_id
        
        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        # Основная статистика
        stats_file = chat_dir / "stats.json"
        users_file = chat_dir / "users.json"
        categories_file = chat_dir / "categories_stats.json"
        settings_file = chat_dir / "settings.json"
        
        result = {"chat_id": chat_id}
        
        if stats_file.exists():
            with open(stats_file, 'r', encoding='utf-8') as f:
                result["stats"] = json.load(f)
        
        if users_file.exists():
            with open(users_file, 'r', encoding='utf-8') as f:
                users = json.load(f)
                result["users_count"] = len(users)
                result["users"] = users
        
        if categories_file.exists():
            with open(categories_file, 'r', encoding='utf-8') as f:
                result["categories"] = json.load(f)
        
        if settings_file.exists():
            with open(settings_file, 'r', encoding='utf-8') as f:
                result["settings"] = json.load(f)
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ИЗОБРАЖЕНИЯ И PHOTO QUIZ ==================

@app.get("/api/photo-quiz")
async def get_photo_quiz():
    """Получить список всех photo quiz вопросов"""
    try:
        if not PHOTO_QUIZ_METADATA.exists():
            return {"photos": [], "total": 0}
        
        with open(PHOTO_QUIZ_METADATA, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        photos = []
        for name, data in metadata.items():
            image_path = IMAGES_DIR / f"{name}.webp"
            photos.append({
                "name": name,
                "correct_answer": data.get("correct_answer", ""),
                "hints": data.get("hints", {}),
                "has_image": image_path.exists(),
                "image_url": f"/api/images/{name}.webp" if image_path.exists() else None
            })
        
        return {"photos": photos, "total": len(photos)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/images/{filename}")
async def get_image(filename: str):
    """Получить изображение"""
    try:
        image_path = IMAGES_DIR / filename
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Изображение не найдено")
        
        return FileResponse(image_path, media_type="image/webp")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.put("/api/photo-quiz/{name}")
async def update_photo_quiz(name: str, data: Dict[str, Any]):
    """Обновить метаданные photo quiz"""
    try:
        if not PHOTO_QUIZ_METADATA.exists():
            raise HTTPException(status_code=404, detail="Файл метаданных не найден")
        
        with open(PHOTO_QUIZ_METADATA, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        if name not in metadata:
            raise HTTPException(status_code=404, detail="Photo quiz не найден")
        
        metadata[name] = data
        
        with open(PHOTO_QUIZ_METADATA, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return {"success": True, "message": "Обновлено"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ПРОДВИНУТАЯ АНАЛИТИКА ==================

@app.get("/api/analytics/dashboard")
async def get_dashboard_data():
    """Получить данные для главного dashboard - реальные данные из stats.json"""
    try:
        # Собираем статистику из чатов
        chats = []
        total_users = 0
        total_answered = 0
        total_score = 0
        unique_users = set()
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id = chat_dir.name
            stats_file = chat_dir / "stats.json"
            settings_file = chat_dir / "settings.json"
            
            chat_info = {
                "chat_id": chat_id,
                "title": f"Чат {chat_id}",
                "users_count": 0,
                "answered": 0,
                "score": 0,
                "daily_enabled": False
            }
            
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                        chat_info["title"] = settings.get("title", chat_info["title"])
                        chat_info["daily_enabled"] = settings.get("daily_quiz", {}).get("enabled", False)
                except:
                    pass
            
            if stats_file.exists():
                try:
                    with open(stats_file, 'r', encoding='utf-8') as f:
                        stats = json.load(f)
                        chat_info["users_count"] = stats.get("total_users", 0)
                        chat_info["answered"] = stats.get("total_answered", 0)
                        chat_info["score"] = round(stats.get("total_score", 0), 1)
                        
                        total_answered += chat_info["answered"]
                        total_score += stats.get("total_score", 0)
                        
                        # Уникальные пользователи
                        for user_id in stats.get("user_activity", {}).keys():
                            unique_users.add(user_id)
                except:
                    pass
            
            chats.append(chat_info)
        
        total_users = len(unique_users)
        
        # Категории и вопросы
        categories = get_all_categories()
        total_questions_db = 0
        for cat in categories:
            try:
                questions = load_category_questions(cat)
                total_questions_db += len(questions)
            except:
                pass
        
        # Photo quiz
        photo_count = 0
        if PHOTO_QUIZ_METADATA.exists():
            try:
                with open(PHOTO_QUIZ_METADATA, 'r', encoding='utf-8') as f:
                    photo_count = len(json.load(f))
            except:
                pass
        
        # Дополнительные метрики
        active_chats_with_subscription = sum(1 for chat in chats if chat.get("daily_enabled", False))
        avg_answered_per_user = round(total_answered / total_users, 1) if total_users > 0 else 0
        avg_score_per_user = round(total_score / total_users, 2) if total_users > 0 else 0
        
        # Статус бота - проверяем через systemd/процесс
        bot_mode = "main"
        if BOT_MODE_FILE.exists():
            try:
                with open(BOT_MODE_FILE, 'r', encoding='utf-8') as f:
                    mode_data = json.load(f)
                    bot_mode = mode_data.get("mode", "main")
            except:
                pass
        
        # Проверяем реальный статус бота через systemd/процесс
        bot_enabled = check_bot_service_status()
        
        # Активные викторины
        active_quizzes_count = 0
        active_quizzes_file = DATA_DIR / "active_quizzes.json"
        if active_quizzes_file.exists():
            try:
                with open(active_quizzes_file, 'r', encoding='utf-8') as f:
                    active_data = json.load(f)
                    active_quizzes_count = len(active_data.get("active_quizzes", {})) if isinstance(active_data, dict) else 0
            except:
                pass
        
        return {
            "total_users": total_users,
            "total_chats": len(chats),
            "active_chats_with_subscription": active_chats_with_subscription,
            "total_quizzes": total_answered,  # Используем answered как proxy для викторин
            "total_questions_asked": total_answered,
            "total_categories": len(categories),
            "total_questions_db": total_questions_db,
            "total_photo_quiz": photo_count,
            "total_score": round(total_score, 1),
            "avg_answered_per_user": avg_answered_per_user,
            "avg_score_per_user": avg_score_per_user,
            "bot_mode": bot_mode,
            "bot_enabled": bot_enabled,
            "active_quizzes_count": active_quizzes_count,
            "chats_overview": chats
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/charts/activity")
async def get_activity_chart():
    """Получить данные для графика активности - реальные данные из stats.json"""
    try:
        # Загружаем индекс чатов для получения названий
        chats_index_file = GLOBAL_DIR / "chats_index.json"
        chats_index = {}
        if chats_index_file.exists():
            try:
                with open(chats_index_file, 'r', encoding='utf-8') as f:
                    chats_index = json.load(f)
            except:
                pass
        
        # Собираем статистику из всех чатов
        total_users = 0
        total_answered = 0
        total_score = 0
        chats_data = []
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id_str = chat_dir.name
            stats_file = chat_dir / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    chat_users = stats.get("total_users", 0)
                    chat_answered = stats.get("total_answered", 0)
                    chat_score = stats.get("total_score", 0)
                    
                    total_users += chat_users
                    total_answered += chat_answered
                    total_score += chat_score
                    
                    # Получаем название чата: приоритет settings.json (там актуальные данные из API), потом индекс
                    chat_title = None
                    
                    # Сначала проверяем settings.json (там актуальные названия, обновляемые через Telegram API)
                    settings_file = chat_dir / "settings.json"
                    if settings_file.exists():
                        try:
                            with open(settings_file, 'r', encoding='utf-8') as f:
                                settings = json.load(f)
                                chat_title = settings.get("title")
                        except:
                            pass
                    
                    # Если не нашли в settings, проверяем индекс
                    if not chat_title:
                        index_title = chats_index.get(chat_id_str, {}).get("title")
                        if index_title:
                            chat_title = index_title
                    
                    # Если название все еще не получено, используем дефолтное
                    if not chat_title:
                        # Для групп (ID начинается с -) используем более короткое название
                        if chat_id_str.startswith('-'):
                            chat_title = f"Группа {chat_id_str}"
                        else:
                            chat_title = f"Чат {chat_id_str}"
                    
                    # Если название слишком длинное, обрезаем
                    if len(chat_title) > 25:
                        chat_title = chat_title[:22] + "..."
                    
                    chats_data.append({
                        "chat_id": chat_id_str,
                        "chat_title": chat_title,
                        "users": chat_users,
                        "answered": chat_answered,
                        "score": round(chat_score, 1)
                    })
        
        # Сортируем чаты по активности
        chats_data.sort(key=lambda x: x["answered"], reverse=True)
        
        return {
            "labels": [c["chat_title"] for c in chats_data[:10]],
            "data": [c["answered"] for c in chats_data[:10]],
            "users": [c["users"] for c in chats_data[:10]],
            "scores": [c["score"] for c in chats_data[:10]],
            "total_users": total_users,
            "total_answered": total_answered,
            "total_score": round(total_score, 1)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/charts/categories")
async def get_categories_chart():
    """Получить данные для графика категорий - реальные данные"""
    try:
        categories = get_all_categories()
        
        # Собираем данные о категориях с количеством вопросов
        category_data = []
        
        for cat_name in categories:
            questions = load_category_questions(cat_name)
            category_data.append({
                "name": cat_name,
                "count": len(questions)
            })
        
        # Сортируем по количеству вопросов (топ 15)
        category_data.sort(key=lambda x: x["count"], reverse=True)
        top_categories = category_data[:15]
        
        return {
            "labels": [c["name"] for c in top_categories],
            "data": [c["count"] for c in top_categories],
            "question_counts": [c["count"] for c in top_categories],
            "total_categories": len(categories),
            "total_questions": sum(c["count"] for c in category_data)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/charts/users")
async def get_users_chart():
    """Получить данные для графика топ пользователей - реальные данные из stats.json"""
    try:
        all_users = {}
        
        # Собираем пользователей из stats.json каждого чата (там user_activity)
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            stats_file = chat_dir / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    user_activity = stats.get("user_activity", {})
                    
                    for user_id, user_data in user_activity.items():
                        if user_id not in all_users:
                            all_users[user_id] = {
                                "user_id": user_id,
                                "name": user_data.get("name", f"User {user_id}"),
                                "score": 0,
                                "answered": 0,
                                "max_streak": 0
                            }
                        
                        all_users[user_id]["score"] += user_data.get("score", 0)
                        all_users[user_id]["answered"] += user_data.get("answered_count", 0)
                        max_streak = user_data.get("max_consecutive_correct", 0)
                        if max_streak > all_users[user_id]["max_streak"]:
                            all_users[user_id]["max_streak"] = max_streak
        
        # Сортируем по баллам
        users_list = list(all_users.values())
        users_list.sort(key=lambda x: x["score"], reverse=True)
        top_users = users_list[:10]
        
        return {
            "labels": [u["name"] for u in top_users],
            "data": [round(u["score"], 1) for u in top_users],
            "scores": [round(u["score"], 1) for u in top_users],
            "answered": [u["answered"] for u in top_users],
            "streaks": [u["max_streak"] for u in top_users],
            "total_users": len(users_list)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/analytics/charts/score-distribution")
async def get_score_distribution_chart():
    """Получить данные для графика распределения баллов - реальные данные"""
    try:
        score_ranges = {
            "0-50": 0,
            "51-200": 0,
            "201-500": 0,
            "501-1000": 0,
            "1000+": 0
        }
        
        # Собираем пользователей из stats.json
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            stats_file = chat_dir / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    user_activity = stats.get("user_activity", {})
                    
                    for user_data in user_activity.values():
                        score = user_data.get("score", 0)
                        if score <= 50:
                            score_ranges["0-50"] += 1
                        elif score <= 200:
                            score_ranges["51-200"] += 1
                        elif score <= 500:
                            score_ranges["201-500"] += 1
                        elif score <= 1000:
                            score_ranges["501-1000"] += 1
                        else:
                            score_ranges["1000+"] += 1
        
        return {
            "labels": list(score_ranges.keys()),
            "data": list(score_ranges.values()),
            "values": list(score_ranges.values())
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ГЛОБАЛЬНЫЙ РЕЙТИНГ ПОЛЬЗОВАТЕЛЕЙ ==================

@app.get("/api/analytics/leaderboard")
async def get_global_leaderboard(limit: int = 50):
    """Получить глобальный рейтинг пользователей из всех чатов"""
    try:
        all_users = {}
        
        # Собираем пользователей из stats.json каждого чата
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id = chat_dir.name
            stats_file = chat_dir / "stats.json"
            
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    user_activity = stats.get("user_activity", {})
                    
                    for user_id, user_data in user_activity.items():
                        if user_id not in all_users:
                            all_users[user_id] = {
                                "user_id": user_id,
                                "name": user_data.get("name", f"User {user_id}"),
                                "total_score": 0,
                                "total_answered": 0,
                                "max_consecutive_correct": 0,
                                "chats": []
                            }
                        
                        all_users[user_id]["total_score"] += user_data.get("score", 0)
                        all_users[user_id]["total_answered"] += user_data.get("answered_count", 0)
                        
                        max_streak = user_data.get("max_consecutive_correct", 0)
                        if max_streak > all_users[user_id]["max_consecutive_correct"]:
                            all_users[user_id]["max_consecutive_correct"] = max_streak
                        
                        all_users[user_id]["chats"].append({
                            "chat_id": chat_id,
                            "score": round(user_data.get("score", 0), 1),
                            "answered": user_data.get("answered_count", 0)
                        })
        
        # Сортируем по баллам
        users_list = list(all_users.values())
        users_list.sort(key=lambda x: x["total_score"], reverse=True)
        
        # Добавляем место в рейтинге
        for idx, user in enumerate(users_list):
            user["rank"] = idx + 1
            user["total_score"] = round(user["total_score"], 1)
        
        return {
            "leaderboard": users_list[:limit],
            "total_users": len(users_list)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ДЕТАЛЬНАЯ СТАТИСТИКА ЧАТА ==================

@app.get("/api/chats/{chat_id}/detailed")
async def get_chat_detailed(chat_id: str):
    """Получить детальную статистику чата"""
    try:
        chat_dir = CHATS_DIR / chat_id

        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")

        result = {
            "chat_id": chat_id,
            "chat_name": f"Чат {chat_id}",
            "user_count": 0,
            "total_quizzes": 0,
            "daily_quiz_enabled": False,
            "daily_quiz_times": [],
            "top_users": []
        }

        # Загружаем настройки
        settings_file = chat_dir / "settings.json"
        if settings_file.exists():
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                result["chat_name"] = settings.get("title", f"Чат {chat_id}")
                daily_quiz = settings.get("daily_quiz", {})
                result["daily_quiz_enabled"] = daily_quiz.get("enabled", False)

                # Форматируем времена
                times = daily_quiz.get("times_msk", [])
                formatted_times = []
                for t in times:
                    if isinstance(t, dict):
                        h = str(t.get("hour", 0)).zfill(2)
                        m = str(t.get("minute", 0)).zfill(2)
                        formatted_times.append(f"{h}:{m}")
                    else:
                        formatted_times.append(str(t))
                result["daily_quiz_times"] = formatted_times

        # Загружаем статистику
        stats_file = chat_dir / "stats.json"
        if stats_file.exists():
            with open(stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)
                result["user_count"] = stats.get("total_users", 0)
                result["total_quizzes"] = stats.get("total_quizzes", 0)

                # Формируем топ пользователей
                user_activity = stats.get("user_activity", {})
                users_list = []

                for user_id, user_data in user_activity.items():
                    users_list.append({
                        "user_id": user_id,
                        "name": user_data.get("name", f"User {user_id}"),
                        "total_score": round(user_data.get("score", 0), 1)
                    })

                # Сортируем по баллам
                users_list.sort(key=lambda x: x["total_score"], reverse=True)
                result["top_users"] = users_list

        # Загружаем статистику категорий с весами
        categories_stats_file = chat_dir / "categories_stats.json"
        if categories_stats_file.exists():
            with open(categories_stats_file, 'r', encoding='utf-8') as f:
                cat_stats = json.load(f)

                # Получаем веса категорий для данного чата
                try:
                    import sys
                    sys.path.insert(0, str(BASE_DIR))
                    from app_config import AppConfig
                    from state import BotState
                    from data_manager import DataManager
                    from modules.category_manager import CategoryManager

                    app_config = AppConfig()
                    bot_state = BotState(app_config)
                    data_manager = DataManager(app_config)
                    category_manager = CategoryManager(bot_state, app_config, data_manager)

                    # Получаем веса категорий
                    weights_info = category_manager.get_category_weights_for_chat(chat_id)

                    # Создаем словарь для быстрого поиска весов
                    weights_dict = {w["name"]: w for w in weights_info}

                    # Формируем список категорий с полной информацией
                    cat_list = []
                    for cat_name, cat_data in cat_stats.items():
                        chat_usage = cat_data.get("chat_usage", 0)
                        if isinstance(chat_usage, dict):
                            chat_usage = sum(chat_usage.values())

                        weight_data = weights_dict.get(cat_name, {})

                        cat_list.append({
                            "name": cat_name,
                            "usage": int(chat_usage),
                            "total_questions": cat_data.get("total_questions", 0),
                            "weight": round(weight_data.get("weight", 0), 2),
                            "excluded": weight_data.get("excluded", False),
                            "days_since_use": round(weight_data.get("days_since_use", 0), 1)
                        })

                    # Сортируем по использованию
                    cat_list.sort(key=lambda x: x["usage"], reverse=True)
                    result["categories_stats"] = cat_list

                except Exception as e:
                    logger.warning(f"Не удалось загрузить веса категорий для чата {chat_id}: {e}")
                    # Продолжаем без весов - базовая статистика
                    cat_list = []
                    for cat_name, cat_data in cat_stats.items():
                        chat_usage = cat_data.get("chat_usage", 0)
                        if isinstance(chat_usage, dict):
                            chat_usage = sum(chat_usage.values())

                        cat_list.append({
                            "name": cat_name,
                            "usage": int(chat_usage),
                            "total_questions": cat_data.get("total_questions", 0)
                        })

                    cat_list.sort(key=lambda x: x["usage"], reverse=True)
                    result["categories_stats"] = cat_list
        else:
            result["categories_stats"] = []

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== СИСТЕМНЫЕ НАСТРОЙКИ ==================

@app.get("/api/system/status")
async def get_system_status():
    """Получить системный статус бота"""
    try:
        result = {
            "bot_mode": "main",
            "bot_enabled": True,
            "maintenance_reason": ""
        }
        
        # Режим бота - сначала проверяем maintenance_status.json (актуальный файл бота)
        maintenance_file = DATA_DIR / "maintenance_status.json"
        if maintenance_file.exists():
            try:
                with open(maintenance_file, 'r', encoding='utf-8') as f:
                    maint_data = json.load(f)
                    if maint_data.get("maintenance_mode", False):
                        result["bot_mode"] = "maintenance"
                        result["maintenance_reason"] = maint_data.get("reason", "Техническое обслуживание")
            except:
                pass
        
        # Если режим не maintenance, проверяем bot_mode.json
        if result["bot_mode"] == "main" and BOT_MODE_FILE.exists():
            try:
                with open(BOT_MODE_FILE, 'r', encoding='utf-8') as f:
                    mode_data = json.load(f)
                    result["bot_mode"] = mode_data.get("mode", "main")
                    result["maintenance_reason"] = mode_data.get("reason", "")
            except:
                pass
        
        # Статус бота - проверяем через systemd/процесс
        result["bot_enabled"] = check_bot_service_status()
        
        # Активные викторины
        active_quizzes_file = DATA_DIR / "active_quizzes.json"
        active_quizzes_count = 0
        if active_quizzes_file.exists():
            try:
                with open(active_quizzes_file, 'r', encoding='utf-8') as f:
                    active_data = json.load(f)
                    active_quizzes = active_data.get("active_quizzes", {})
                    if isinstance(active_quizzes, dict):
                        active_quizzes_count = len(active_quizzes)
                    elif isinstance(active_quizzes, list):
                        active_quizzes_count = len(active_quizzes)
            except Exception as e:
                if logger:
                    logger.warning(f"Ошибка чтения active_quizzes.json: {e}")
        result["active_quizzes_count"] = active_quizzes_count
        
        # Подписки на ежедневные викторины - считаем чаты с включенными ежедневными викторинами
        daily_subscriptions = 0
        try:
            # Считаем из настроек чатов (основной источник данных)
            for chat_dir in CHATS_DIR.iterdir():
                if not chat_dir.is_dir():
                    continue
                
                settings_file = chat_dir / "settings.json"
                if settings_file.exists():
                    try:
                        with open(settings_file, 'r', encoding='utf-8') as f:
                            settings = json.load(f)
                            daily_quiz = settings.get("daily_quiz", {})
                            if isinstance(daily_quiz, dict) and daily_quiz.get("enabled", False):
                                daily_subscriptions += 1
                    except Exception as e:
                        if logger:
                            logger.debug(f"Ошибка чтения настроек чата {chat_dir.name}: {e}")
                        pass
            
            # Дополнительно проверяем файл подписок (если используется)
            subscriptions_file = SYSTEM_DIR / "daily_quiz_subscriptions.json"
            if subscriptions_file.exists():
                try:
                    with open(subscriptions_file, 'r', encoding='utf-8') as f:
                        subs_data = json.load(f)
                        if isinstance(subs_data, dict) and subs_data:
                            # Если файл содержит данные, используем его как приоритетный источник
                            file_count = len([k for k, v in subs_data.items() if v])
                            if file_count > 0:
                                daily_subscriptions = file_count
                except Exception as e:
                    if logger:
                        logger.debug(f"Ошибка чтения файла подписок: {e}")
                    pass
        except Exception as e:
            if logger:
                logger.warning(f"Ошибка подсчета подписок: {e}")
        
        result["daily_subscriptions"] = daily_subscriptions
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/system/mode")
async def set_system_mode(mode: str, reason: Optional[str] = None):
    """Установить режим работы бота"""
    try:
        if mode not in ["main", "maintenance"]:
            raise HTTPException(status_code=400, detail="Режим должен быть 'main' или 'maintenance'")
        
        mode_data = {
            "mode": mode,
            "reason": reason or ("Техническое обслуживание" if mode == "maintenance" else "Работа основного бота"),
            "timestamp": datetime.now().isoformat()
        }
        
        # Синхронизируем bot_mode.json
        with open(BOT_MODE_FILE, 'w', encoding='utf-8') as f:
            json.dump(mode_data, f, ensure_ascii=False, indent=2)
        
        # ИСПРАВЛЕНО: Синхронизируем с maintenance_status.json (который читает бот)
        maintenance_file = MAINTENANCE_STATUS_FILE
        stop_success = False
        start_success = False
        stop_fallback_success = False
        start_main_success = False
        last_error = ""
        
        if mode == "maintenance":
            # Включаем режим обслуживания (создаем файл)
            maintenance_data = {
                "maintenance_mode": True,
                "reason": reason or "Техническое обслуживание",
                "start_time": datetime.now().isoformat(),
                "chats_notified": [],
                "notification_messages": []
            }
            maintenance_file.parent.mkdir(parents=True, exist_ok=True)
            with open(maintenance_file, 'w', encoding='utf-8') as f:
                json.dump(maintenance_data, f, ensure_ascii=False, indent=2)
            
            # Останавливаем основной бот и запускаем fallback-бота
            stop_commands = [
                ['/usr/bin/sudo', '-n', '/bin/systemctl', 'stop', 'quiz-bot'],
                ['sudo', '-n', '/bin/systemctl', 'stop', 'quiz-bot'],
                ['/bin/systemctl', 'stop', 'quiz-bot'],
            ]
            
            for cmd in stop_commands:
                try:
                    env = os.environ.copy()
                    env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
                    if result.returncode == 0:
                        stop_success = True
                        if logger:
                            logger.info(f"Основной бот остановлен через: {' '.join(cmd)}")
                        break
                except Exception as e:
                    if not last_error:
                        last_error = f"Остановка: {str(e)}"
            
            # Ждем немного перед запуском fallback-бота
            if stop_success:
                await asyncio.sleep(2)
            
            # Пробуем запустить fallback-бота
            start_commands = [
                ['/usr/bin/sudo', '-n', '/bin/systemctl', 'start', 'maintenance-fallback'],
                ['sudo', '-n', '/bin/systemctl', 'start', 'maintenance-fallback'],
                ['/bin/systemctl', 'start', 'maintenance-fallback'],
            ]
            
            for cmd in start_commands:
                try:
                    env = os.environ.copy()
                    env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
                    if result.returncode == 0:
                        start_success = True
                        if logger:
                            logger.info(f"Fallback-бот запущен через: {' '.join(cmd)}")
                        break
                except Exception as e:
                    if not last_error:
                        last_error = f"Запуск fallback: {str(e)}"
            
            if not stop_success or not start_success:
                if logger:
                    logger.warning(f"Не удалось переключиться на fallback-бота: {last_error}")
        else:
            # Выключаем режим обслуживания (удаляем файл)
            try:
                if maintenance_file.exists():
                    maintenance_file.unlink()
            except Exception as e:
                if logger:
                    logger.warning(f"Не удалось удалить maintenance_status.json: {e}")
                # Не критично, продолжаем работу
            
            # Останавливаем fallback-бота и запускаем основной бот
            stop_commands = [
                ['/usr/bin/sudo', '-n', '/bin/systemctl', 'stop', 'maintenance-fallback'],
                ['sudo', '-n', '/bin/systemctl', 'stop', 'maintenance-fallback'],
                ['/bin/systemctl', 'stop', 'maintenance-fallback'],
            ]
            
            for cmd in stop_commands:
                try:
                    env = os.environ.copy()
                    env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                    result = await asyncio.to_thread(
                        subprocess.run,
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        env=env,
                        check=False
                    )
                    if result.returncode == 0:
                        stop_fallback_success = True
                        if logger:
                            logger.info(f"Fallback-бот остановлен через: {' '.join(cmd)}")
                        break
                except subprocess.TimeoutExpired:
                    if logger:
                        logger.debug(f"Таймаут при остановке fallback-бота: {' '.join(cmd)}")
                    continue
                except FileNotFoundError:
                    if logger:
                        logger.debug(f"Команда не найдена: {' '.join(cmd)}")
                    continue
                except Exception as e:
                    # Игнорируем ошибки остановки fallback (может быть не запущен)
                    if logger:
                        logger.debug(f"Ошибка при остановке fallback (игнорируется): {e}")
                    pass
            
            # Ждем немного перед запуском основного бота
            if stop_fallback_success:
                await asyncio.sleep(2)
            
            # Пробуем запустить основной бот
            start_commands = [
                ['/usr/bin/sudo', '-n', '/bin/systemctl', 'start', 'quiz-bot'],
                ['sudo', '-n', '/bin/systemctl', 'start', 'quiz-bot'],
                ['/bin/systemctl', 'start', 'quiz-bot'],
            ]
            
            for cmd in start_commands:
                try:
                    env = os.environ.copy()
                    env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                    result = await asyncio.to_thread(
                        subprocess.run,
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        env=env,
                        check=False
                    )
                    if result.returncode == 0:
                        start_main_success = True
                        if logger:
                            logger.info(f"Основной бот запущен через: {' '.join(cmd)}")
                        break
                    else:
                        if not last_error:
                            last_error = f"Запуск основного: код {result.returncode}, stderr: {result.stderr[:200]}"
                except subprocess.TimeoutExpired:
                    if not last_error:
                        last_error = f"Таймаут при запуске основного бота"
                    if logger:
                        logger.warning(f"Таймаут при выполнении команды: {' '.join(cmd)}")
                except FileNotFoundError:
                    if logger:
                        logger.debug(f"Команда не найдена: {' '.join(cmd)}")
                    continue
                except Exception as e:
                    if not last_error:
                        last_error = f"Запуск основного: {str(e)[:200]}"
                    if logger:
                        logger.error(f"Ошибка при запуске основного бота: {e}", exc_info=True)
            
            if not start_main_success:
                if logger:
                    logger.warning(f"Не удалось запустить основной бот: {last_error}")
        
        # Формируем результат
        result_data = {
            "success": True, 
            "mode": mode, 
            "reason": mode_data["reason"]
        }
        
        if mode == "maintenance":
            result_data["main_bot_stopped"] = stop_success
            result_data["fallback_bot_started"] = start_success
            if not stop_success or not start_success:
                result_data["warning"] = "Не удалось полностью переключиться на fallback-бота"
        else:
            result_data["fallback_bot_stopped"] = stop_fallback_success
            result_data["main_bot_started"] = start_main_success
            if not start_main_success:
                result_data["warning"] = "Не удалось запустить основной бот"
        
        return result_data
    
    except HTTPException:
        raise
    except Exception as e:
        error_detail = str(e)
        if logger:
            logger.error(f"Критическая ошибка в set_system_mode: {e}", exc_info=True)
        # Не падаем, а возвращаем частичный успех с предупреждением
        try:
            # Пытаемся хотя бы сохранить режим в файл
            mode_data = {
                "mode": mode if 'mode' in locals() else "unknown",
                "reason": reason if 'reason' in locals() else "Ошибка при переключении",
                "timestamp": datetime.now().isoformat()
            }
            with open(BOT_MODE_FILE, 'w', encoding='utf-8') as f:
                json.dump(mode_data, f, ensure_ascii=False, indent=2)
        except Exception as file_error:
            if logger:
                logger.error(f"Не удалось сохранить режим в файл: {file_error}")
        
        # Возвращаем ошибку, но веб-сервер не падает
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка при переключении режима: {error_detail[:500]}. Режим сохранен в файл, но переключение сервисов могло не выполниться."
        )

@app.post("/api/system/bot-status")
async def set_bot_status(enabled: bool):
    """
    Управление статусом бота через systemd.
    enabled=True - запустить сервис, enabled=False - остановить.
    Использует различные методы для обхода ограничений sudo.
    """
    try:
        action = 'start' if enabled else 'stop'
        
        # Пробуем разные методы выполнения команды
        commands_to_try = [
            ['sudo', '-n', 'systemctl', action, 'quiz-bot'],
            ['systemctl', '--user', action, 'quiz-bot'],
            ['systemctl', action, 'quiz-bot'],
            ['pkexec', 'systemctl', action, 'quiz-bot']
        ]
        
        success = False
        last_error = None
        
        # Получаем информацию о текущем пользователе для диагностики
        current_user = os.getenv('USER', os.getenv('USERNAME', 'unknown'))
        effective_user = os.geteuid()
        if logger:
            logger.info(f"Управление ботом: action={action}, USER={current_user}, EUID={effective_user}")
        
        for cmd in commands_to_try:
            try:
                # Используем env для передачи переменных окружения
                env = os.environ.copy()
                # Убеждаемся, что PATH содержит нужные директории
                env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                
                if logger:
                    logger.debug(f"Попытка выполнения команды: {' '.join(cmd)}")
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                    # Важно: используем shell=False для безопасности, но убеждаемся что команды абсолютные
                )
                if result.returncode == 0:
                    success = True
                    if logger:
                        logger.info(f"Бот {'запущен' if enabled else 'остановлен'} через команду: {' '.join(cmd)}")
                    break
                else:
                    if result.stderr:
                        last_error = result.stderr.strip()
                    elif result.stdout:
                        last_error = result.stdout.strip()
                    else:
                        last_error = f"Команда завершилась с кодом {result.returncode}"
                    if logger:
                        logger.debug(f"Команда {' '.join(cmd)} не сработала: {last_error}")
            except subprocess.TimeoutExpired:
                last_error = f"Таймаут при {action} бота"
                if logger:
                    logger.warning(f"Таймаут при выполнении команды: {' '.join(cmd)}")
            except FileNotFoundError:
                if logger:
                    logger.debug(f"Команда не найдена: {' '.join(cmd)}")
                continue
            except Exception as e:
                last_error = str(e)
                if logger:
                    logger.debug(f"Ошибка при выполнении команды {' '.join(cmd)}: {e}")
        
        if not success:
            error_msg = f"Не удалось {'запустить' if enabled else 'остановить'} бота. Ошибка: {last_error}"
            if "Interactive authentication required" in str(last_error):
                error_msg += "\n\nРешение: Настройте sudo без пароля. См. docs/SUDO_SETUP.md"
            
            if logger:
                logger.error(f"Не удалось {action} бота: {last_error}")
            
            raise HTTPException(
                status_code=500,
                detail=error_msg
            )
        
        # Ждем немного перед проверкой статуса
        await asyncio.sleep(1)
        
        # Проверяем реальный статус после операции
        actual_status = check_bot_service_status()
        
        return {
            "success": True,
            "enabled": actual_status,
            "message": "Бот запущен" if actual_status else "Бот остановлен"
        }
    
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Таймаут при управлении сервисом")
    except HTTPException:
        raise
    except Exception as e:
        if logger:
            logger.error(f"Ошибка при управлении статусом бота: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/system/restart-bot")
async def restart_bot():
    """
    Перезапустить бота через systemd (аналог menu.sh опция 8).
    Использует различные методы для обхода ограничений sudo.
    """
    try:
        # Метод 1: Пробуем через sudo без пароля (если настроено)
        # Используем абсолютные пути, так как systemd сервис может иметь ограниченный PATH
        commands_to_try = [
            ['/usr/bin/sudo', '-n', '/bin/systemctl', 'restart', 'quiz-bot'],
            ['sudo', '-n', '/bin/systemctl', 'restart', 'quiz-bot'],
            ['/usr/bin/sudo', '-n', 'systemctl', 'restart', 'quiz-bot'],
            ['sudo', '-n', 'systemctl', 'restart', 'quiz-bot'],
            ['/bin/systemctl', '--user', 'restart', 'quiz-bot'],
            ['systemctl', '--user', 'restart', 'quiz-bot'],
            ['/bin/systemctl', 'restart', 'quiz-bot'],
            ['systemctl', 'restart', 'quiz-bot'],
        ]
        
        success = False
        last_error = None
        
        # Получаем информацию о текущем пользователе для диагностики
        current_user = os.getenv('USER', os.getenv('USERNAME', 'unknown'))
        effective_user = os.geteuid()
        if logger:
            logger.info(f"Перезапуск бота: USER={current_user}, EUID={effective_user}")
        
        for cmd in commands_to_try:
            try:
                # Используем env для передачи переменных окружения
                env = os.environ.copy()
                # Убеждаемся, что PATH содержит нужные директории
                env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                
                if logger:
                    logger.debug(f"Попытка выполнения команды: {' '.join(cmd)}")
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env
                )
                if result.returncode == 0:
                    success = True
                    if logger:
                        logger.info(f"Бот перезапущен через команду: {' '.join(cmd)}")
                    break
                else:
                    # Сохраняем ошибку, но продолжаем пробовать другие команды
                    if result.stderr:
                        last_error = result.stderr.strip()
                    elif result.stdout:
                        last_error = result.stdout.strip()
                    else:
                        last_error = f"Команда завершилась с кодом {result.returncode}"
                    if logger:
                        logger.debug(f"Команда {' '.join(cmd)} не сработала: {last_error}")
            except subprocess.TimeoutExpired:
                last_error = "Таймаут при перезапуске"
                if logger:
                    logger.warning(f"Таймаут при выполнении команды: {' '.join(cmd)}")
            except FileNotFoundError:
                # Команда не найдена, пробуем следующую
                if logger:
                    logger.debug(f"Команда не найдена: {' '.join(cmd)}")
                continue
            except Exception as e:
                last_error = str(e)
                if logger:
                    logger.debug(f"Ошибка при выполнении команды {' '.join(cmd)}: {e}")
        
        if not success:
            # Если все методы не сработали, возвращаем инструкцию
            error_msg = f"Не удалось перезапустить бота. Ошибка: {last_error}"
            if "Interactive authentication required" in str(last_error):
                error_msg += "\n\nРешение: Настройте sudo без пароля. См. docs/SUDO_SETUP.md"
            
            if logger:
                logger.error(f"Не удалось перезапустить бота: {last_error}")
            
            raise HTTPException(
                status_code=500,
                detail=error_msg
            )
        
        # Даем боту время на запуск
        await asyncio.sleep(2)
        
        # Проверяем статус после перезапуска
        actual_status = check_bot_service_status()
        
        return {
            "success": True,
            "enabled": actual_status,
            "message": "Бот перезапущен успешно" if actual_status else "Бот перезапущен, но не запущен"
        }
    
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Таймаут при перезапуске сервиса")
    except HTTPException:
        raise
    except Exception as e:
        if logger:
            logger.error(f"Ошибка при перезапуске бота: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/system/detailed-status")
async def get_detailed_status():
    """
    Получить детальный статус системы (аналог simple_switcher.py status + systemctl).
    """
    try:
        # Базовая информация
        result = {
            "bot_process_running": False,
            "bot_service_status": "unknown",
            "bot_mode": "main",
            "maintenance_reason": "",
            "service_details": {}
        }
        
        # Проверяем статус сервиса
        result["bot_process_running"] = check_bot_service_status()
        
        # Получаем детальный статус из systemctl
        try:
            # Пробуем с sudo, затем без него
            commands_to_try = [
                ['sudo', '-n', 'systemctl', 'status', 'quiz-bot', '--no-pager', '-l'],
                ['systemctl', 'status', 'quiz-bot', '--no-pager', '-l']
            ]
            
            status_result = None
            for cmd in commands_to_try:
                try:
                    status_result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    if status_result.returncode in [0, 3]:  # 0=running, 3=stopped
                        break
                except:
                    continue
            
            if not status_result:
                status_result = subprocess.run(
                    ['echo', 'systemctl недоступен'],
                    capture_output=True,
                    text=True
                )
            # Берем первые 10 строк статуса
            status_lines = status_result.stdout.split('\n')[:10]
            result["service_details"]["status_output"] = '\n'.join(status_lines)
            
            # Определяем статус из вывода
            if 'Active: active (running)' in status_result.stdout:
                result["bot_service_status"] = "active"
            elif 'Active: inactive' in status_result.stdout:
                result["bot_service_status"] = "inactive"
            elif 'Active: failed' in status_result.stdout:
                result["bot_service_status"] = "failed"
            else:
                result["bot_service_status"] = "unknown"
        except:
            pass
        
        # Проверяем режим из bot_mode.json
        if BOT_MODE_FILE.exists():
            try:
                with open(BOT_MODE_FILE, 'r', encoding='utf-8') as f:
                    mode_data = json.load(f)
                    result["bot_mode"] = mode_data.get("mode", "main")
                    result["maintenance_reason"] = mode_data.get("reason", "")
            except:
                pass
        
        # Проверяем также maintenance_status.json (актуальный файл бота)
        maintenance_file = MAINTENANCE_STATUS_FILE
        if maintenance_file.exists():
            try:
                with open(maintenance_file, 'r', encoding='utf-8') as f:
                    maint_data = json.load(f)
                    if maint_data.get("maintenance_mode", False):
                        result["bot_mode"] = "maintenance"
                        result["maintenance_reason"] = maint_data.get("reason", result["maintenance_reason"])
                        result["service_details"]["maintenance_start"] = maint_data.get("start_time", "")
            except:
                pass
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== PHOTO QUIZ CRUD ==================

@app.post("/api/photo-quiz")
async def create_photo_quiz(name: str, correct_answer: str, hints: Optional[Dict] = None):
    """Создать новую photo quiz запись"""
    try:
        if not PHOTO_QUIZ_METADATA.exists():
            metadata = {}
        else:
            with open(PHOTO_QUIZ_METADATA, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        
        if name in metadata:
            raise HTTPException(status_code=400, detail=f"Photo quiz '{name}' уже существует")
        
        # Создаем запись
        metadata[name] = {
            "correct_answer": correct_answer,
            "hints": hints or {
                "length": len(correct_answer),
                "first_letter": correct_answer[0] if correct_answer else "",
                "partial": correct_answer[0] + "_" * (len(correct_answer) - 1) if len(correct_answer) > 1 else correct_answer
            }
        }
        
        with open(PHOTO_QUIZ_METADATA, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return {"success": True, "message": f"Photo quiz '{name}' создан", "data": metadata[name]}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.delete("/api/photo-quiz/{name}")
async def delete_photo_quiz(name: str):
    """Удалить photo quiz"""
    try:
        if not PHOTO_QUIZ_METADATA.exists():
            raise HTTPException(status_code=404, detail="Файл метаданных не найден")
        
        with open(PHOTO_QUIZ_METADATA, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        if name not in metadata:
            raise HTTPException(status_code=404, detail=f"Photo quiz '{name}' не найден")
        
        # Удаляем запись
        del metadata[name]
        
        with open(PHOTO_QUIZ_METADATA, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # Удаляем изображение если есть
        image_path = IMAGES_DIR / f"{name}.webp"
        if image_path.exists():
            image_path.unlink()
        
        return {"success": True, "message": f"Photo quiz '{name}' удален"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/photo-quiz/{name}/upload-image")
async def upload_photo_quiz_image(name: str, file: UploadFile = File(...)):
    """Загрузить изображение для photo quiz"""
    try:
        if not PHOTO_QUIZ_METADATA.exists():
            raise HTTPException(status_code=404, detail="Файл метаданных не найден")
        
        with open(PHOTO_QUIZ_METADATA, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        if name not in metadata:
            raise HTTPException(status_code=404, detail=f"Photo quiz '{name}' не найден")
        
        # Проверяем тип файла
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Файл должен быть изображением")
        
        # Создаем папку если нет
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем файл
        image_path = IMAGES_DIR / f"{name}.webp"
        with open(image_path, 'wb') as f:
            content = await file.read()
            f.write(content)
        
        return {"success": True, "message": "Изображение загружено", "image_url": f"/api/images/{name}.webp"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== РАСШИРЕННАЯ АНАЛИТИКА ==================

@app.get("/api/analytics/summary")
async def get_analytics_summary():
    """Получить сводку аналитики для раздела Аналитика"""
    try:
        # Категории
        categories = get_all_categories()
        total_questions = 0
        category_stats = []
        
        for cat_name in categories:
            questions = load_category_questions(cat_name)
            count = len(questions)
            total_questions += count
            category_stats.append({
                "name": cat_name,
                "questions": count
            })
        
        category_stats.sort(key=lambda x: x["questions"], reverse=True)
        
        # Пользователи из всех чатов
        all_users = {}
        chats_stats = []
        total_answered_all = 0
        total_score_all = 0
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id = chat_dir.name
            stats_file = chat_dir / "stats.json"
            settings_file = chat_dir / "settings.json"
            
            chat_info = {
                "chat_id": chat_id,
                "title": f"Чат {chat_id}",
                "users": 0,
                "answered": 0,
                "score": 0,
                "daily_enabled": False
            }
            
            if settings_file.exists():
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    chat_info["title"] = settings.get("title", chat_info["title"])
                    chat_info["daily_enabled"] = settings.get("daily_quiz", {}).get("enabled", False)
            
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    chat_info["users"] = stats.get("total_users", 0)
                    chat_info["answered"] = stats.get("total_answered", 0)
                    chat_info["score"] = round(stats.get("total_score", 0), 1)
                    
                    total_answered_all += chat_info["answered"]
                    total_score_all += chat_info["score"]
                    
                    # Собираем пользователей
                    for user_id, user_data in stats.get("user_activity", {}).items():
                        if user_id not in all_users:
                            all_users[user_id] = {
                                "name": user_data.get("name", f"User {user_id}"),
                                "score": 0,
                                "answered": 0
                            }
                        all_users[user_id]["score"] += user_data.get("score", 0)
                        all_users[user_id]["answered"] += user_data.get("answered_count", 0)
            
            chats_stats.append(chat_info)
        
        chats_stats.sort(key=lambda x: x["answered"], reverse=True)
        
        # Топ пользователей
        users_list = [{"user_id": uid, **data} for uid, data in all_users.items()]
        users_list.sort(key=lambda x: x["score"], reverse=True)
        for idx, user in enumerate(users_list):
            user["rank"] = idx + 1
            user["score"] = round(user["score"], 1)
        
        # Photo quiz
        photo_count = 0
        if PHOTO_QUIZ_METADATA.exists():
            with open(PHOTO_QUIZ_METADATA, 'r', encoding='utf-8') as f:
                photo_count = len(json.load(f))
        
        return {
            "overview": {
                "total_categories": len(categories),
                "total_questions": total_questions,
                "total_users": len(all_users),
                "total_chats": len(chats_stats),
                "total_answered": total_answered_all,
                "total_score": round(total_score_all, 1),
                "total_photos": photo_count
            },
            "top_categories": category_stats[:10],
            "top_users": users_list[:20],
            "chats": chats_stats
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ЭКСПОРТ СТАТИСТИКИ ==================

# ================== ПОЛНАЯ СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ==================

@app.get("/api/users")
async def get_all_users_full():
    """Получить полную информацию о всех пользователях из всех чатов"""
    try:
        all_users = {}
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id = chat_dir.name
            stats_file = chat_dir / "stats.json"
            settings_file = chat_dir / "settings.json"
            
            # Получаем название чата
            chat_title = f"Чат {chat_id}"
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                        chat_title = settings.get("title", chat_title)
                except:
                    pass
            
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    user_activity = stats.get("user_activity", {})
                    
                    for user_id, user_data in user_activity.items():
                        if user_id not in all_users:
                            all_users[user_id] = {
                                "user_id": user_id,
                                "name": user_data.get("name", f"User {user_id}"),
                                "total_score": 0,
                                "total_answered": 0,
                                "max_streak": 0,
                                "streak_achievements": 0,
                                "first_activity": None,
                                "last_activity": None,
                                "chats_activity": []
                            }
                        
                        # Агрегируем данные
                        all_users[user_id]["total_score"] += user_data.get("score", 0)
                        all_users[user_id]["total_answered"] += user_data.get("answered_count", 0)
                        all_users[user_id]["streak_achievements"] += user_data.get("streak_achievements_count", 0)
                        
                        # Максимальная серия
                        max_consec = user_data.get("max_consecutive_correct", 0)
                        if max_consec > all_users[user_id]["max_streak"]:
                            all_users[user_id]["max_streak"] = max_consec
                        
                        # Даты активности
                        first_ans = user_data.get("first_answer")
                        last_ans = user_data.get("last_answer")
                        
                        if first_ans:
                            if all_users[user_id]["first_activity"] is None or first_ans < all_users[user_id]["first_activity"]:
                                all_users[user_id]["first_activity"] = first_ans
                        
                        if last_ans:
                            if all_users[user_id]["last_activity"] is None or last_ans > all_users[user_id]["last_activity"]:
                                all_users[user_id]["last_activity"] = last_ans
                        
                        # Активность в чате
                        all_users[user_id]["chats_activity"].append({
                            "chat_id": chat_id,
                            "chat_title": chat_title,
                            "score": round(user_data.get("score", 0), 2),
                            "answered_count": user_data.get("answered_count", 0),
                            "consecutive_correct": user_data.get("consecutive_correct", 0),
                            "max_consecutive_correct": user_data.get("max_consecutive_correct", 0),
                            "first_answer": user_data.get("first_answer"),
                            "last_answer": user_data.get("last_answer"),
                            "streak_achievements_count": user_data.get("streak_achievements_count", 0)
                        })
        
        # Сортируем по баллам
        users_list = list(all_users.values())
        users_list.sort(key=lambda x: x["total_score"], reverse=True)
        
        # Добавляем место и округляем
        for idx, user in enumerate(users_list):
            user["rank"] = idx + 1
            user["total_score"] = round(user["total_score"], 2)
            user["chats_count"] = len(user["chats_activity"])
        
        return {
            "users": users_list,
            "total": len(users_list)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

def decode_achievement(achievement_id: str) -> Dict[str, Any]:
    """Декодирует ID достижения в человеко-читаемый формат"""
    try:
        # chat_achievement_{chat_id}_{user_id}_{score}
        if achievement_id.startswith("chat_achievement_"):
            parts = achievement_id.split("_")
            if len(parts) >= 4:
                score = parts[-1]
                return {
                    "type": "chat",
                    "icon": "🏆",
                    "title": f"Достижение чата: {score} очков",
                    "description": f"Набрано {score} баллов в чате"
                }
        
        # motivational_{chat_id}_{user_id}_{count} или motivational_{user_id}_{count}
        elif achievement_id.startswith("motivational_"):
            parts = achievement_id.split("_")
            count = parts[-1]
            is_global = len(parts) == 3  # motivational_{user_id}_{count}
            
            return {
                "type": "motivational",
                "icon": "⭐",
                "title": f"Мотивационное: {count} ответов",
                "description": f"Дано {count} правильных ответов" + (" (глобально)" if is_global else " (в чате)")
            }
        
        # streak achievement (серия)
        elif "_streak_" in achievement_id:
            parts = achievement_id.split("_")
            streak_count = parts[-1]
            return {
                "type": "streak",
                "icon": "🔥",
                "title": f"Серия: {streak_count} подряд",
                "description": f"Серия из {streak_count} правильных ответов подряд"
            }
        
        # Неизвестный тип
        return {
            "type": "unknown",
            "icon": "🎖️",
            "title": "Достижение",
            "description": achievement_id
        }
    except:
        return {
            "type": "unknown",
            "icon": "🎖️",
            "title": "Достижение",
            "description": achievement_id
        }

@app.get("/api/users/{user_id}")
async def get_user_details(user_id: str):
    """Получить детальную информацию о конкретном пользователе"""
    try:
        user_data = {
            "user_id": user_id,
            "name": None,
            "total_score": 0,
            "total_answered": 0,
            "max_streak": 0,
            "streak_achievements": 0,
            "first_activity": None,
            "last_activity": None,
            "chats_activity": [],
            "answered_polls_count": 0,
            "achievements": []  # Новое поле для ачивок
        }
        
        found = False
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id = chat_dir.name
            stats_file = chat_dir / "stats.json"
            users_file = chat_dir / "users.json"
            settings_file = chat_dir / "settings.json"
            
            # Название чата
            chat_title = f"Чат {chat_id}"
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                        chat_title = settings.get("title", chat_title)
                except:
                    pass
            
            # Статистика из stats.json
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    user_activity = stats.get("user_activity", {})
                    
                    if user_id in user_activity:
                        found = True
                        activity = user_activity[user_id]
                        
                        if user_data["name"] is None:
                            user_data["name"] = activity.get("name", f"User {user_id}")
                        
                        user_data["total_score"] += activity.get("score", 0)
                        user_data["total_answered"] += activity.get("answered_count", 0)
                        user_data["streak_achievements"] += activity.get("streak_achievements_count", 0)
                        
                        max_consec = activity.get("max_consecutive_correct", 0)
                        if max_consec > user_data["max_streak"]:
                            user_data["max_streak"] = max_consec
                        
                        first_ans = activity.get("first_answer")
                        last_ans = activity.get("last_answer")
                        
                        if first_ans:
                            if user_data["first_activity"] is None or first_ans < user_data["first_activity"]:
                                user_data["first_activity"] = first_ans
                        
                        if last_ans:
                            if user_data["last_activity"] is None or last_ans > user_data["last_activity"]:
                                user_data["last_activity"] = last_ans
                        
                        chat_activity = {
                            "chat_id": chat_id,
                            "chat_title": chat_title,
                            "score": round(activity.get("score", 0), 2),
                            "answered_count": activity.get("answered_count", 0),
                            "consecutive_correct": activity.get("consecutive_correct", 0),
                            "max_consecutive_correct": activity.get("max_consecutive_correct", 0),
                            "first_answer": activity.get("first_answer"),
                            "last_answer": activity.get("last_answer"),
                            "streak_achievements_count": activity.get("streak_achievements_count", 0)
                        }
                        user_data["chats_activity"].append(chat_activity)
            
            # Количество отвеченных опросов из users.json + ачивки
            if users_file.exists():
                try:
                    with open(users_file, 'r', encoding='utf-8') as f:
                        users = json.load(f)
                        if user_id in users:
                            user_info = users[user_id]
                            polls = user_info.get("answered_polls", [])
                            user_data["answered_polls_count"] += len(polls)
                            
                            # Собираем ачивки
                            milestones = user_info.get("milestones_achieved", [])
                            
                            if isinstance(milestones, (list, set)):
                                for milestone_id in milestones:
                                    try:
                                        decoded = decode_achievement(milestone_id)
                                        if decoded:
                                            decoded["chat_id"] = chat_id
                                            decoded["chat_title"] = chat_title
                                            user_data["achievements"].append(decoded)
                                    except Exception as e:
                                        if logger:
                                            logger.warning(f"Ошибка декодирования ачивки {milestone_id}: {e}")
                                        continue
                except Exception as e:
                    if logger:
                        logger.error(f"Ошибка при чтении ачивок пользователя {user_id} из {chat_id}: {e}")
                    pass
        
        # Также проверяем global/users.json для глобальных ачивок
        global_users_file = GLOBAL_DIR / "users.json"
        if global_users_file.exists():
            try:
                with open(global_users_file, 'r', encoding='utf-8') as f:
                    global_users = json.load(f)
                    
                    if user_id in global_users:
                        global_user = global_users[user_id]
                        
                        # Глобальные ачивки
                        global_milestones = global_user.get("milestones_achieved", [])
                        
                        if isinstance(global_milestones, (list, set)):
                            for milestone_id in global_milestones:
                                try:
                                    # Проверяем, не добавили ли мы уже эту ачивку из конкретного чата
                                    already_added = any(
                                        a.get("description", "").endswith(milestone_id.split("_")[-1]) and 
                                        milestone_id.split("_")[0] in a.get("description", "") 
                                        for a in user_data["achievements"]
                                    )
                                    if not already_added:
                                        decoded = decode_achievement(milestone_id)
                                        if decoded:
                                            decoded["chat_id"] = "global"
                                            decoded["chat_title"] = "Глобальные"
                                            user_data["achievements"].append(decoded)
                                except Exception as e:
                                    if logger:
                                        logger.warning(f"Ошибка декодирования глобальной ачивки {milestone_id}: {e}")
                                    continue
            except Exception as e:
                if logger:
                    logger.error(f"Ошибка при чтении глобальных ачивок пользователя {user_id}: {e}", exc_info=True)
                pass
        
        if not found:
            raise HTTPException(status_code=404, detail=f"Пользователь {user_id} не найден")
        
        user_data["total_score"] = round(user_data["total_score"], 2)
        user_data["chats_count"] = len(user_data["chats_activity"])
        
        # Сортируем ачивки: сначала по типу, затем по количеству (из title)
        type_order = {"streak": 0, "chat": 1, "motivational": 2, "unknown": 3}
        def get_number_from_title(title):
            import re
            numbers = re.findall(r'\d+', title)
            return int(numbers[0]) if numbers else 0
        
        user_data["achievements"].sort(
            key=lambda x: (type_order.get(x["type"], 999), -get_number_from_title(x["title"]))
        )
        
        return user_data
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        if logger:
            logger.error(f"Ошибка в get_user_details для {user_id}: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ПОЛНАЯ СТАТИСТИКА ЧАТОВ ==================

@app.get("/api/chats/{chat_id}/full")
async def get_chat_full_info(chat_id: str):
    """Получить полную информацию о чате включая все настройки, статистику и пользователей"""
    try:
        chat_dir = CHATS_DIR / chat_id
        
        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        # Загружаем chats_index для получения метаданных
        chats_index_file = GLOBAL_DIR / "chats_index.json"
        chat_meta = {}
        if chats_index_file.exists():
            with open(chats_index_file, 'r', encoding='utf-8') as f:
                chats_index = json.load(f)
                chat_meta = chats_index.get(chat_id, {})
        
        result = {
            "chat_id": chat_id,
            "type": chat_meta.get("type", "unknown"),
            "title": chat_meta.get("title", f"Чат {chat_id}"),
            "migration_date": chat_meta.get("migration_date"),
            "settings": {},
            "stats": {
                "total_users": 0,
                "total_score": 0,
                "total_answered": 0
            },
            "users": [],
            "categories_stats": {},
            "daily_quiz_config": {}
        }
        
        # Настройки
        settings_file = chat_dir / "settings.json"
        if settings_file.exists():
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                result["settings"] = settings
                result["title"] = settings.get("title", result["title"])
                result["daily_quiz_config"] = settings.get("daily_quiz", {})
        
        # Статистика и пользователи
        stats_file = chat_dir / "stats.json"
        if stats_file.exists():
            with open(stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)
                result["stats"] = {
                    "total_users": stats.get("total_users", 0),
                    "total_score": round(stats.get("total_score", 0), 2),
                    "total_answered": stats.get("total_answered", 0)
                }
                
                # Пользователи с полной информацией
                users_list = []
                for user_id, user_data in stats.get("user_activity", {}).items():
                    users_list.append({
                        "user_id": user_id,
                        "name": user_data.get("name", f"User {user_id}"),
                        "score": round(user_data.get("score", 0), 2),
                        "answered_count": user_data.get("answered_count", 0),
                        "consecutive_correct": user_data.get("consecutive_correct", 0),
                        "max_consecutive_correct": user_data.get("max_consecutive_correct", 0),
                        "first_answer": user_data.get("first_answer"),
                        "last_answer": user_data.get("last_answer"),
                        "streak_achievements_count": user_data.get("streak_achievements_count", 0)
                    })
                
                # Сортируем по баллам
                users_list.sort(key=lambda x: x["score"], reverse=True)
                for idx, user in enumerate(users_list):
                    user["rank"] = idx + 1
                
                result["users"] = users_list
        
        # Статистика по категориям
        categories_stats_file = chat_dir / "categories_stats.json"
        if categories_stats_file.exists():
            with open(categories_stats_file, 'r', encoding='utf-8') as f:
                cat_stats = json.load(f)
                # Преобразуем в список и сортируем
                cat_list = []
                for cat_name, cat_data in cat_stats.items():
                    # Поддержка обоих форматов chat_usage
                    chat_usage_data = cat_data.get("chat_usage", 0)
                    if isinstance(chat_usage_data, dict):
                        # Новый формат: берем значение для текущего чата или сумму всех
                        chat_usage = sum(chat_usage_data.values())
                    elif isinstance(chat_usage_data, (int, float)):
                        # Старый формат: просто число
                        chat_usage = int(chat_usage_data)
                    else:
                        chat_usage = 0

                    cat_list.append({
                        "name": cat_name,
                        "chat_usage": chat_usage,
                        "last_used": cat_data.get("last_used", 0),
                        "total_questions": cat_data.get("total_questions", 0)
                    })

                # Добавляем веса категорий
                try:
                    import sys
                    sys.path.insert(0, str(BASE_DIR))
                    from app_config import AppConfig
                    from state import BotState
                    from data_manager import DataManager
                    from modules.category_manager import CategoryManager

                    app_config = AppConfig()
                    bot_state = BotState(app_config)
                    data_manager = DataManager(app_config)
                    category_manager = CategoryManager(bot_state, app_config, data_manager)

                    # Получаем веса категорий
                    weights_info = category_manager.get_category_weights_for_chat(chat_id)

                    # Создаем словарь для быстрого поиска весов
                    weights_dict = {w["name"]: w for w in weights_info}

                    # Обогащаем cat_list весами
                    for cat in cat_list:
                        cat_name = cat["name"]
                        if cat_name in weights_dict:
                            weight_data = weights_dict[cat_name]
                            cat["weight"] = round(weight_data.get("weight", 0), 2)
                            cat["excluded"] = weight_data.get("excluded", False)
                            cat["days_since_use"] = round(weight_data.get("days_since_use", 0), 1)
                        else:
                            cat["weight"] = 0
                            cat["excluded"] = False
                            cat["days_since_use"] = 0

                except Exception as e:
                    logger.warning(f"Не удалось загрузить веса категорий для чата {chat_id}: {e}")
                    # Продолжаем без весов

                cat_list.sort(key=lambda x: x["chat_usage"], reverse=True)
                result["categories_stats"] = cat_list

        return result
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ГЛОБАЛЬНАЯ СТАТИСТИКА ПО КАТЕГОРИЯМ ==================

@app.get("/api/analytics/categories/usage")
async def get_categories_usage():
    """Получить статистику использования категорий по всем чатам"""
    try:
        categories_usage = {}
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_id = chat_dir.name
            categories_stats_file = chat_dir / "categories_stats.json"
            
            if categories_stats_file.exists():
                with open(categories_stats_file, 'r', encoding='utf-8') as f:
                    cat_stats = json.load(f)
                    
                    for cat_name, cat_data in cat_stats.items():
                        if cat_name not in categories_usage:
                            # Поддержка обоих форматов: читаем global_usage (новый) или total_usage (старый)
                            initial_usage = cat_data.get("global_usage", cat_data.get("total_usage", 0))

                            categories_usage[cat_name] = {
                                "name": cat_name,
                                "total_usage": initial_usage,
                                "total_questions": cat_data.get("total_questions", 0),
                                "chats_used": [],
                                "last_used_global": 0
                            }

                        # Поддержка обоих форматов chat_usage: словарь (новый) или число (старый)
                        chat_usage_data = cat_data.get("chat_usage", 0)
                        if isinstance(chat_usage_data, dict):
                            # Новый формат: словарь {"chat_id": count}
                            usage = chat_usage_data.get(chat_id, 0)
                        elif isinstance(chat_usage_data, (int, float)):
                            # Старый формат: просто число
                            usage = int(chat_usage_data)
                        else:
                            usage = 0

                        categories_usage[cat_name]["chats_used"].append({
                            "chat_id": chat_id,
                            "usage": usage,
                            "last_used": cat_data.get("last_used", 0)
                        })

                        last_used = cat_data.get("last_used", 0)
                        if last_used > categories_usage[cat_name]["last_used_global"]:
                            categories_usage[cat_name]["last_used_global"] = last_used
        
        # Преобразуем в список
        result = list(categories_usage.values())
        result.sort(key=lambda x: x["total_usage"], reverse=True)
        
        for cat in result:
            cat["chats_count"] = len(cat["chats_used"])
        
        return {
            "categories": result,
            "total": len(result)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/export/statistics")
async def export_statistics():
    """Экспортировать полную статистику в JSON"""
    try:
        # Собираем всю статистику
        export_data = {
            "exported_at": datetime.now().isoformat(),
            "categories": [],
            "chats": [],
            "users": []
        }
        
        # Категории
        for cat_name in get_all_categories():
            questions = load_category_questions(cat_name)
            export_data["categories"].append({
                "name": cat_name,
                "questions_count": len(questions)
            })
        
        # Чаты и пользователи
        all_users = {}
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            chat_data = {"chat_id": chat_dir.name}
            
            stats_file = chat_dir / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                    chat_data["stats"] = stats
                    
                    for user_id, user_data in stats.get("user_activity", {}).items():
                        if user_id not in all_users:
                            all_users[user_id] = {
                                "user_id": user_id,
                                "name": user_data.get("name"),
                                "total_score": 0,
                                "total_answered": 0
                            }
                        all_users[user_id]["total_score"] += user_data.get("score", 0)
                        all_users[user_id]["total_answered"] += user_data.get("answered_count", 0)
            
            export_data["chats"].append(chat_data)
        
        export_data["users"] = list(all_users.values())
        
        json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
        return StreamingResponse(
            io.BytesIO(json_str.encode('utf-8')),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=statistics_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"}
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ==================

BLACKLIST_FILE = DATA_DIR / "system" / "blacklist.json"

def load_blacklist() -> Dict:
    """Загрузить черный список"""
    if BLACKLIST_FILE.exists():
        with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"users": {}, "chats": {}}

def save_blacklist(data: Dict):
    """Сохранить черный список"""
    BLACKLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.post("/api/users/{user_id}/reset-stats")
async def reset_user_stats(user_id: str, chat_id: Optional[str] = None):
    """Сбросить статистику пользователя (во всех чатах или в конкретном)"""
    try:
        reset_count = 0
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            if chat_id and chat_dir.name != chat_id:
                continue
            
            # Сбрасываем в stats.json
            stats_file = chat_dir / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                
                if user_id in stats.get("user_activity", {}):
                    user_data = stats["user_activity"][user_id]
                    old_score = user_data.get("score", 0)
                    old_answered = user_data.get("answered_count", 0)
                    
                    # Сбрасываем статистику пользователя
                    stats["user_activity"][user_id] = {
                        "name": user_data.get("name", f"User {user_id}"),
                        "score": 0,
                        "answered_count": 0,
                        "first_answer": None,
                        "last_answer": None,
                        "consecutive_correct": 0,
                        "max_consecutive_correct": 0,
                        "streak_achievements_count": 0
                    }
                    
                    # Обновляем общую статистику чата
                    stats["total_score"] = stats.get("total_score", 0) - old_score
                    stats["total_answered"] = stats.get("total_answered", 0) - old_answered
                    
                    with open(stats_file, 'w', encoding='utf-8') as f:
                        json.dump(stats, f, ensure_ascii=False, indent=2)
                    
                    reset_count += 1
            
            # Сбрасываем в users.json
            users_file = chat_dir / "users.json"
            if users_file.exists():
                with open(users_file, 'r', encoding='utf-8') as f:
                    users = json.load(f)
                
                if user_id in users:
                    users[user_id] = {
                        "name": users[user_id].get("name", f"User {user_id}"),
                        "score": 0,
                        "answered_polls": []
                    }
                    
                    with open(users_file, 'w', encoding='utf-8') as f:
                        json.dump(users, f, ensure_ascii=False, indent=2)
        
        return {
            "success": True,
            "message": f"Статистика сброшена в {reset_count} чат(ах)",
            "reset_count": reset_count
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str, chat_id: Optional[str] = None):
    """Удалить пользователя (из всех чатов или из конкретного)"""
    try:
        delete_count = 0
        
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            
            if chat_id and chat_dir.name != chat_id:
                continue
            
            # Удаляем из stats.json
            stats_file = chat_dir / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                
                if user_id in stats.get("user_activity", {}):
                    user_data = stats["user_activity"].pop(user_id)
                    
                    # Обновляем общую статистику
                    stats["total_users"] = max(0, stats.get("total_users", 1) - 1)
                    stats["total_score"] = stats.get("total_score", 0) - user_data.get("score", 0)
                    stats["total_answered"] = stats.get("total_answered", 0) - user_data.get("answered_count", 0)
                    
                    with open(stats_file, 'w', encoding='utf-8') as f:
                        json.dump(stats, f, ensure_ascii=False, indent=2)
                    
                    delete_count += 1
            
            # Удаляем из users.json
            users_file = chat_dir / "users.json"
            if users_file.exists():
                with open(users_file, 'r', encoding='utf-8') as f:
                    users = json.load(f)
                
                if user_id in users:
                    del users[user_id]
                    
                    with open(users_file, 'w', encoding='utf-8') as f:
                        json.dump(users, f, ensure_ascii=False, indent=2)
        
        return {
            "success": True,
            "message": f"Пользователь удален из {delete_count} чат(ов)",
            "delete_count": delete_count
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/users/{user_id}/ban")
async def ban_user(user_id: str, reason: Optional[str] = None):
    """Добавить пользователя в черный список"""
    try:
        blacklist = load_blacklist()
        
        # Получаем имя пользователя
        user_name = f"User {user_id}"
        for chat_dir in CHATS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            stats_file = chat_dir / "stats.json"
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                if user_id in stats.get("user_activity", {}):
                    user_name = stats["user_activity"][user_id].get("name", user_name)
                    break
        
        blacklist["users"][user_id] = {
            "name": user_name,
            "reason": reason or "Заблокирован администратором",
            "banned_at": datetime.now().isoformat(),
            "banned_by": "admin"
        }
        
        save_blacklist(blacklist)
        
        return {
            "success": True,
            "message": f"Пользователь {user_name} добавлен в черный список"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/users/{user_id}/unban")
async def unban_user(user_id: str):
    """Удалить пользователя из черного списка"""
    try:
        blacklist = load_blacklist()
        
        if user_id in blacklist.get("users", {}):
            del blacklist["users"][user_id]
            save_blacklist(blacklist)
            return {"success": True, "message": "Пользователь разблокирован"}
        
        return {"success": False, "message": "Пользователь не найден в черном списке"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.put("/api/users/{user_id}/score")
async def update_user_score(user_id: str, chat_id: str, new_score: float):
    """Изменить баллы пользователя в конкретном чате"""
    try:
        chat_dir = CHATS_DIR / chat_id
        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        stats_file = chat_dir / "stats.json"
        if not stats_file.exists():
            raise HTTPException(status_code=404, detail="Статистика чата не найдена")
        
        with open(stats_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        
        if user_id not in stats.get("user_activity", {}):
            raise HTTPException(status_code=404, detail="Пользователь не найден в чате")
        
        old_score = stats["user_activity"][user_id].get("score", 0)
        stats["user_activity"][user_id]["score"] = new_score
        
        # Обновляем общую статистику
        stats["total_score"] = stats.get("total_score", 0) - old_score + new_score
        
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        # Обновляем также в users.json
        users_file = chat_dir / "users.json"
        if users_file.exists():
            with open(users_file, 'r', encoding='utf-8') as f:
                users = json.load(f)
            if user_id in users:
                users[user_id]["score"] = new_score
                with open(users_file, 'w', encoding='utf-8') as f:
                    json.dump(users, f, ensure_ascii=False, indent=2)
        
        return {
            "success": True,
            "message": f"Баллы изменены: {old_score} → {new_score}",
            "old_score": old_score,
            "new_score": new_score
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/api/blacklist")
async def get_blacklist():
    """Получить черный список"""
    try:
        blacklist = load_blacklist()
        return blacklist
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== УПРАВЛЕНИЕ ЧАТАМИ ==================

@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    """Удалить чат и все его данные"""
    try:
        chat_dir = CHATS_DIR / chat_id
        
        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        # Удаляем папку чата
        shutil.rmtree(chat_dir)
        
        # Удаляем из индекса чатов
        chats_index_file = GLOBAL_DIR / "chats_index.json"
        if chats_index_file.exists():
            with open(chats_index_file, 'r', encoding='utf-8') as f:
                chats_index = json.load(f)
            
            if chat_id in chats_index:
                del chats_index[chat_id]
                with open(chats_index_file, 'w', encoding='utf-8') as f:
                    json.dump(chats_index, f, ensure_ascii=False, indent=2)
        
        return {"success": True, "message": f"Чат {chat_id} и все данные удалены"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/chats/{chat_id}/reset-stats")
async def reset_chat_stats(chat_id: str):
    """Сбросить всю статистику чата (сохранить настройки)"""
    try:
        chat_dir = CHATS_DIR / chat_id
        
        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        # Сбрасываем stats.json
        stats_file = chat_dir / "stats.json"
        if stats_file.exists():
            with open(stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            
            # Сохраняем chat_id, сбрасываем остальное
            stats = {
                "chat_id": chat_id,
                "total_users": 0,
                "total_score": 0,
                "total_answered": 0,
                "user_activity": {}
            }
            
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
        
        # Сбрасываем users.json
        users_file = chat_dir / "users.json"
        if users_file.exists():
            with open(users_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        
        # Сбрасываем categories_stats.json
        cat_stats_file = chat_dir / "categories_stats.json"
        if cat_stats_file.exists():
            with open(cat_stats_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        
        return {"success": True, "message": "Статистика чата сброшена"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.put("/api/chats/{chat_id}/title")
async def update_chat_title(chat_id: str, title: str):
    """Обновить название чата"""
    try:
        chat_dir = CHATS_DIR / chat_id
        
        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        settings_file = chat_dir / "settings.json"
        
        if settings_file.exists():
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        else:
            settings = {}
        
        settings["title"] = title
        
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        
        # Обновляем индекс чатов
        chats_index_file = GLOBAL_DIR / "chats_index.json"
        if chats_index_file.exists():
            with open(chats_index_file, 'r', encoding='utf-8') as f:
                chats_index = json.load(f)
            
            if chat_id in chats_index:
                chats_index[chat_id]["title"] = title
                with open(chats_index_file, 'w', encoding='utf-8') as f:
                    json.dump(chats_index, f, ensure_ascii=False, indent=2)
        
        return {"success": True, "message": "Название чата обновлено", "title": title}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.put("/api/chats/{chat_id}/categories")
async def update_chat_categories(chat_id: str, enabled: Optional[List[str]] = None, disabled: Optional[List[str]] = None):
    """Обновить категории чата"""
    try:
        chat_dir = CHATS_DIR / chat_id
        
        if not chat_dir.exists():
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        settings_file = chat_dir / "settings.json"
        
        if settings_file.exists():
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        else:
            settings = {}
        
        if enabled is not None:
            settings["enabled_categories"] = enabled
        
        if disabled is not None:
            settings["disabled_categories"] = disabled
        
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        
        return {
            "success": True,
            "message": "Категории обновлены",
            "enabled_categories": settings.get("enabled_categories"),
            "disabled_categories": settings.get("disabled_categories", [])
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/chats/{chat_id}/ban")
async def ban_chat(chat_id: str, reason: Optional[str] = None):
    """Добавить чат в черный список"""
    try:
        blacklist = load_blacklist()
        
        blacklist["chats"][chat_id] = {
            "reason": reason or "Заблокирован администратором",
            "banned_at": datetime.now().isoformat(),
            "banned_by": "admin"
        }
        
        save_blacklist(blacklist)
        
        return {"success": True, "message": f"Чат {chat_id} добавлен в черный список"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.post("/api/chats/{chat_id}/unban")
async def unban_chat(chat_id: str):
    """Удалить чат из черного списка"""
    try:
        blacklist = load_blacklist()
        
        if chat_id in blacklist.get("chats", {}):
            del blacklist["chats"][chat_id]
            save_blacklist(blacklist)
            return {"success": True, "message": "Чат разблокирован"}
        
        return {"success": False, "message": "Чат не найден в черном списке"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

# ================== ЛОГИ ==================

@app.get("/api/logs")
async def get_logs(
    level: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 1000
):
    """
    Получить логи с фильтрацией
    
    Args:
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL) или несколько через запятую (например: "INFO,WARNING,ERROR")
        since: Начало временного диапазона (ISO формат: YYYY-MM-DD или YYYY-MM-DDTHH:MM:SS)
        until: Конец временного диапазона (ISO формат: YYYY-MM-DD или YYYY-MM-DDTHH:MM:SS)
        limit: Максимальное количество записей (по умолчанию 1000)
    """
    try:
        import re
        
        # Валидация уровня логирования - поддерживаем несколько уровней через запятую
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        levels_to_filter = None
        if level:
            # Разделяем по запятой и обрабатываем каждый уровень
            level_list = [l.strip().upper() for l in level.split(',') if l.strip()]
            invalid_levels = [l for l in level_list if l not in valid_levels]
            if invalid_levels:
                raise HTTPException(status_code=400, detail=f"Неподдерживаемые уровни логирования: {', '.join(invalid_levels)}. Доступные: {', '.join(valid_levels)}")
            if level_list:
                levels_to_filter = set(level_list)
        
        # Парсим временные диапазоны
        since_dt = None
        until_dt = None
        
        if since:
            try:
                if len(since) == 10:  # YYYY-MM-DD
                    since_dt = datetime.fromisoformat(since + "T00:00:00")
                else:
                    since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Неверный формат даты 'since': {since}. Используйте YYYY-MM-DD или YYYY-MM-DDTHH:MM:SS")
        
        if until:
            try:
                if len(until) == 10:  # YYYY-MM-DD
                    until_dt = datetime.fromisoformat(until + "T23:59:59")
                else:
                    until_dt = datetime.fromisoformat(until.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Неверный формат даты 'until': {until}. Используйте YYYY-MM-DD или YYYY-MM-DDTHH:MM:SS")
        
        # Если не указано время, берем за сегодня
        if not since_dt and not until_dt:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            since_dt = today
            until_dt = datetime.now()
        
        # Если указано только since, until = сейчас
        if since_dt and not until_dt:
            until_dt = datetime.now()
        
        # Если указано только until, since = начало дня
        if until_dt and not since_dt:
            since_dt = until_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Проверяем существование директории логов
        if not LOGS_DIR.exists():
            logger.warning(f"Директория логов не найдена: {LOGS_DIR}")
            return {
                "logs": [],
                "total": 0,
                "filters": {
                    "level": level,
                    "since": since_dt.isoformat() if since_dt else None,
                    "until": until_dt.isoformat() if until_dt else None
                },
                "error": f"Директория логов не найдена: {LOGS_DIR}"
            }
        
        # Получаем все лог-файлы
        try:
            log_files = sorted(LOGS_DIR.glob("bot_*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
        except Exception as e:
            logger.error(f"Ошибка при получении списка лог-файлов: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка доступа к директории логов: {str(e)}")
        
        all_logs = []
        # levels_to_filter уже установлен выше, если level был передан
        
        # Паттерн для парсинга строк логов
        # Формат: 2026-01-02 08:19:32,096 - modules.quiz_engine - ERROR - ...
        log_line_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?)\s+-\s+(\S+)\s+-\s+(\w+)\s+-\s+(.*)$')
        
        for log_file in log_files:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.rstrip('\n\r')
                        if not line.strip():
                            continue
                        
                        # Парсим строку лога
                        match = log_line_pattern.match(line)
                        if match:
                            timestamp_str, logger_name, log_level, message = match.groups()
                            
                            # Парсим timestamp
                            try:
                                # Убираем микросекунды если есть
                                timestamp_str_clean = timestamp_str.replace(',', '.')
                                if '.' in timestamp_str_clean:
                                    log_dt = datetime.strptime(timestamp_str_clean, '%Y-%m-%d %H:%M:%S.%f')
                                else:
                                    log_dt = datetime.strptime(timestamp_str_clean, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                continue
                            
                            # Фильтруем по уровню (поддерживаем несколько уровней)
                            if levels_to_filter and log_level.upper() not in levels_to_filter:
                                continue
                            
                            # Фильтруем по времени
                            if since_dt and log_dt < since_dt:
                                continue
                            if until_dt and log_dt > until_dt:
                                continue
                            
                            all_logs.append({
                                "timestamp": log_dt.isoformat(),
                                "level": log_level.upper(),
                                "logger": logger_name,
                                "message": message,
                                "file": log_file.name,
                                "line": line_num
                            })
                        else:
                            # Если строка не соответствует паттерну, но содержит ERROR/CRITICAL, всё равно включаем
                            if not levels_to_filter or any(lvl in ['ERROR', 'CRITICAL'] for lvl in levels_to_filter):
                                if levels_to_filter and any(lvl in line.upper() for lvl in levels_to_filter):
                                    # Пытаемся определить уровень из строки
                                    detected_level = None
                                    for lvl in levels_to_filter:
                                        if lvl in line.upper():
                                            detected_level = lvl
                                            break
                                    all_logs.append({
                                        "timestamp": None,
                                        "level": detected_level or (list(levels_to_filter)[0] if levels_to_filter else 'UNKNOWN'),
                                        "logger": None,
                                        "message": line,
                                        "file": log_file.name,
                                        "line": line_num
                                    })
                
                # Если набрали достаточно логов, прерываем
                if len(all_logs) >= limit * 2:  # Берем больше для сортировки
                    break
            except Exception as e:
                logger.warning(f"Ошибка чтения лог-файла {log_file.name}: {e}")
                continue
        
        # Сортируем по времени (новые первыми)
        all_logs.sort(key=lambda x: x["timestamp"] if x["timestamp"] else "", reverse=True)
        
        # Ограничиваем количество
        all_logs = all_logs[:limit]
        
        return {
            "logs": all_logs,
            "total": len(all_logs),
            "filters": {
                "level": level,
                "levels": list(levels_to_filter) if levels_to_filter else None,
                "since": since_dt.isoformat() if since_dt else None,
                "until": until_dt.isoformat() if until_dt else None
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения логов: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка получения логов: {str(e)}")

# ================== ОТПРАВКА СООБЩЕНИЙ АДМИНА ==================

class AdminMessageRequest(BaseModel):
    message: str = Field(..., description="Текст сообщения для отправки")
    chat_ids: Optional[List[str]] = Field(None, description="Список ID чатов. Если пусто, отправляется во все чаты")
    send_to_all: bool = Field(False, description="Отправить во все чаты")

@app.post("/api/admin/send-message")
async def send_admin_message(request: AdminMessageRequest):
    """Отправить сообщение от админа в чаты"""
    try:
        from telegram import Bot
        from telegram.constants import ParseMode
        from modules.telegram_utils import safe_send_message
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from utils import escape_markdown_v2
        
        # Получаем токен бота
        bot_token = os.getenv("BOT_TOKEN")
        
        # Если токен не найден, пытаемся перезагрузить .env файл
        if not bot_token:
            try:
                from dotenv import load_dotenv
                BASE_DIR_FOR_ENV = Path(__file__).parent.parent
                env_path = BASE_DIR_FOR_ENV / '.env'
                if not env_path.exists():
                    env_path = Path('.env')
                if env_path.exists():
                    load_dotenv(dotenv_path=env_path, override=True)
                    bot_token = os.getenv("BOT_TOKEN")
                    if bot_token:
                        logger.info(f"BOT_TOKEN успешно загружен из {env_path.absolute()}")
            except Exception as e:
                logger.warning(f"Не удалось перезагрузить .env файл: {e}")
        
        if not bot_token:
            raise HTTPException(status_code=500, detail="Токен бота не найден в переменных окружения. Убедитесь, что файл .env существует и содержит BOT_TOKEN")
        
        bot = Bot(token=bot_token)
        
        # Определяем список чатов для отправки
        target_chat_ids = []
        
        if request.send_to_all:
            # Получаем все чаты из директории
            for chat_dir in CHATS_DIR.iterdir():
                if chat_dir.is_dir():
                    chat_id = chat_dir.name
                    try:
                        # Проверяем, что это валидный числовой ID
                        int(chat_id.lstrip('-'))
                        target_chat_ids.append(chat_id)
                    except ValueError:
                        continue
        elif request.chat_ids:
            target_chat_ids = request.chat_ids
        else:
            raise HTTPException(status_code=400, detail="Укажите chat_ids или установите send_to_all=true")
        
        if not target_chat_ids:
            raise HTTPException(status_code=400, detail="Не найдено чатов для отправки")
        
        # Экранируем сообщение для Markdown V2
        try:
            escaped_message = escape_markdown_v2(request.message)
        except:
            escaped_message = request.message  # Если ошибка экранирования, отправляем как есть
        
        results = {
            "total": len(target_chat_ids),
            "success": [],
            "failed": []
        }
        
        # Отправляем сообщения
        for chat_id in target_chat_ids:
            try:
                await safe_send_message(
                    bot=bot,
                    chat_id=int(chat_id),
                    text=escaped_message,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                results["success"].append(chat_id)
            except Exception as e:
                error_msg = str(e)
                results["failed"].append({
                    "chat_id": chat_id,
                    "error": error_msg
                })
                logger.warning(f"Не удалось отправить сообщение в чат {chat_id}: {error_msg}")
        
        return {
            "success": True,
            "message": f"Отправлено в {len(results['success'])} из {len(target_chat_ids)} чатов",
            "results": results
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка отправки сообщений: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка отправки сообщений: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ==================== МЕТРИКИ БОТА ====================

@app.get("/api/bot/metrics")
async def get_bot_metrics():
    """
    Получить метрики работы бота (таймауты, retry, rate limiting).
    Endpoint для мониторинга здоровья бота.
    """
    try:
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "rate_limiter": None,
            "retry_stats": None,
            "timeout_stats": None,
            "bot_status": "unknown"
        }
        
        # Пробуем получить метрики из работающего процесса бота
        # Для этого нужно читать данные из общего файла или использовать IPC
        
        # Временное решение: читаем из лог-файла последние ошибки таймаута
        try:
            if LOGS_DIR.exists():
                # Находим последний лог-файл
                log_files = sorted(LOGS_DIR.glob("bot_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                if log_files:
                    latest_log = log_files[0]
                    
                    # Читаем последние 1000 строк
                    import subprocess
                    result = subprocess.run(
                        ['tail', '-1000', str(latest_log)],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        log_content = result.stdout
                        
                        # Подсчитываем ошибки таймаута
                        timeout_errors = log_content.count("TimedOut")
                        timeout_warnings = log_content.count("Таймаут/сетевая ошибка")
                        retry_attempts = log_content.count("повтор через")
                        
                        metrics["timeout_stats"] = {
                            "errors": timeout_errors,
                            "warnings": timeout_warnings,
                            "retry_attempts": retry_attempts,
                            "log_file": latest_log.name
                        }
                        
                        # Определяем статус бота
                        if timeout_errors == 0:
                            metrics["bot_status"] = "healthy"
                        elif timeout_errors < 10:
                            metrics["bot_status"] = "degraded"
                        else:
                            metrics["bot_status"] = "critical"
                    
        except Exception as e:
            logger.error(f"Ошибка при анализе логов: {e}")
            metrics["error"] = str(e)
        
        # Проверяем, запущен ли бот
        try:
            pid_file = BASE_DIR / "bot.pid"
            if pid_file.exists():
                with open(pid_file, 'r') as f:
                    bot_pid = f.read().strip()
                
                # Проверяем, жив ли процесс
                try:
                    import psutil
                    process = psutil.Process(int(bot_pid))
                    if process.is_running():
                        metrics["bot_running"] = True
                        metrics["bot_pid"] = bot_pid
                        metrics["bot_uptime_seconds"] = int((datetime.now().timestamp() - process.create_time()))
                    else:
                        metrics["bot_running"] = False
                except:
                    # Проверка через ps (fallback)
                    result = subprocess.run(['ps', '-p', bot_pid], capture_output=True)
                    metrics["bot_running"] = result.returncode == 0
                    metrics["bot_pid"] = bot_pid
            else:
                metrics["bot_running"] = False
                metrics["bot_pid"] = None
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса бота: {e}")
            metrics["bot_running"] = None
        
        return metrics
        
    except Exception as e:
        logger.error(f"Ошибка при получении метрик: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bot/health")
async def bot_health_check():
    """
    Быстрая проверка здоровья бота (для мониторинга).
    Возвращает простой статус: healthy, degraded, critical, offline.
    """
    try:
        # Проверяем, запущен ли бот
        pid_file = BASE_DIR / "bot.pid"
        if not pid_file.exists():
            return {
                "status": "offline",
                "message": "Bot PID file not found"
            }
        
        with open(pid_file, 'r') as f:
            bot_pid = f.read().strip()
        
        # Проверяем процесс
        try:
            import psutil
            process = psutil.Process(int(bot_pid))
            if not process.is_running():
                return {
                    "status": "offline",
                    "message": "Bot process not running"
                }
        except:
            result = subprocess.run(['ps', '-p', bot_pid], capture_output=True)
            if result.returncode != 0:
                return {
                    "status": "offline",
                    "message": "Bot process not running"
                }
        
        # Проверяем последние ошибки в логах
        if LOGS_DIR.exists():
            log_files = sorted(LOGS_DIR.glob("bot_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if log_files:
                latest_log = log_files[0]
                result = subprocess.run(
                    ['tail', '-100', str(latest_log)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    recent_errors = result.stdout.count("ERROR")
                    timeout_errors = result.stdout.count("TimedOut")
                    
                    if timeout_errors > 5:
                        return {
                            "status": "critical",
                            "message": f"High timeout error rate: {timeout_errors} in last 100 log lines",
                            "timeout_errors": timeout_errors
                        }
                    elif recent_errors > 10:
                        return {
                            "status": "degraded",
                            "message": f"Elevated error rate: {recent_errors} in last 100 log lines",
                            "errors": recent_errors
                        }
        
        return {
            "status": "healthy",
            "message": "Bot is running normally",
            "pid": bot_pid
        }
        
    except Exception as e:
        logger.error(f"Ошибка при проверке здоровья: {e}", exc_info=True)
        return {
            "status": "unknown",
            "message": f"Error checking health: {str(e)}"
        }
