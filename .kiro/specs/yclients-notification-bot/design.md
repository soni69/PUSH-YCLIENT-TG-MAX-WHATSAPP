# Design Document: yclients-notification-bot

## Overview

Система представляет собой production-ready бот-уведомитель, заменяющий платный сервис пуш-уведомлений YClients. Система интегрируется с CRM YClients через официальное API, получает события (записи, изменения статусов, напоминания, дни рождения) и доставляет персонализированные уведомления клиентам через три канала: Telegram, WhatsApp и MAX (мессенджер VK). Клиенты могут интерактивно подтверждать, отменять или переносить записи прямо из мессенджера, а изменения автоматически синхронизируются обратно в YClients.

---

## Architecture

### Диаграмма компонентов

```mermaid
graph TB
    subgraph External["Внешние сервисы"]
        YC[YClients API]
        TG[Telegram Bot API]
        WA[WhatsApp Business Cloud API]
        MX[MAX Bot API]
    end

    subgraph Core["Ядро системы (FastAPI)"]
        WH[WebhookHandler\n/webhook/yclients]
        NS[NotificationService]
        TE[TemplateEngine]
        CR[ClientRegistry]
        DS[Dispatcher]
    end

    subgraph Adapters["Адаптеры мессенджеров"]
        TA[TelegramAdapter]
        WA2[WhatsAppAdapter]
        MA[MaxAdapter]
    end

    subgraph Workers["Фоновые задачи (Celery)"]
        SC[Scheduler\nAPScheduler]
        RQ[RetryQueue]
        CL[Cleanup Task]
    end

    subgraph Storage["Хранилище"]
        PG[(PostgreSQL)]
        RD[(Redis)]
    end

    subgraph Admin["Администрирование"]
        AP[AdminPanel\n/admin]
        HL[/health]
        MT[/metrics]
    end

    YC -->|webhook POST| WH
    SC -->|polling| YC
    WH --> NS
    SC --> NS
    NS --> TE
    NS --> CR
    NS --> DS
    DS --> TA
    DS --> WA2
    DS --> MA
    TA <-->|Bot API| TG
    WA2 <-->|Graph API| WA
    MA <-->|MAX API| MX
    TA -->|callback| NS
    WA2 -->|callback| NS
    MA -->|callback| NS
    NS -->|update status| YC
    Workers --> RD
    Core --> PG
    Core --> RD
    AP --> PG
    AP --> RD
```

### Диаграмма потока данных

```mermaid
sequenceDiagram
    participant YC as YClients
    participant WH as WebhookHandler
    participant NS as NotificationService
    participant DS as Dispatcher
    participant CR as ClientRegistry
    participant TE as TemplateEngine
    participant AD as Adapter (TG/WA/MAX)
    participant RQ as RetryQueue (Celery)
    participant DB as PostgreSQL

    YC->>WH: POST /webhook/yclients (событие)
    WH->>WH: Валидация подписи HMAC
    WH->>RQ: Поставить задачу в очередь
    RQ->>NS: Обработать событие
    NS->>CR: Получить привязки клиента
    CR->>DB: SELECT client channels
    DB-->>CR: telegram_id, whatsapp_phone, max_user_id
    NS->>TE: Рендерить шаблон
    TE-->>NS: Готовое сообщение
    NS->>DS: Маршрутизировать уведомление
    DS->>AD: Отправить сообщение
    AD-->>DS: OK / Error
    DS->>DB: INSERT notification_log
    alt Ошибка доставки
        RQ->>RQ: Экспоненциальная задержка (1/5/15/60 мин)
        RQ->>AD: Повторная попытка (макс. 4)
    end
```

---

## Структура проекта

