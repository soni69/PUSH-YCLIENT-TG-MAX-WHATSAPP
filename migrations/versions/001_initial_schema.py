"""Initial schema — all tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── clients ──────────────────────────────────────────────────────────────
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("yclients_client_id", sa.String(64), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("whatsapp_phone_hash", sa.String(64), nullable=True),
        sa.Column("whatsapp_phone_enc", sa.String(32), nullable=True),
        sa.Column("max_user_id", sa.String(64), nullable=True),
        sa.Column("preferred_channel", sa.String(16), nullable=False, server_default="telegram"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("yclients_client_id"),
    )
    op.create_index("idx_clients_yclients_id", "clients", ["yclients_client_id"])
    op.create_index("idx_clients_telegram_id", "clients", ["telegram_id"])
    op.create_index("idx_clients_whatsapp_hash", "clients", ["whatsapp_phone_hash"])

    # ── client_channel_settings ───────────────────────────────────────────────
    op.create_table(
        "client_channel_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "notification_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'["all"]\'::jsonb'),
        ),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "channel", name="uq_client_channel"),
    )
    op.create_index(
        "idx_channel_settings_client_id", "client_channel_settings", ["client_id"]
    )

    # ── notification_templates ────────────────────────────────────────────────
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("notification_type", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default="ru"),
        sa.Column("subject", sa.String(256), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notification_type",
            "channel",
            "language",
            name="uq_template_type_channel_lang",
        ),
    )

    # ── notification_log ──────────────────────────────────────────────────────
    op.create_table(
        "notification_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("notification_type", sa.String(64), nullable=False),
        sa.Column("appointment_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("message_id", sa.String(128), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_notif_log_client_id", "notification_log", ["client_id"])
    op.create_index("idx_notif_log_appointment_id", "notification_log", ["appointment_id"])
    op.create_index("idx_notif_log_sent_at", "notification_log", ["sent_at"])
    op.create_index("idx_notif_log_status", "notification_log", ["status"])

    # ── scheduled_reminders ───────────────────────────────────────────────────
    op.create_table(
        "scheduled_reminders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("appointment_id", sa.String(64), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("reminder_type", sa.String(32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("celery_task_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "appointment_id", "reminder_type", name="uq_reminder_appointment_type"
        ),
    )
    op.create_index("idx_reminders_scheduled_at", "scheduled_reminders", ["scheduled_at"])
    op.create_index("idx_reminders_status", "scheduled_reminders", ["status"])

    # ── task_queue ────────────────────────────────────────────────────────────
    op.create_table(
        "task_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("idx_task_queue_status", "task_queue", ["status"])
    op.create_index("idx_task_queue_next_retry", "task_queue", ["next_retry_at"])

    # ── action_dedup ──────────────────────────────────────────────────────────
    op.create_table(
        "action_dedup",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("appointment_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_dedup_appointment_action",
        "action_dedup",
        ["appointment_id", "action", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("action_dedup")
    op.drop_table("task_queue")
    op.drop_table("scheduled_reminders")
    op.drop_table("notification_log")
    op.drop_table("notification_templates")
    op.drop_table("client_channel_settings")
    op.drop_table("clients")
