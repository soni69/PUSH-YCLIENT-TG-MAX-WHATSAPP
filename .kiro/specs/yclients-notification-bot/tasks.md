# Implementation Plan

## Overview

План реализации production-ready бота-уведомителя YClients с интеграцией Telegram, WhatsApp и MAX. Задачи организованы от базовой инфраструктуры к функциональным компонентам и финальной интеграции.

## Tasks

- [x] 1. Инициализация проекта и базовая конфигурация
  - Создать структуру папок проекта согласно design.md (`app/`, `migrations/`, `tests/`, `docker/`)
  - Создать `pyproject.toml` и `requirements.txt` со всеми зависимостями (FastAPI, SQLAlchemy, Alembic, Celery, aiogram, httpx, pydantic-settings, structlog, slowapi, python-jose)
  - Создать `app/config.py` с Pydantic Settings — загрузка всех переменных окружения из `.env`, валидация обязательных переменных при старте
  - Создать `.env.example` со всеми переменными окружения и описаниями
  - Создать `docker/Dockerfile` с multi-stage build (builder + production)
  - Создать `docker-compose.yml` с сервисами: app, celery_worker, celery_beat, postgres, redis
  - Создать `docker/entrypoint.sh` — запуск миграций перед стартом приложения
  - Создать `app/utils/logging.py` — структурированное JSON-логирование через structlog
  - _Requirements: Req 13_

- [x] 2. База данных — модели и миграции
  - Создать `app/database.py` — async SQLAlchemy engine, session factory, connection pool (min=5, max=20)
  - Создать `app/models/client.py` — модели `Client` и `ClientChannelSettings`
  - Создать `app/models/notification.py` — модели `NotificationLog` и `ScheduledReminder`
  - Создать `app/models/template.py` — модель `NotificationTemplate`
  - Создать `app/models/task.py` — модели `TaskQueue` и `ActionDedup`
  - Настроить Alembic (`migrations/env.py`) для async SQLAlchemy
  - Создать первую миграцию Alembic с полной схемой БД (все таблицы, индексы, ограничения)
  - Создать `app/schemas/` — Pydantic-схемы для всех моделей (request/response)
  - _Requirements: Req 10_

- [x] 3. YClients API клиент
  - Создать `app/services/yclients_client.py` — базовый HTTP-клиент на httpx с Bearer-аутентификацией
  - Реализовать метод `get_appointments()` — получение записей за период
  - Реализовать метод `get_appointment()` — получение деталей записи
  - Реализовать метод `update_appointment_status()` — обновление статуса записи
  - Реализовать метод `get_client()` — получение данных клиента
  - Реализовать метод `get_clients_with_birthdays()` — клиенты с ДР на дату
  - Реализовать экспоненциальный backoff при HTTP 429 (начало 1с, макс 60с)
  - Реализовать circuit breaker — пауза 5 минут при трёх подряд HTTP 5xx
  - Создать `app/schemas/yclients.py` — Pydantic-схемы для YClients API ответов
  - _Requirements: Req 1_

- [x] 4. Реестр клиентов (ClientRegistry)
  - Создать `app/services/client_registry.py` — класс `ClientRegistry`
  - Реализовать `get_client()` — поиск клиента по yclients_client_id
  - Реализовать `link_telegram()` — привязка Telegram ID по номеру телефона
  - Реализовать `link_max()` — привязка MAX user ID по номеру телефона
  - Реализовать `unsubscribe()` — удаление привязки канала
  - Реализовать `deactivate_channel()` — деактивация канала с причиной
  - Реализовать `get_active_channels()` — получение активных каналов с настройками
  - Реализовать `find_by_phone_hash()` — поиск по SHA-256 хешу телефона
  - Реализовать хеширование телефонов в `app/utils/security.py`
  - _Requirements: Req 2_

- [x] 5. Движок шаблонов (TemplateEngine)
  - Создать `app/services/template_engine.py` — класс `TemplateEngine` на базе Jinja2
  - Реализовать `render()` — рендеринг шаблона с подстановкой переменных (< 100ms)
  - Реализовать обработку отсутствующих переменных — замена пустой строкой + WARNING
  - Реализовать `validate_template()` — валидация переменных шаблона
  - Реализовать `get_template()` — получение шаблона из БД с кешированием в Redis
  - Реализовать `invalidate_cache()` — сброс кеша при изменении шаблона
  - Создать seed-данные с шаблонами по умолчанию для всех 8 типов уведомлений × 3 канала (24 шаблона)
  - _Requirements: Req 8_