```
yclients-notification-bot/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI приложение, точка входа
│   ├── config.py                  # Pydantic Settings, загрузка .env
│   ├── database.py                # SQLAlchemy engine, session factory
│   │
│   ├── api/                       # FastAPI роутеры
│   │   ├── __init__.py
│   │   ├── webhook.py             # POST /webhook/yclients
│   │   ├── health.py              # GET /health
│   │   ├── metrics.py             # GET /metrics (Prometheus)
│   │   └── admin.py               # /admin роутер
│   │
│   ├── models/                    # SQLAlchemy ORM модели
│   │   ├── __init__.py
│   │   ├── client.py              # Client, ClientChannel
│   │   ├── notification.py        # NotificationLog, ScheduledReminder
│   │   ├── template.py            # NotificationTemplate
│   │   └── task.py                # TaskQueue
│   │
│   ├── schemas/                   # Pydantic схемы (request/response)
│   │   ├── __init__.py
│   │   ├── yclients.py            # YClients webhook payload
│   │   ├── notification.py        # NotificationRequest, NotificationResult
│   │   └── admin.py               # AdminPanel schemas
│   │
│   ├── services/                  # Бизнес-логика
│   │   ├── __init__.py
│   │   ├── notification_service.py
│   │   ├── template_engine.py
│   │   ├── client_registry.py
│   │   ├── dispatcher.py
│   │   └── yclients_client.py
│   │
│   ├── adapters/                  # Адаптеры мессенджеров
│   │   ├── __init__.py
│   │   ├── base.py                # Абстрактный базовый адаптер
│   │   ├── telegram_adapter.py
│   │   ├── whatsapp_adapter.py
│   │   └── max_adapter.py
│   │
│   ├── tasks/                     # Celery задачи
│   │   ├── __init__.py
│   │   ├── celery_app.py          # Celery конфигурация
│   │   ├── notification_tasks.py  # Задачи отправки уведомлений
│   │   ├── scheduler_tasks.py     # Периодические задачи (polling, reminders)
│   │   └── cleanup_tasks.py       # Очистка старых записей
│   │
│   ├── admin/                     # AdminPanel (Starlette Admin или кастомный)
│   │   ├── __init__.py
│   │   ├── views.py
│   │   └── templates/
│   │       ├── dashboard.html
│   │       ├── templates_editor.html
│   │       └── notification_log.html
│   │
│   └── utils/
│       ├── __init__.py
│       ├── rate_limiter.py        # RateLimiter (token bucket)
│       ├── security.py            # HMAC валидация, хеширование телефонов
│       └── logging.py             # Структурированное JSON-логирование
│
├── migrations/                    # Alembic миграции
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── property/                  # Property-based тесты (Hypothesis)
│
├── docker/
│   ├── Dockerfile
│   └── entrypoint.sh
│
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Схема базы данных

### Таблица `clients`

Хранит привязку клиентов YClients к каналам мессенджеров.

```sql
CREATE TABLE clients (
    id                   SERIAL PRIMARY KEY,
    yclients_client_id   VARCHAR(64) NOT NULL UNIQUE,  -- ID клиента в YClients
    telegram_id          BIGINT,                        -- Telegram user ID
    whatsapp_phone_hash  VARCHAR(64),                   -- SHA-256 хеш номера телефона
    whatsapp_phone_enc   VARCHAR(32),                   -- Зашифрованный номер для отправки
    max_user_id          VARCHAR(64),                   -- MAX user ID
    preferred_channel    VARCHAR(16) DEFAULT 'telegram', -- telegram | whatsapp | max
    is_active            BOOLEAN DEFAULT TRUE,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_clients_yclients_id ON clients(yclients_client_id);
CREATE INDEX idx_clients_telegram_id ON clients(telegram_id);
CREATE INDEX idx_clients_whatsapp_hash ON clients(whatsapp_phone_hash);
```

### Таблица `client_channel_settings`

Настройки уведомлений по каждому каналу отдельно.

```sql
CREATE TABLE client_channel_settings (
    id                   SERIAL PRIMARY KEY,
    client_id            INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    channel              VARCHAR(16) NOT NULL,  -- telegram | whatsapp | max
    is_enabled           BOOLEAN DEFAULT TRUE,
    notification_types   JSONB DEFAULT '["all"]',  -- список типов или ["all"]
    quiet_hours_start    TIME,                      -- начало тихого режима (напр. 22:00)
    quiet_hours_end      TIME,                      -- конец тихого режима (напр. 09:00)
    timezone             VARCHAR(64) DEFAULT 'Europe/Moscow',
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id, channel)
);
```

### Таблица `notification_templates`

Шаблоны сообщений для каждого типа уведомления и канала.

```sql
CREATE TABLE notification_templates (
    id                   SERIAL PRIMARY KEY,
    notification_type    VARCHAR(64) NOT NULL,  -- new_appointment, confirmed, cancelled, etc.
    channel              VARCHAR(16) NOT NULL,  -- telegram | whatsapp | max
    language             VARCHAR(8) DEFAULT 'ru',
    subject              VARCHAR(256),          -- заголовок (для будущего email-канала)
    body_template        TEXT NOT NULL,         -- текст шаблона с {{переменными}}
    is_active            BOOLEAN DEFAULT TRUE,
    is_default           BOOLEAN DEFAULT FALSE,
    created_by           VARCHAR(64),           -- 'system' или имя администратора
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(notification_type, channel, language)
);
```

### Таблица `notification_log`

История всех отправленных уведомлений (AuditLog).

```sql
CREATE TABLE notification_log (
    id                   BIGSERIAL PRIMARY KEY,
    client_id            VARCHAR(64) NOT NULL,   -- yclients_client_id
    channel              VARCHAR(16) NOT NULL,
    notification_type    VARCHAR(64) NOT NULL,
    appointment_id       VARCHAR(64),            -- ID записи в YClients
    status               VARCHAR(16) NOT NULL,   -- pending | sent | delivered | failed | skipped
    error_message        TEXT,
    message_id           VARCHAR(128),           -- ID сообщения в мессенджере
    sent_at              TIMESTAMPTZ,
    delivered_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notif_log_client_id ON notification_log(client_id);
CREATE INDEX idx_notif_log_appointment_id ON notification_log(appointment_id);
CREATE INDEX idx_notif_log_sent_at ON notification_log(sent_at);
CREATE INDEX idx_notif_log_status ON notification_log(status);
```

### Таблица `scheduled_reminders`

Запланированные напоминания (за 24 часа и за 2 часа до записи).

```sql
CREATE TABLE scheduled_reminders (
    id                   SERIAL PRIMARY KEY,
    appointment_id       VARCHAR(64) NOT NULL,
    client_id            VARCHAR(64) NOT NULL,
    reminder_type        VARCHAR(32) NOT NULL,  -- reminder_24h | reminder_2h | birthday
    scheduled_at         TIMESTAMPTZ NOT NULL,
    status               VARCHAR(16) DEFAULT 'pending',  -- pending | sent | cancelled
    celery_task_id       VARCHAR(128),
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(appointment_id, reminder_type)
);

CREATE INDEX idx_reminders_scheduled_at ON scheduled_reminders(scheduled_at);
CREATE INDEX idx_reminders_status ON scheduled_reminders(status);
```

### Таблица `task_queue`

Состояние задач Celery для обеспечения идемпотентности и устойчивости к перезапускам.

```sql
CREATE TABLE task_queue (
    id                   SERIAL PRIMARY KEY,
    task_id              VARCHAR(128) NOT NULL UNIQUE,  -- Celery task UUID
    task_type            VARCHAR(64) NOT NULL,
    payload              JSONB NOT NULL,
    status               VARCHAR(16) DEFAULT 'pending',  -- pending | running | success | failed
    attempts             INTEGER DEFAULT 0,
    max_attempts         INTEGER DEFAULT 4,
    next_retry_at        TIMESTAMPTZ,
    error_message        TEXT,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_task_queue_status ON task_queue(status);
CREATE INDEX idx_task_queue_next_retry ON task_queue(next_retry_at);
```

### Таблица `action_dedup`

Дедупликация интерактивных действий клиентов (защита от двойного нажатия).

```sql
CREATE TABLE action_dedup (
    id                   SERIAL PRIMARY KEY,
    appointment_id       VARCHAR(64) NOT NULL,
    action               VARCHAR(32) NOT NULL,  -- confirm | cancel | reschedule
    client_id            VARCHAR(64) NOT NULL,
    channel              VARCHAR(16) NOT NULL,
    executed_at          TIMESTAMPTZ DEFAULT NOW(),
    expires_at           TIMESTAMPTZ NOT NULL    -- executed_at + 30 seconds
);

CREATE INDEX idx_dedup_appointment_action ON action_dedup(appointment_id, action, expires_at);
```

---

## Components and Interfaces

### YClientsClient

Отвечает за всё взаимодействие с YClients API: аутентификацию, получение записей, обновление статусов.

```python
class YClientsClient:
    """
    Клиент YClients API с поддержкой retry и rate limiting.
    Базовый URL: https://api.yclients.com/api/v1
    """

    async def get_appointments(
        self,
        company_id: int,
        start_date: datetime,
        end_date: datetime,
        page: int = 1,
        count: int = 100,
    ) -> list[Appointment]:
        """Получить список записей за период. Используется при polling."""

    async def get_appointment(self, company_id: int, appointment_id: int) -> Appointment:
        """Получить детали конкретной записи."""

    async def update_appointment_status(
        self,
        company_id: int,
        appointment_id: int,
        status: AppointmentStatus,
    ) -> bool:
        """Обновить статус записи (подтверждена/отменена)."""

    async def get_client(self, company_id: int, client_id: int) -> ClientInfo:
        """Получить данные клиента (имя, телефон, день рождения)."""

    async def get_clients_with_birthdays(
        self, company_id: int, date: date
    ) -> list[ClientInfo]:
        """Получить клиентов с днём рождения на указанную дату."""

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """
        Внутренний метод с:
        - Экспоненциальным backoff при 429 (начало 1с, макс 60с)
        - Остановкой на 5 минут при трёх подряд 5xx
        - Логированием без токена
        """
```

**Конфигурация:**
- `YCLIENTS_API_TOKEN` — Bearer-токен авторизации
- `YCLIENTS_COMPANY_ID` — ID компании
- Base URL: `https://api.yclients.com/api/v1`
- Заголовки: `Authorization: Bearer {token}`, `Accept: application/vnd.yclients.v2+json`

---

### Dispatcher

Маршрутизирует уведомления по каналам на основе настроек клиента.

```python
class Dispatcher:
    """
    Определяет канал(ы) доставки для каждого клиента и делегирует
    отправку соответствующему адаптеру.
    """

    async def dispatch(
        self,
        client: Client,
        notification_type: NotificationType,
        rendered_message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> list[DeliveryResult]:
        """
        Логика маршрутизации:
        1. Получить все активные каналы клиента из ClientRegistry
        2. Для каждого канала проверить:
           a. Канал включён в client_channel_settings
           b. Тип уведомления разрешён для канала
           c. Текущее время вне тихого режима (кроме типа 'in_progress')
        3. Отправить через соответствующий адаптер
        4. Записать результат в notification_log
        """

    def _is_quiet_hours(self, settings: ChannelSettings, now: datetime) -> bool:
        """Проверить, попадает ли текущее время в тихий режим."""

    def _select_adapters(
        self, client: Client, notification_type: NotificationType
    ) -> list[BaseAdapter]:
        """Выбрать адаптеры для доставки согласно настройкам клиента."""
```

**Логика выбора канала:**

```mermaid
flowchart TD
    A[Получить клиента] --> B{Есть активные каналы?}
    B -->|Нет| C[Лог WARNING, пропустить]
    B -->|Да| D[Для каждого канала]
    D --> E{Канал включён?}
    E -->|Нет| F[Пропустить канал]
    E -->|Да| G{Тип уведомления разрешён?}
    G -->|Нет| F
    G -->|Да| H{Тихий режим?}
    H -->|Да и тип != in_progress| I[Отложить до конца тихого режима]
    H -->|Нет| J[Отправить через адаптер]
    I --> K[Создать ScheduledReminder]
    J --> L[Записать в notification_log]
```

---

### TelegramAdapter

```python
class TelegramAdapter(BaseAdapter):
    """
    Адаптер Telegram Bot API.
    Библиотека: aiogram 3.x
    """

    async def send_notification(
        self,
        telegram_id: int,
        message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> DeliveryResult:
        """
        Отправить уведомление с inline-клавиатурой.
        Кнопки: ✅ Подтвердить | ❌ Отменить | 🔄 Перенести
        Callback data: confirm:{appointment_id} | cancel:{appointment_id} | reschedule:{appointment_id}
        """

    async def handle_callback(self, callback_query: CallbackQuery) -> None:
        """
        Обработать нажатие inline-кнопки.
        Ответить answer_callback_query в течение 3 секунд.
        """

    async def handle_message(self, message: Message) -> None:
        """
        Обработать текстовое сообщение от клиента.
        Команды: /start, /unsubscribe, /help
        Прочий текст → справочное сообщение с командами.
        """

    def _build_keyboard(self, appointment_id: str) -> InlineKeyboardMarkup:
        """Построить inline-клавиатуру для записи."""

    async def _handle_403(self, telegram_id: int) -> None:
        """Деактивировать Telegram-канал при блокировке бота."""
```

**Rate limiting:** 30 сообщений/сек на бота, 1 сообщение/сек в один чат (token bucket).

---

### WhatsAppAdapter

```python
class WhatsAppAdapter(BaseAdapter):
    """
    Адаптер WhatsApp Business Cloud API.
    Endpoint: https://graph.facebook.com/v18.0/{phone_number_id}/messages
    """

    async def send_notification(
        self,
        phone: str,
        message: RenderedMessage,
        appointment_id: str | None = None,
        use_template: bool = True,
    ) -> DeliveryResult:
        """
        Отправить уведомление.
        use_template=True → template message (первичный контакт)
        use_template=False → free-form interactive message (в рамках 24ч сессии)
        """

    async def send_template_message(
        self,
        phone: str,
        template_name: str,
        components: list[dict],
    ) -> DeliveryResult:
        """Отправить одобренный шаблон WhatsApp."""

    async def send_interactive_message(
        self,
        phone: str,
        body: str,
        buttons: list[dict],
    ) -> DeliveryResult:
        """Отправить интерактивное сообщение с кнопками (макс. 3)."""

    async def handle_webhook(self, payload: dict) -> None:
        """Обработать входящий webhook от WhatsApp (статусы, ответы клиентов)."""
```

**Конфигурация:**
- `WHATSAPP_API_TOKEN` — Bearer-токен Graph API
- `WHATSAPP_PHONE_NUMBER_ID` — ID номера телефона бизнеса
- `WHATSAPP_BUSINESS_ACCOUNT_ID` — ID бизнес-аккаунта

---

### MaxAdapter

```python
class MaxAdapter(BaseAdapter):
    """
    Адаптер MAX Bot API.
    Endpoint: https://botapi.max.ru
    Документация: https://dev.max.ru/
    """

    async def send_notification(
        self,
        max_user_id: str,
        message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> DeliveryResult:
        """
        Отправить сообщение с inline-клавиатурой.
        POST /messages?user_id={max_user_id}
        """

    async def start_polling(self) -> None:
        """
        Запустить long-polling для получения обновлений.
        GET /updates?timeout=30&marker={last_marker}
        """

    async def handle_callback(self, update: MaxUpdate) -> None:
        """Обработать callback от нажатия кнопки."""

    def _build_keyboard(self, appointment_id: str) -> dict:
        """
        Построить клавиатуру MAX Bot API формата:
        {
          "buttons": [[
            {"type": "callback", "text": "✅ Подтвердить", "payload": "confirm:{id}"},
            {"type": "callback", "text": "❌ Отменить", "payload": "cancel:{id}"}
          ]]
        }
        """
```

**Конфигурация:**
- `MAX_BOT_TOKEN` — токен бота MAX
- Base URL: `https://botapi.max.ru`
- Поддержка форматирования: **жирный**, _курсив_, [ссылки](url)

---

### NotificationService

```python
class NotificationService:
    """
    Центральный сервис формирования и отправки уведомлений.
    """

    async def process_event(self, event: YClientsEvent) -> None:
        """
        Обработать событие из YClients:
        1. Определить тип уведомления
        2. Получить данные клиента и записи
        3. Проверить дедупликацию (10 минут)
        4. Сформировать уведомление через TemplateEngine
        5. Передать в Dispatcher
        """

    async def send_reminder(
        self, appointment_id: str, reminder_type: ReminderType
    ) -> None:
        """Отправить напоминание (24ч или 2ч до записи)."""

    async def send_birthday_greeting(self, client_id: str) -> None:
        """Отправить поздравление с днём рождения."""

    async def _check_dedup(
        self,
        client_id: str,
        appointment_id: str,
        notification_type: str,
        window_minutes: int = 10,
    ) -> bool:
        """
        Проверить, не было ли уже отправлено такое уведомление
        в течение window_minutes минут.
        """
```

---

### TemplateEngine

```python
class TemplateEngine:
    """
    Движок шаблонов с поддержкой персонализации.
    Использует Jinja2 для рендеринга.
    """

    def render(
        self,
        notification_type: str,
        channel: str,
        context: dict,
        language: str = "ru",
    ) -> RenderedMessage:
        """
        Рендерить шаблон за < 100ms.
        Переменные: {{client_name}}, {{master_name}}, {{service_name}},
                    {{appointment_date}}, {{appointment_time}},
                    {{salon_address}}, {{salon_phone}}, {{salon_name}}
        Отсутствующие переменные → пустая строка + WARNING в лог.
        """

    def validate_template(self, template_body: str) -> list[str]:
        """
        Валидировать шаблон: вернуть список некорректных переменных.
        Корректные переменные: ALLOWED_VARIABLES константа.
        """

    def get_template(self, notification_type: str, channel: str) -> NotificationTemplate:
        """Получить активный шаблон из БД (с кешированием в Redis)."""

    def invalidate_cache(self, notification_type: str, channel: str) -> None:
        """Сбросить кеш шаблона при изменении через AdminPanel."""
```

**Поддерживаемые переменные:**

| Переменная | Описание |
|---|---|
| `{{client_name}}` | Имя клиента |
| `{{master_name}}` | Имя мастера |
| `{{service_name}}` | Название услуги |
| `{{appointment_date}}` | Дата записи (дд.мм.гггг) |
| `{{appointment_time}}` | Время записи (чч:мм) |
| `{{salon_address}}` | Адрес салона |
| `{{salon_phone}}` | Телефон салона |
| `{{salon_name}}` | Название салона |

---

### ClientRegistry

```python
class ClientRegistry:
    """
    Реестр соответствия client_id YClients → идентификаторам мессенджеров.
    """

    async def get_client(self, yclients_client_id: str) -> Client | None:
        """Получить клиента по ID YClients."""

    async def link_telegram(self, phone: str, telegram_id: int) -> Client:
        """
        Привязать Telegram ID к клиенту по номеру телефона.
        Поиск клиента в YClients по телефону, затем сохранение в БД.
        """

    async def link_max(self, phone: str, max_user_id: str) -> Client:
        """Привязать MAX user ID к клиенту по номеру телефона."""

    async def unsubscribe(self, client_id: str, channel: str) -> None:
        """Удалить привязку канала для клиента."""

    async def deactivate_channel(
        self, client_id: str, channel: str, reason: str
    ) -> None:
        """Деактивировать канал (при блокировке бота, неверном номере и т.д.)."""

    async def get_active_channels(self, client_id: str) -> list[ChannelSettings]:
        """Получить все активные каналы клиента с настройками."""

    async def find_by_phone_hash(self, phone: str) -> Client | None:
        """Найти клиента по хешу номера телефона (SHA-256)."""
```

---

### RetryQueue

Реализован через Celery с PostgreSQL-бэкендом для хранения состояния.

```python
# tasks/notification_tasks.py

@celery_app.task(
    bind=True,
    max_retries=4,
    default_retry_delay=60,
    autoretry_for=(DeliveryError,),
    retry_backoff=True,
    retry_backoff_max=3600,
)
def send_notification_task(self, task_payload: dict) -> dict:
    """
    Задача отправки уведомления с retry.
    Задержки: 1 мин → 5 мин → 15 мин → 60 мин
    После 4 неудач: статус 'failed' в notification_log.
    Идемпотентность: проверка task_id в task_queue перед выполнением.
    """
```

**Схема retry:**

```mermaid
stateDiagram-v2
    [*] --> Pending: Задача создана
    Pending --> Running: Celery worker взял задачу
    Running --> Success: Доставлено
    Running --> Retry1: Ошибка (задержка 1 мин)
    Retry1 --> Running: Повторная попытка
    Running --> Retry2: Ошибка (задержка 5 мин)
    Retry2 --> Running: Повторная попытка
    Running --> Retry3: Ошибка (задержка 15 мин)
    Retry3 --> Running: Повторная попытка
    Running --> Retry4: Ошибка (задержка 60 мин)
    Retry4 --> Running: Последняя попытка
    Running --> Failed: Все 4 попытки исчерпаны
    Success --> [*]
    Failed --> [*]: Запись в AuditLog
```

---

### AdminPanel

Реализована на базе `starlette-admin` или кастомного FastAPI-роутера с Jinja2-шаблонами.

**Эндпоинты AdminPanel:**

| Метод | Путь | Описание |
|---|---|---|
| GET | `/admin` | Дашборд с метриками |
| GET | `/admin/templates` | Список шаблонов |
| GET | `/admin/templates/{id}/edit` | Редактор шаблона |
| POST | `/admin/templates/{id}` | Сохранить шаблон |
| GET | `/admin/notifications` | История отправок |
| GET | `/admin/clients` | Список клиентов |
| POST | `/admin/test-send` | Тестовая отправка |
| POST | `/admin/clients/{id}/deactivate-channel` | Деактивировать канал |

---

## Data Models

### Перечисления

```python
class NotificationType(str, Enum):
    NEW_APPOINTMENT = "new_appointment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    CHANGED = "changed"
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    BIRTHDAY = "birthday"

class Channel(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    MAX = "max"

class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"

class AppointmentStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    COMPLETED = "completed"
```

### Pydantic-схемы YClients webhook

```python
class YClientsWebhookPayload(BaseModel):
    """Входящий webhook от YClients."""
    company_id: int
    resource: str          # "record", "client"
    resource_id: int
    status: str            # "create", "update", "delete"
    data: dict

class AppointmentData(BaseModel):
    """Данные записи из YClients API."""
    id: int
    company_id: int
    client_id: int
    staff_id: int
    services: list[ServiceData]
    date: datetime
    datetime: datetime
    status_id: int
    comment: str | None = None

class ClientInfo(BaseModel):
    """Данные клиента из YClients API."""
    id: int
    name: str
    phone: str
    email: str | None = None
    birth_date: date | None = None
```

---

## Обработка Webhook и Polling

### Webhook-обработчик

```mermaid
sequenceDiagram
    participant YC as YClients
    participant WH as WebhookHandler (FastAPI)
    participant SEC as Security (HMAC)
    participant RQ as Celery Queue
    participant DB as PostgreSQL

    YC->>WH: POST /webhook/yclients\n{payload, X-Signature}
    WH->>SEC: Проверить HMAC-SHA256 подпись
    alt Подпись неверна
        SEC-->>WH: Invalid
        WH-->>YC: 401 Unauthorized
    else Подпись верна
        SEC-->>WH: Valid
        WH->>WH: Распарсить payload
        WH->>RQ: celery.send_task("process_event", payload)
        WH->>DB: INSERT task_queue (task_id, payload, status=pending)
        WH-->>YC: 200 OK (< 5 секунд)
    end
    RQ->>RQ: Асинхронная обработка события
```

**Валидация подписи:**

```python
def validate_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> bool:
    """
    YClients подписывает webhook HMAC-SHA256.
    Заголовок: X-Yclients-Signature: sha256={hex_digest}
    """
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### Polling-механизм

```python
# tasks/scheduler_tasks.py

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Polling каждые 2 минуты
    sender.add_periodic_task(120.0, poll_yclients.s(), name="poll_yclients")
    # Проверка напоминаний каждую минуту
    sender.add_periodic_task(60.0, check_reminders.s(), name="check_reminders")
    # Поздравления с ДР в 09:50 (отправка в 10:00)
    sender.add_periodic_task(
        crontab(hour=9, minute=50),
        send_birthday_greetings.s(),
        name="birthday_greetings",
    )
    # Очистка старых записей в 03:00
    sender.add_periodic_task(
        crontab(hour=3, minute=0),
        cleanup_old_logs.s(),
        name="cleanup_logs",
    )

@celery_app.task
async def poll_yclients():
    """
    Опросить YClients API за последние 3 минуты.
    Пропустить, если очередь содержит > 1000 задач.
    """
    queue_size = get_queue_size()
    if queue_size > 1000:
        logger.warning("Queue overloaded, skipping poll", queue_size=queue_size)
        return

    now = datetime.utcnow()
    appointments = await yclients_client.get_appointments(
        company_id=settings.YCLIENTS_COMPANY_ID,
        start_date=now - timedelta(minutes=3),
        end_date=now,
    )
    for appointment in appointments:
        process_event.delay(appointment.dict())
```

---

## API эндпоинты FastAPI

### Основные эндпоинты

| Метод | Путь | Описание | Auth |
|---|---|---|---|
| POST | `/webhook/yclients` | Входящие события YClients | HMAC подпись |
| POST | `/webhook/telegram` | Входящие обновления Telegram | Bot token |
| POST | `/webhook/whatsapp` | Входящие обновления WhatsApp | Verify token |
| GET | `/webhook/whatsapp` | Верификация WhatsApp webhook | Verify token |
| GET | `/health` | Проверка работоспособности | Нет |
| GET | `/metrics` | Prometheus метрики | IP whitelist |

### Схемы ответов

```python
# GET /health
class HealthResponse(BaseModel):
    status: str           # "healthy" | "degraded" | "unhealthy"
    timestamp: datetime
    services: dict[str, ServiceStatus]

class ServiceStatus(BaseModel):
    status: str           # "ok" | "error"
    latency_ms: float | None = None
    error: str | None = None

# Пример ответа /health:
{
    "status": "healthy",
    "timestamp": "2024-01-15T10:30:00Z",
    "services": {
        "postgresql": {"status": "ok", "latency_ms": 2.3},
        "redis": {"status": "ok", "latency_ms": 0.8},
        "yclients_api": {"status": "ok", "latency_ms": 145.2},
        "telegram_api": {"status": "ok", "latency_ms": 89.1},
        "whatsapp_api": {"status": "ok", "latency_ms": 201.5},
        "max_api": {"status": "ok", "latency_ms": 67.3}
    }
}
```

### Rate limiting эндпоинтов

```python
# Ограничение /webhook/yclients: 100 запросов/мин с одного IP
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/webhook/yclients")
@limiter.limit("100/minute")
async def yclients_webhook(request: Request, payload: YClientsWebhookPayload):
    ...
```

---

## Шаблоны сообщений по умолчанию

### Telegram (HTML-разметка)

```
# new_appointment / telegram
🎉 <b>Новая запись!</b>

Здравствуйте, {{client_name}}!

Вы записаны:
📅 <b>{{appointment_date}}</b> в <b>{{appointment_time}}</b>
💇 Услуга: {{service_name}}
👤 Мастер: {{master_name}}
📍 {{salon_name}}, {{salon_address}}

Ждём вас! По вопросам: {{salon_phone}}

# confirmed / telegram
✅ <b>Запись подтверждена</b>

{{client_name}}, ваша запись подтверждена:
📅 {{appointment_date}} в {{appointment_time}}
👤 Мастер: {{master_name}}

# cancelled / telegram
❌ <b>Запись отменена</b>

{{client_name}}, ваша запись на {{appointment_date}} в {{appointment_time}} отменена.
Для новой записи: {{salon_phone}}

# in_progress / telegram
⏰ <b>Мастер ждёт вас!</b>

{{client_name}}, ваш мастер {{master_name}} готов принять вас прямо сейчас.
📍 {{salon_name}}, {{salon_address}}

# changed / telegram
🔄 <b>Изменение записи</b>

{{client_name}}, ваша запись изменена:
📅 Новая дата: <b>{{appointment_date}}</b> в <b>{{appointment_time}}</b>
👤 Мастер: {{master_name}}
💇 Услуга: {{service_name}}

# reminder_24h / telegram
⏰ <b>Напоминание о записи</b>

{{client_name}}, напоминаем о вашей записи <b>завтра</b>:
📅 {{appointment_date}} в {{appointment_time}}
👤 Мастер: {{master_name}}
📍 {{salon_name}}

# reminder_2h / telegram
🔔 <b>Скоро ваша запись!</b>

{{client_name}}, через 2 часа ваша запись:
⏰ {{appointment_time}}
👤 Мастер: {{master_name}}
📍 {{salon_address}}

# birthday / telegram
🎂 <b>С Днём Рождения!</b>

Дорогой(ая) {{client_name}}!

Команда {{salon_name}} поздравляет вас с Днём Рождения! 🎉
Желаем здоровья, красоты и отличного настроения!

Ждём вас в гости: {{salon_phone}}
```

### WhatsApp (шаблоны, plain text)

```
# new_appointment / whatsapp (template: appointment_created)
Здравствуйте, {{client_name}}! Вы записаны в {{salon_name}} на {{appointment_date}} в {{appointment_time}}. Мастер: {{master_name}}, услуга: {{service_name}}. Адрес: {{salon_address}}. Тел: {{salon_phone}}

# reminder_24h / whatsapp (template: appointment_reminder_24h)
Напоминаем о вашей записи в {{salon_name}} завтра, {{appointment_date}} в {{appointment_time}}. Мастер: {{master_name}}. Ждём вас!

# birthday / whatsapp (template: birthday_greeting)
С Днём Рождения, {{client_name}}! Команда {{salon_name}} поздравляет вас и ждёт в гости. Тел: {{salon_phone}}
```

### MAX (Markdown-форматирование)

```
# new_appointment / max
🎉 **Новая запись!**

Здравствуйте, {{client_name}}!

Вы записаны:
📅 **{{appointment_date}}** в **{{appointment_time}}**
💇 Услуга: {{service_name}}
👤 Мастер: {{master_name}}
📍 {{salon_name}}, {{salon_address}}

По вопросам: {{salon_phone}}
```

---

## Интеграция с MAX Bot API

### Аутентификация

```python
# Все запросы к MAX Bot API
headers = {
    "Authorization": f"Bearer {settings.MAX_BOT_TOKEN}",
    "Content-Type": "application/json",
}
BASE_URL = "https://botapi.max.ru"
```

### Отправка сообщения с клавиатурой

```python
# POST https://botapi.max.ru/messages?user_id={max_user_id}
payload = {
    "text": "Ваша запись на завтра в 14:00",
    "attachments": [
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [
                        {
                            "type": "callback",
                            "text": "✅ Подтвердить",
                            "payload": f"confirm:{appointment_id}"
                        },
                        {
                            "type": "callback",
                            "text": "❌ Отменить",
                            "payload": f"cancel:{appointment_id}"
                        }
                    ],
                    [
                        {
                            "type": "callback",
                            "text": "🔄 Перенести",
                            "payload": f"reschedule:{appointment_id}"
                        }
                    ]
                ]
            }
        }
    ]
}
```

### Long-polling обновлений

```python
# GET https://botapi.max.ru/updates?timeout=30&marker={last_marker}
async def poll_updates(self):
    marker = await self._get_last_marker()
    while True:
        try:
            response = await self.client.get(
                f"{BASE_URL}/updates",
                params={"timeout": 30, "marker": marker},
                timeout=35,
            )
            data = response.json()
            for update in data.get("updates", []):
                await self._process_update(update)
            marker = data.get("marker", marker)
            await self._save_marker(marker)
        except Exception as e:
            logger.error("MAX polling error", error=str(e))
            await asyncio.sleep(30)  # Повтор через 30 секунд
