# YClients Notification Bot

Production-ready бот-уведомитель, заменяющий платный сервис пуш-уведомлений YClients.

## Возможности

- 📱 **3 канала уведомлений**: Telegram, WhatsApp Business, MAX (VK)
- 🔔 **8 типов уведомлений**: новая запись, подтверждение, отмена, напоминания (24ч/2ч), изменение, день рождения
- ✅ **Интерактивные кнопки**: Подтвердить / Отменить / Перенести с обратной синхронизацией в YClients
- 🔄 **Надёжная доставка**: Celery + Redis, retry с экспоненциальной задержкой (4 попытки)
- 📊 **AdminPanel**: веб-интерфейс для управления шаблонами и статистикой
- 🐳 **Docker Compose**: одна команда для запуска всего стека

## Быстрый старт

### 1. Клонировать и настроить

```bash
git clone <repo>
cd yclients-notification-bot
cp .env.example .env
# Заполните .env реальными токенами
```

### 2. Запустить через Docker Compose

```bash
docker-compose up -d
```

Приложение будет доступно на `http://localhost:8000`.

### 3. Проверить работоспособность

```bash
curl http://localhost:8000/health
```

## Переменные окружения

| Переменная | Описание | Обязательная |
|---|---|---|
| `YCLIENTS_API_TOKEN` | Bearer-токен YClients API | ✅ |
| `YCLIENTS_COMPANY_ID` | ID компании в YClients | ✅ |
| `YCLIENTS_WEBHOOK_SECRET` | Секрет для HMAC-валидации webhook | ✅ |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота (от @BotFather) | ✅ |
| `WHATSAPP_API_TOKEN` | Bearer-токен WhatsApp Business Cloud API | ✅ |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone Number ID в Meta Business Manager | ✅ |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | WhatsApp Business Account ID | ✅ |
| `WHATSAPP_VERIFY_TOKEN` | Токен верификации webhook WhatsApp | ✅ |
| `MAX_BOT_TOKEN` | Токен бота MAX (platform-api.max.ru) | ✅ |
| `DATABASE_URL` | PostgreSQL DSN (asyncpg) | ✅ |
| `REDIS_URL` | Redis DSN | ✅ |
| `ADMIN_USERNAME` | Логин AdminPanel | ✅ |
| `ADMIN_PASSWORD` | Пароль AdminPanel | ✅ |
| `ADMIN_JWT_SECRET` | Секрет JWT (мин. 32 символа) | ✅ |
| `POLLING_INTERVAL_SECONDS` | Интервал опроса YClients (60–180) | ❌ (120) |
| `TIMEZONE` | Часовой пояс (IANA) | ❌ (Europe/Moscow) |
| `LOG_LEVEL` | Уровень логирования | ❌ (INFO) |

## Архитектура

```
YClients API ──webhook──► FastAPI ──► Celery Queue ──► Adapters
                                                         ├── Telegram Bot API
                                                         ├── WhatsApp Business Cloud API
                                                         └── MAX Bot API (botapi.max.ru)
                                          │
                                     PostgreSQL + Redis
```

## Настройка webhook YClients

1. В настройках YClients укажите URL webhook: `https://your-domain.com/webhook/yclients`
2. Установите секретный ключ и запишите его в `YCLIENTS_WEBHOOK_SECRET`

## Настройка Telegram

1. Создайте бота через @BotFather
2. Получите токен и запишите в `TELEGRAM_BOT_TOKEN`
3. Установите webhook: `https://your-domain.com/webhook/telegram`

## Настройка WhatsApp

1. Создайте приложение в Meta Business Manager
2. Настройте WhatsApp Business Cloud API
3. Зарегистрируйте шаблоны сообщений (обязательно для первого контакта)
4. Настройте webhook: `https://your-domain.com/webhook/whatsapp`

## Настройка MAX

1. Создайте бота через MasterBot на platform-api.max.ru
2. Получите токен и запишите в `MAX_BOT_TOKEN`
3. Бот использует long-polling (webhook опционален)

## AdminPanel

Доступна по адресу `http://localhost:8000/admin/`

Для входа используйте `ADMIN_USERNAME` и `ADMIN_PASSWORD` из `.env`.

## Команды

```bash
# Запуск в development-режиме
docker-compose up

# Запуск в фоне
docker-compose up -d

# Просмотр логов
docker-compose logs -f app

# Применить миграции вручную
docker-compose exec app alembic upgrade head

# Остановить
docker-compose down

# Остановить и удалить данные
docker-compose down -v
```

## Структура проекта

```
app/
├── adapters/          # Адаптеры мессенджеров (Telegram, WhatsApp, MAX)
├── admin/templates/   # HTML-шаблоны AdminPanel
├── api/               # FastAPI роутеры (webhook, health, metrics, admin)
├── models/            # SQLAlchemy ORM модели
├── schemas/           # Pydantic схемы
├── services/          # Бизнес-логика (NotificationService, Dispatcher, TemplateEngine)
├── tasks/             # Celery задачи
├── utils/             # Утилиты (logging, security, rate_limiter)
├── config.py          # Pydantic Settings
├── database.py        # SQLAlchemy engine
└── main.py            # FastAPI приложение
migrations/            # Alembic миграции
tests/                 # Тесты (unit, integration, property)
docker/                # Dockerfile, entrypoint.sh
docker-compose.yml
.env.example
```
