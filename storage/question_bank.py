"""Static question files: validated edits, optimistic versions and recoverable history."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from .admin_actions import operation_fence
from .models import QuestionCategory, QuestionCategoryRevision


class BankConflict(ValueError):
    pass


class BankQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    correct: str
    explanation: str = Field(default='', max_length=200)

    @field_validator('options')
    @classmethod
    def valid_options(cls, value):
        value = [v.strip() for v in value]
        if any(not v or len(v) > 100 for v in value) or len(set(value)) != len(value):
            raise ValueError('Варианты должны быть уникальными, от 1 до 100 символов')
        return value

    @model_validator(mode='after')
    def valid_correct(self):
        if self.correct not in self.options:
            raise ValueError('Правильный ответ должен совпадать с одним из вариантов')
        return self


def normalized(value):
    if not isinstance(value, dict):
        raise ValueError('Вопрос должен быть объектом')
    options = value.get('options', value.get('answers', []))
    correct = value.get('correct', value.get('correct_answer', value.get('correct_option_text', '')))
    if isinstance(correct, int) and not isinstance(correct, bool) and 0 <= correct < len(options):
        correct = options[correct]
    return BankQuestion.model_validate({
        'question': value.get('question', ''), 'options': options, 'correct': correct,
        'explanation': value.get('explanation') or '',
    }).model_dump()


_lock = threading.RLock()


def validate_category_name(name):
    if (not isinstance(name, str) or not name or len(name) > 100 or name != name.strip()
            or name.startswith('.') or name.endswith('.') or '..' in name
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name)):
        raise ValueError('Недопустимое имя категории')
    return name


class QuestionBank:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, name):
        validate_category_name(name)
        path = (self.root / f'{name}.json').resolve()
        if not path.is_relative_to(self.root) or path.parent != self.root:
            raise ValueError('Категория вне каталога вопросов')
        return path

    @contextmanager
    def locked(self):
        # OS lock releases on process exit; the RLock also serializes threads.
        self.root.mkdir(parents=True, exist_ok=True)
        with _lock, (self.root / '.admin.lock').open('a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b'0'); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self, name):
        path = self.path(name)
        if not path.is_file():
            raise LookupError('Категория не найдена')
        raw = path.read_bytes()
        if len(raw) > 10_000_000:
            raise ValueError('Категория превышает 10 МБ')
        values = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(values, list):
            raise ValueError('Категория должна содержать массив вопросов')
        return {'name': name, 'version': hashlib.sha256(raw).hexdigest(), 'questions': values, 'count': len(values)}

    def raw(self, name):
        path = self.path(name)
        if not path.is_file():
            raise LookupError('Категория не найдена')
        if path.stat().st_size > 10_000_000:
            raise ValueError('Категория превышает 10 МБ')
        return path.read_bytes()

    def repair(self, name, expected_version, questions):
        if not isinstance(questions, list) or len(questions) > 5000:
            raise ValueError('Нужен массив не более 5000 вопросов')
        with self.locked():
            raw = self.raw(name)
            if hashlib.sha256(raw).hexdigest() != expected_version:
                raise BankConflict('Файл изменился. Обновите предварительный просмотр.')
            for question in questions:
                normalized(question)
            self._commit(name, questions)
            return self.read(name)

    def categories(self):
        result = []
        for path in sorted(self.root.glob('*.json')):
            if path.name.startswith('.'):
                continue
            try:
                data = self.read(path.stem)
                invalid = sum(1 for v in data['questions'] if not self.is_valid(v))
                result.append({k: data[k] for k in ('name', 'version', 'count')} | {'invalid': invalid})
            except (ValueError, LookupError, OSError):
                try:
                    version = hashlib.sha256(self.raw(path.stem)).hexdigest()
                except (ValueError, LookupError, OSError):
                    version = None
                result.append({'name': path.stem, 'count': 0, 'invalid': 1, 'error': 'Не удалось прочитать JSON', 'version': version})
        return result

    @staticmethod
    def is_valid(value):
        try:
            normalized(value)
            return True
        except (ValueError, TypeError):
            return False

    def for_quiz(self):
        result = {}
        for item in self.categories():
            if item.get('error'):
                continue
            values = self.read(item['name'])['questions']
            result[item['name']] = [dict(v, **normalized(v), original_category=item['name'],
                                        correct_option_text=normalized(v)['correct'])
                                    for v in values if self.is_valid(v)]
        return result

    def _commit(self, name, values):
        path = self.path(name)
        if path.exists():
            history = (self.root / '.history' / name).resolve()
            if not history.is_relative_to(self.root):
                raise ValueError('История вне каталога вопросов')
            history.mkdir(parents=True, exist_ok=True)
            (history / f'{uuid.uuid4().hex}.json').write_bytes(path.read_bytes())
        if values is None:
            path.unlink()  # Previous bytes are retained in .history first.
            return {'deleted': True, 'recoverable': True}
        raw = (json.dumps(values, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        temporary = self.root / f'.{uuid.uuid4().hex}.tmp'
        try:
            with temporary.open('xb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.read(name)

    def create(self, name):
        with self.locked():
            if self.path(name).exists():
                raise BankConflict('Категория уже существует')
            return self._commit(name, [])

    def export_all(self):
        with self.locked():
            return {'format': 'morning-quiz-bank-v1', 'categories': {
                item['name']: self.read(item['name'])['questions'] for item in self.categories()}}

    def import_all(self, categories, expected_versions):
        """Validate every category first; replace selected categories, never append twice.

        Files have individually atomic commits, not a fictitious cross-file transaction.
        On I/O failure return exactly which files committed; retain their histories.
        """
        if not categories or len(categories) > 200 or set(categories) != set(expected_versions):
            raise ValueError('Укажите от 1 до 200 категорий и версию каждой из них')
        with self.locked():
            prepared = {}
            for name, values in categories.items():
                path = self.path(name)
                if not isinstance(values, list) or len(values) > 5000:
                    raise ValueError('Каждая категория должна содержать до 5000 вопросов')
                actual = self.read(name)['version'] if path.exists() else None
                if expected_versions[name] != actual:
                    raise BankConflict(f'Категория «{name}» уже изменилась. Повторите предварительный просмотр.')
                prepared[name] = [dict(value, **normalized(value)) for value in values]
            result = {'completed': [], 'failed': None, 'remaining': [], 'recoverable': True}
            names = sorted(prepared)
            for index, name in enumerate(names):
                try:
                    self._commit(name, prepared[name])
                except OSError:
                    result.update(failed=name, remaining=names[index + 1:])
                    return result
                result['completed'].append(name)
            return result

    def change(self, name, expected, *, index=None, question=None, remove=False, import_values=None):
        with self.locked():
            current = self.read(name)
            if current['version'] != expected:
                raise BankConflict('Категория уже изменена. Загрузите её заново')
            values = current['questions']
            if import_values is not None:
                if len(import_values) > 5000:
                    raise ValueError('Не более 5000 вопросов за импорт')
                # Import appends and preserves unknown legacy metadata.
                values.extend(dict(v, **normalized(v)) for v in import_values)
            elif index is not None:
                if not 0 <= index < len(values):
                    raise LookupError('Вопрос не найден')
                if remove:
                    values.pop(index)
                else:
                    original = values[index] if isinstance(values[index], dict) else {}
                    # Keep unrelated metadata but eliminate stale answer aliases.
                    values[index] = {k: v for k, v in original.items()
                                     if k not in {'answers', 'correct_answer', 'correct_option_text'}} | normalized(question)
            elif remove:
                return self._commit(name, None)
            else:
                values.append(normalized(question))
            return self._commit(name, values)


def question_content_hash(questions):
    raw = json.dumps(questions, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class PostgresQuestionBank:
    """Transactional question bank shared by the bot and admin API."""

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _view(row):
        return {
            'name': row.name,
            'version': row.content_hash,
            'revision': row.revision,
            'questions': list(row.questions or []),
            'count': len(row.questions or []),
        }

    async def read(self, name):
        validate_category_name(name)
        async with self.database.transaction() as session:
            row = await session.get(QuestionCategory, name)
            if row is None or row.archived:
                raise LookupError('Категория не найдена')
            return self._view(row)

    async def raw(self, name):
        result = await self.read(name)
        return (json.dumps(result['questions'], ensure_ascii=False, indent=2) + '\n').encode('utf-8')

    async def categories(self):
        async with self.database.transaction() as session:
            rows = (await session.scalars(select(QuestionCategory).where(
                QuestionCategory.archived.is_(False)
            ).order_by(QuestionCategory.name))).all()
            return [
                {
                    'name': row.name,
                    'version': row.content_hash,
                    'revision': row.revision,
                    'count': len(row.questions or []),
                    'invalid': sum(not QuestionBank.is_valid(item) for item in (row.questions or [])),
                }
                for row in rows
            ]

    async def for_quiz(self):
        async with self.database.transaction() as session:
            rows = (await session.scalars(select(QuestionCategory).where(
                QuestionCategory.archived.is_(False)
            ).order_by(QuestionCategory.name))).all()
            result = {}
            for row in rows:
                values = []
                for item in row.questions or []:
                    if not QuestionBank.is_valid(item):
                        continue
                    clean = normalized(item)
                    values.append(dict(item, **clean, original_category=row.name,
                                       correct_option_text=clean['correct']))
                if values:
                    result[row.name] = values
            return result

    @staticmethod
    def _history(session, row, action):
        session.add(QuestionCategoryRevision(
            category_name=row.name, revision=row.revision,
            content_hash=row.content_hash, questions=list(row.questions or []),
            metadata_json=dict(row.metadata_json or {}), action=action,
        ))

    @staticmethod
    def _replace(row, questions, *, archived=False):
        row.questions = questions
        row.revision += 1
        row.content_hash = question_content_hash(questions)
        row.archived = archived
        row.updated_at = func.now()

    async def create(self, name):
        validate_category_name(name)
        async with self.database.transaction() as session:
            await operation_fence(session)
            row = await session.get(QuestionCategory, name, with_for_update=True)
            if row is not None:
                raise BankConflict('Категория уже существует')
            row = QuestionCategory(
                name=name, revision=0, questions=[], metadata_json={},
                content_hash=question_content_hash([]), archived=False,
            )
            session.add(row)
            await session.flush()
            return self._view(row)

    async def repair(self, name, expected_version, questions):
        if not isinstance(questions, list) or len(questions) > 5000:
            raise ValueError('Нужен массив не более 5000 вопросов')
        for question in questions:
            normalized(question)
        return await self._change(name, expected_version, replacement=questions, action='repair')

    async def _change(self, name, expected, *, replacement, action, archived=False):
        validate_category_name(name)
        async with self.database.transaction() as session:
            await operation_fence(session)
            row = await session.get(QuestionCategory, name, with_for_update=True)
            if row is None or row.archived:
                raise LookupError('Категория не найдена')
            if row.content_hash != expected:
                raise BankConflict('Категория уже изменена. Загрузите её заново')
            self._history(session, row, action)
            self._replace(row, replacement, archived=archived)
            await session.flush()
            if archived:
                return {'deleted': True, 'recoverable': True, 'revision': row.revision}
            return self._view(row)

    async def change(
        self, name, expected, *, index=None, question=None, remove=False,
        import_values=None,
    ):
        current = await self.read(name)
        values = current['questions']
        if import_values is not None:
            if len(import_values) > 5000:
                raise ValueError('Не более 5000 вопросов за импорт')
            prepared = [dict(value, **normalized(value)) for value in import_values]
            values.extend(prepared)
            action = 'import'
        elif index is not None:
            if not 0 <= index < len(values):
                raise LookupError('Вопрос не найден')
            if remove:
                values.pop(index)
                action = 'delete_question'
            else:
                original = values[index] if isinstance(values[index], dict) else {}
                values[index] = {
                    key: value for key, value in original.items()
                    if key not in {'answers', 'correct_answer', 'correct_option_text'}
                } | normalized(question)
                action = 'edit_question'
        elif remove:
            return await self._change(
                name, expected, replacement=values, action='archive_category', archived=True
            )
        else:
            values.append(normalized(question))
            action = 'add_question'
        return await self._change(name, expected, replacement=values, action=action)

    async def export_all(self):
        async with self.database.transaction() as session:
            rows = (await session.scalars(select(QuestionCategory).where(
                QuestionCategory.archived.is_(False)
            ).order_by(QuestionCategory.name))).all()
            return {'format': 'morning-quiz-bank-v1',
                    'categories': {row.name: list(row.questions or []) for row in rows}}

    async def import_all(self, categories, expected_versions):
        if not categories or len(categories) > 200 or set(categories) != set(expected_versions):
            raise ValueError('Укажите от 1 до 200 категорий и версию каждой из них')
        prepared = {}
        for name, values in categories.items():
            validate_category_name(name)
            if not isinstance(values, list) or len(values) > 5000:
                raise ValueError('Каждая категория должна содержать до 5000 вопросов')
            prepared[name] = [dict(value, **normalized(value)) for value in values]
        async with self.database.transaction() as session:
            await operation_fence(session)
            existing = {
                row.name: row for row in (await session.scalars(
                    select(QuestionCategory).where(QuestionCategory.name.in_(sorted(prepared)))
                    .order_by(QuestionCategory.name).with_for_update()
                )).all()
            }
            for name in sorted(prepared):
                row = existing.get(name)
                actual = None if row is None or row.archived else row.content_hash
                if expected_versions[name] != actual:
                    raise BankConflict(
                        f'Категория «{name}» уже изменилась. Повторите предварительный просмотр.'
                    )
            for name, questions in sorted(prepared.items()):
                row = existing.get(name)
                if row is None:
                    session.add(QuestionCategory(
                        name=name, revision=0, content_hash=question_content_hash(questions),
                        questions=questions, metadata_json={}, archived=False,
                    ))
                else:
                    self._history(session, row, 'bulk_import')
                    self._replace(row, questions)
            return {'completed': sorted(prepared), 'failed': None,
                    'remaining': [], 'recoverable': True}

    async def seed_from_directory(self, root, *, metadata_path=None):
        root = Path(root).resolve()
        metadata = {}
        if metadata_path and Path(metadata_path).is_file():
            loaded = json.loads(Path(metadata_path).read_text(encoding='utf-8-sig'))
            metadata = loaded if isinstance(loaded, dict) else {}
        prepared = {}
        for path in sorted(root.glob('*.json')):
            values = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(values, list):
                raise ValueError(f'{path}: категория должна содержать массив')
            prepared[path.stem] = values
        async with self.database.transaction() as session:
            await operation_fence(session)
            if await session.scalar(select(func.count()).select_from(QuestionCategory)):
                return 0
            for name, questions in prepared.items():
                validate_category_name(name)
                session.add(QuestionCategory(
                    name=name, revision=0, content_hash=question_content_hash(questions),
                    questions=questions,
                    metadata_json=metadata.get(name) if isinstance(metadata.get(name), dict) else {},
                    archived=False,
                ))
            return len(prepared)