```

### Типы обновлений MAX

```python
class MaxUpdateType(str, Enum):
    MESSAGE_CREATED = "message_created"
    MESSAGE_CALLBACK = "message_callback"
    BOT_STARTED = "bot_started"
    USER_ADDED = "user_added"
```

---

## Обработка интерактивных действий

```mermaid
sequenceDiagram
    participant C as Клиент (мессенджер)
    participant AD as Adapter
    participant NS as NotificationService
    participant DD as ActionDedup
    participant YC as YClients API
    participant DB as PostgreSQL

    C->>AD: Нажать кнопку "✅ Подтвердить"
    AD->>DD: Проверить дедупликацию\n(appointment_id, action, 30 сек)
    alt Дубликат
        DD-->>AD: Уже выполнено
        AD-->>C: Игнорировать
    else Новое действие
        DD-->>AD: OK
        AD->>DB: INSERT action_dedup
        AD->>NS: handle_action(confirm, appointment_id, client_id)
        NS->>YC: PATCH /appointments/{id}\n{status: "confirmed"}
        alt Успех
            YC-->>NS: 200 OK
            NS->>DB: UPDATE notification_log
            NS->>AD: Отправить подтверждение
            AD-->>C: "✅ Запись подтверждена!"
        else Ошибка YClients
            YC-->>NS: 4xx/5xx
            NS->>DB: INSERT audit_log (error)
            NS->>AD: Отправить сообщение об ошибке
            AD-->>C: "Ошибка. Позвоните в салон: {phone}"
        end
    end
