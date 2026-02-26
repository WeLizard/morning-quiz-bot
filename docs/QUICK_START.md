# 🚀 Быстрый старт - Morning Quiz Bot

## Для Ubuntu сервера (рекомендуется)

### 1. Автоматическое развертывание
```bash
# Скачайте и запустите скрипт развертывания
wget https://raw.githubusercontent.com/WeLizard/morning-quiz-bot/main/deploy.sh
chmod +x deploy.sh
sudo ./deploy.sh
```

### 2. Настройка токена
```bash
# Отредактируйте файл .env
sudo nano /home/quizbot/morning-quiz-bot-beta/.env
```

Добавьте ваш токен:
```env
BOT_TOKEN=your_telegram_bot_token_here
LOG_LEVEL=INFO
```

### 3. Перезапуск бота
```bash
sudo systemctl restart quiz-bot
sudo systemctl status quiz-bot
```

## Для Docker

### 1. Клонирование и настройка
```bash
git clone https://github.com/WeLizard/morning-quiz-bot.git
cd morning-quiz-bot
cp env.example .env
nano .env  # Укажите ваш BOT_TOKEN
```

### 2. Запуск
```bash
docker-compose up -d
```

## Полезные команды

### Ubuntu (systemd)
```bash
# Статус бота
sudo systemctl status quiz-bot

# Просмотр логов
sudo journalctl -u quiz-bot -f

# Перезапуск
sudo systemctl restart quiz-bot

# Обновление
quiz-bot-update
```

### Docker
```bash
# Просмотр логов
docker-compose logs -f quiz-bot

# Перезапуск
docker-compose restart quiz-bot

# Обновление
docker-compose pull && docker-compose up -d
```

## 📞 Поддержка

- 📖 [Полная документация](README.md)
- 🚀 [Инструкции по развертыванию](DEPLOYMENT.md)
- 🐛 [Создать Issue](https://github.com/WeLizard/morning-quiz-bot/issues)

## ✅ Проверка работы

1. Найдите бота в Telegram
2. Отправьте команду `/start`
3. Попробуйте команду `/quiz`

Если бот не отвечает, проверьте логи:
```bash
# Ubuntu
sudo journalctl -u quiz-bot -n 50

# Docker
docker-compose logs --tail=50 quiz-bot
``` 