- [x] 6. Telegram адаптер
  - Создать `app/adapters/base.py` — абстрактный базовый класс `BaseAdapter`
  - Создать `app/adapters/telegram_adapter.py` — класс `TelegramAdapter` на базе aiogram 3.x
  - Реализовать `send_notification()` — отправка HTML-сообщения с inline-клавиатурой
  - Реализовать `_build_keyboard()` — построение inline-клавиатуры (✅ Подтвердить / ❌ Отменить / 🔄 Перенести)
  - Реализовать `handle_callback()` — обработка callback_query (ответ за < 3 сек)
  - Реализовать `handle_message()` — обработка команд `/start`, `/unsubscribe`, `/help`
  - Реализовать обработку ошибки 403 — деактивация канала в ClientRegistry
  - Реализовать `app/utils/rate_limiter.py` — token bucket для Telegram (30/сек на бота, 1/сек на чат)
  - Создать эндпоинт `POST /webhook/telegram` в `app/api/webhook.py`
  - _Requirements: Req 3, Req 7_

- [x] 7. WhatsApp адаптер
  - Создать `app/adapters/whatsapp_adapter.py` — класс `WhatsAppAdapter`
  - Реализовать `send_template_message()` — отправка одобренного шаблона WhatsApp
  - Реализовать `send_interactive_message()` — отправка interactive/button сообщения (макс. 3 кнопки)
  - Реализовать `send_notification()` — выбор между template и free-form на основе сессии
  - Реализовать `handle_webhook()` — обработка входящих статусов и ответов клиентов
  - Реализовать обработку ошибки "номер не в WhatsApp" — деактивация канала
  - Добавить эндпоинты `POST /webhook/whatsapp` и `GET /webhook/whatsapp` (верификация)
  - _Requirements: Req 4, Req 7_

- [x] 8. MAX адаптер
  - Создать `app/adapters/max_adapter.py` — класс `MaxAdapter`
  - Реализовать `send_notification()` — отправка сообщения с inline-клавиатурой MAX
  - Реализовать `_build_keyboard()` — построение клавиатуры в формате MAX Bot API
  - Реализовать `start_polling()` — long-polling обновлений (GET /updates?timeout=30)
  - Реализовать `handle_callback()` — обработка callback от кнопок
  - Реализовать `handle_message()` — обработка команд `/start`, `/unsubscribe`
  - Реализовать reconnect при недоступности API > 60 сек (повтор через 30 сек)
  - _Requirements: Req 5, Req 7_

- [x] 9. Dispatcher и NotificationService
  - Создать `app/services/dispatcher.py` — класс `Dispatcher`
  - Реализовать `dispatch()` — маршрутизация по активным каналам клиента
  - Реализовать `_is_quiet_hours()` — проверка тихого режима с учётом часового пояса
  - Реализовать откладывание уведомлений при тихом режиме (создание ScheduledReminder)
  - Создать `app/services/notification_service.py` — класс `NotificationService`
  - Реализовать `process_event()` — обработка события YClients → определение типа → уведомление
  - Реализовать `_check_dedup()` — дедупликация уведомлений (10 минут)
  - Реализовать `send_reminder()` — отправка напоминаний (24ч и 2ч)
  - Реализовать `send_birthday_greeting()` — поздравление с ДР
  - Реализовать обработку интерактивных действий клиента с дедупликацией (30 сек)
  - _Requirements: Req 6, Req 7, Req 2_

- [x] 10. Celery задачи и планировщик
  - Создать `app/tasks/celery_app.py` — конфигурация Celery с Redis-брокером и PostgreSQL-бэкендом
  - Создать `app/tasks/notification_tasks.py` — задача `send_notification_task` с retry (4 попытки, задержки 1/5/15/60 мин)
  - Реализовать идемпотентность задач через проверку `task_id` в `task_queue`
  - Создать `app/tasks/scheduler_tasks.py` — периодические задачи: polling (каждые 2 мин), проверка напоминаний (каждую мин), ДР (09:50)
  - Реализовать `poll_yclients` — опрос YClients за последние 3 минуты с проверкой размера очереди (> 1000 → пауза)
  - Реализовать `check_reminders` — поиск и отправка напоминаний за 24ч и 2ч
  - Реализовать `send_birthday_greetings` — поздравления с ДР
  - Создать `app/tasks/cleanup_tasks.py` — ежедневная очистка `notification_log` старше 90 дней
  - _Requirements: Req 9, Req 1, Req 6_

- [x] 11. Webhook-обработчик YClients
  - Реализовать `validate_webhook_signature()` в `app/utils/security.py` — HMAC-SHA256 валидация
  - Создать эндпоинт `POST /webhook/yclients` в `app/api/webhook.py`
  - Добавить rate limiting на `/webhook/yclients` — 100 запросов/мин с одного IP (slowapi)
  - Реализовать парсинг payload и постановку задачи в Celery-очередь (ответ за < 5 сек)
  - Реализовать запись задачи в `task_queue` при получении webhook
  - _Requirements: Req 1, Req 14_