```

---

## Конфигурация и переменные окружения

```bash
# .env.example

# YClients
YCLIENTS_API_TOKEN=your_yclients_token_here
YCLIENTS_COMPANY_ID=123456
YCLIENTS_WEBHOOK_SECRET=your_webhook_secret_here

# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# WhatsApp Business Cloud API
WHATSAPP_API_TOKEN=your_whatsapp_token_here
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_BUSINESS_ACCOUNT_ID=123456789012345
WHATSAPP_VERIFY_TOKEN=your_verify_token_here

# MAX Bot API
MAX_BOT_TOKEN=your_max_bot_token_here

# База данных
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/notifications_db
DB_POOL_MIN_SIZE=5
DB_POOL_MAX_SIZE=20

# Redis
REDIS_URL=redis://redis:6379/0

# AdminPanel
ADMIN_USERNAME=admin
ADMIN_PASSWORD=strong_password_here
ADMIN_JWT_SECRET=your_jwt_secret_here
ADMIN_JWT_EXPIRE_MINUTES=60

# Настройки системы
POLLING_INTERVAL_SECONDS=120
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO
ENVIRONMENT=production

# Безопасность
WEBHOOK_RATE_LIMIT=100/minute
```

---

## Docker Compose

```yaml
# docker-compose.yml
version: "3.9"

