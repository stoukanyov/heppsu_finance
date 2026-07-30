"""Брояч на неуспешните опити за вход — обща таблица вместо памет на процеса

Revision ID: b9d4f1a76c53
Revises: e4b8d2f16a37
Create Date: 2026-07-30

Само добавя таблица и индекси; нищо съществуващо не се пипа.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9d4f1a76c53"
down_revision: str | None = "e4b8d2f16a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_throttle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.Float(), nullable=False),
        # Успешният вход маркира реда, вместо да го трие: праговете по акаунт спират
        # да го броят, а този по IP продължава. Триенето връщаше на нападателя
        # квотата му, щом жертвите влязат нормално.
        sa.Column("cleared_at", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # По един индекс за всеки от трите прага — проверката при вход прави точно
    # три запитвания и всяко от тях трябва да е по индекс.
    op.create_index(
        "ix_auth_throttle_pair",
        "auth_throttle_events",
        ["scope", "client_ip", "subject", "occurred_at"],
    )
    op.create_index(
        "ix_auth_throttle_subject", "auth_throttle_events", ["scope", "subject", "occurred_at"]
    )
    op.create_index(
        "ix_auth_throttle_ip", "auth_throttle_events", ["scope", "client_ip", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_throttle_ip", table_name="auth_throttle_events")
    op.drop_index("ix_auth_throttle_subject", table_name="auth_throttle_events")
    op.drop_index("ix_auth_throttle_pair", table_name="auth_throttle_events")
    op.drop_table("auth_throttle_events")