- [x] 12. AdminPanel
  - Создать `app/api/admin.py` — FastAPI-роутер `/admin` с JWT-аутентификацией
  - Реализовать JWT-аутентификацию (python-jose) — login, refresh, logout
  - Создать HTML-шаблоны Jinja2: `dashboard.html`, `templates_editor.html`, `notification_log.html`, `clients.html`
  - Реализовать дашборд — метрики за период (отправлено по каналам, % доставки, ошибки)
  - Реализовать CRUD шаблонов — просмотр, редактирование, предпросмотр, сохранение с валидацией
  - Реализовать историю отправок с фильтрацией (канал, тип, статус, период)
  - Реализовать управление клиентами — список, деактивация каналов
  - Реализовать тестовую отправку уведомления на указанный client_id
  - Реализовать Telegram-команды для администратора: `/stats`, `/template`, `/clients`
  - _Requirements: Req 11, Req 8_

- [x] 13. Health check, метрики и логирование
  - Создать `app/api/health.py` — эндпоинт `GET /health` с проверкой PostgreSQL, Redis и внешних API
  - Создать `app/api/metrics.py` — эндпоинт `GET /metrics` в формате Prometheus (prometheus-client)
  - Настроить structlog в `app/utils/logging.py` — JSON-формат с полями timestamp, level, service, event, client_id, channel, error
  - Добавить логирование INFO для каждой успешной отправки, ERROR для ошибок, WARNING для rate limit и недоступности API
  - Добавить Prometheus-метрики: счётчики отправок по каналам/типам/статусам, гистограммы задержек
  - _Requirements: Req 12_

- [x] 14. Точка входа FastAPI и интеграция компонентов
  - Создать `app/main.py` — FastAPI-приложение с подключением всех роутеров
  - Реализовать startup/shutdown lifecycle — инициализация БД, запуск MAX polling, проверка переменных окружения
  - Добавить middleware: CORS, trusted hosts, request ID
  - Реализовать проверку обязательных переменных окружения при старте (exit code 1 при отсутствии)
  - Создать `README.md` — инструкция по развёртыванию, описание переменных окружения, примеры команд
  - _Requirements: Req 13, Req 14_

- [x] 15. Тесты
  - Настроить pytest с fixtures для тестовой БД (PostgreSQL) и мок-Redis
  - Написать юнит-тесты для `TemplateEngine` — рендеринг, валидация, отсутствующие переменные
  - Написать юнит-тесты для `Dispatcher` — маршрутизация, тихий режим, фильтрация типов
  - Написать юнит-тесты для `ClientRegistry` — привязка, отвязка, поиск по хешу
  - Написать юнит-тесты для `security.py` — HMAC валидация, хеширование телефонов
  - Написать интеграционные тесты для webhook-обработчика (валидная/невалидная подпись)
  - Написать интеграционные тесты для полного цикла уведомления (событие → лог)
  - Написать property-based тесты (Hypothesis) — идемпотентность, ограничение попыток, дедупликация
  - _Requirements: Req 1-14_

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": [1] },
    { "wave": 2, "tasks": [2] },
    { "wave": 3, "tasks": [3, 4, 5] },
    { "wave": 4, "tasks": [6, 7, 8] },
    { "wave": 5, "tasks": [9] },
    { "wave": 6, "tasks": [10, 11, 12, 13] },
    { "wave": 7, "tasks": [14] },
    { "wave": 8, "tasks": [15] }
  ],
  "dependencies": {
    "2": [1],
    "3": [2],
    "4": [2],
    "5": [2],
    "6": [2, 4],
    "7": [2, 4],
    "8": [2, 4],
    "9": [3, 4, 5, 6, 7, 8],
    "10": [9],
    "11": [9],
    "12": [5, 9],
    "13": [2],
    "14": [6, 7, 8, 9, 10, 11, 12, 13],
    "15": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
  }
}
```

## Notes

- Задачи 1-2 — фундамент, выполняются первыми
- Задачи 3-8 — независимые компоненты, могут выполняться параллельно после задачи 2
- Задача 9 зависит от задач 3, 4, 5, 6, 7, 8
- Задача 10 зависит от задачи 9
- Задача 14 собирает всё вместе
- Для WhatsApp необходимо предварительно зарегистрировать шаблоны сообщений в Meta Business Manager
- Для MAX необходимо создать бота через MasterBot на platform-api.max.ru
- Все токены хранятся только в `.env`, никогда не коммитятся в git