services:
  app:
    build:
      context: .
      dockerfile: docker/Dockerfile
      target: production
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: >
      sh -c "alembic upgrade head &&
             python -m app.main"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  celery_worker:
    build:
      context: .
      dockerfile: docker/Dockerfile
      target: production
    env_file: .env
    depends_on:
      - app
      - redis
      - postgres
    command: celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
    restart: unless-stopped

  celery_beat:
    build:
      context: .
      dockerfile: docker/Dockerfile
      target: production
    env_file: .env
    depends_on:
      - redis
      - postgres
    command: celery -A app.tasks.celery_app beat --loglevel=info
    restart: unless-stopped

  postgres:
    image: postgres:14-alpine
    environment:
      POSTGRES_DB: notifications_db
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d notifications_db"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

---

## Error Handling

### Стратегия обработки ошибок по компонентам

| Компонент | Тип ошибки | Действие |
|---|---|---|
| YClientsClient | HTTP 429 | Экспоненциальный backoff (1с → 60с) |
| YClientsClient | HTTP 5xx × 3 | Пауза 5 минут, лог ERROR |
| TelegramAdapter | 403 Forbidden | Деактивировать канал в ClientRegistry |
| TelegramAdapter | 429 Too Many Requests | Соблюдать `retry_after` из ответа |
| WhatsAppAdapter | Ошибка доставки | Лог в AuditLog, retry через Celery |
| WhatsAppAdapter | Номер не в WhatsApp | Деактивировать канал |
| MaxAdapter | API недоступен > 60с | Лог ERROR, повтор через 30с |
| RetryQueue | 4 неудачи подряд | Статус `failed` в AuditLog, стоп |
| TemplateEngine | Переменная отсутствует | Заменить пустой строкой, лог WARNING |
| WebhookHandler | Неверная подпись | HTTP 401, лог WARNING |
| NotificationService | Клиент не найден | Лог WARNING, пропустить |

### Идемпотентность

Каждая Celery-задача проверяет `task_id` в таблице `task_queue` перед выполнением. Если задача уже выполнена (`status = success`), повторное выполнение пропускается. Это предотвращает дублирование уведомлений при перезапуске воркеров.

### Дедупликация уведомлений

Перед отправкой `NotificationService` проверяет `notification_log` на наличие записи с тем же `(client_id, appointment_id, notification_type)` за последние 10 минут. При обнаружении дубликата уведомление пропускается с логом INFO.

---

## Testing Strategy

### Юнит-тесты (`tests/unit/`)

- `test_template_engine.py` — рендеринг шаблонов, валидация переменных, обработка отсутствующих переменных
- `test_dispatcher.py` — логика маршрутизации, тихий режим, фильтрация типов уведомлений
- `test_client_registry.py` — привязка/отвязка каналов, поиск по хешу телефона
- `test_rate_limiter.py` — token bucket алгоритм, соблюдение лимитов
- `test_security.py` — HMAC валидация подписи, хеширование телефонов

### Интеграционные тесты (`tests/integration/`)

- `test_webhook_handler.py` — обработка webhook с валидной/невалидной подписью
- `test_notification_flow.py` — полный цикл: событие → уведомление → лог
- `test_retry_queue.py` — retry-механизм с мок-ошибками адаптеров
- `test_admin_panel.py` — CRUD шаблонов, аутентификация, тестовая отправка

### Property-based тесты (`tests/property/`)

- `test_template_properties.py` — шаблон с любыми данными всегда рендерится без исключений
- `test_dedup_properties.py` — дедупликация корректна при любом порядке событий
- `test_retry_properties.py` — количество попыток никогда не превышает 4

### Тестовое окружение

```bash
# Запуск тестов
pytest tests/ -v --cov=app --cov-report=html

# Только юнит-тесты (без внешних зависимостей)
pytest tests/unit/ -v

# С интеграционными тестами (требует Docker)
docker-compose -f docker-compose.test.yml up --abort-on-container-exit
```

---

## Correctness Properties

### Property 1: Идемпотентность доставки

Повторное выполнение задачи с одним `task_id` не создаёт дублирующих записей в `notification_log` и не отправляет повторных сообщений.

**Validates: Requirements 9.5**

### Property 2: Ограничение попыток

Для любого уведомления количество попыток доставки не превышает 4. После 4 неудач статус всегда `failed`.

**Validates: Requirements 9.3, 9.4**

### Property 3: Дедупликация событий

Два одинаковых события (тот же `appointment_id` + `notification_type`) в течение 10 минут порождают ровно одно уведомление.

**Validates: Requirements 6.9**

### Property 4: Тихий режим

Уведомления типов, отличных от `in_progress`, никогда не отправляются в период тихого режима клиента — они откладываются до конца периода.

**Validates: Requirements 6.10, 2.7**

### Property 5: Безопасность токенов

Ни один API-токен не появляется в логах, ответах API или записях БД в открытом виде.

**Validates: Requirements 14.1, 1.8**

### Property 6: Целостность привязок

Один `yclients_client_id` может иметь не более одной активной привязки на каждый канал (`UNIQUE(client_id, channel)` в `client_channel_settings`).

**Validates: Requirements 2.4**
