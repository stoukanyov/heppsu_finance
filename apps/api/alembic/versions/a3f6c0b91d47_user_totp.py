"""Двуфакторна автентикация — тайната на потребителя и резервните кодове

Revision ID: a3f6c0b91d47
Revises: f2c7a94e81b3
Create Date: 2026-10-26

Само добавя две таблици; нищо съществуващо не се пипа и 2FA е изключена за
всички, докато всеки сам не я включи. `created_at` и `updated_at` носят
server_default — иначе първият INSERT на PostgreSQL пада, защото приложението
не ги подава (виж tests/test_migrations_schema.py).

`last_counter` е BigInteger: броячът е unix време / 30 и минава 2^31 през
2038 г., а `integer` на PostgreSQL е точно 32-битов.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f6c0b91d47"
down_revision: str | None = "f2c7a94e81b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_totp",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_counter", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Един ред на потребител — вторият фактор е един, не колекция.
        sa.UniqueConstraint("user_id", name="uq_user_totp_user"),
    )

    op.create_table(
        "totp_recovery_codes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_totp_recovery_codes_user_id", "totp_recovery_codes", ["user_id"])
    # Проверката при вход търси точно по двойката „чий код“ + „кой код“.
    op.create_index("ix_totp_recovery_user_hash", "totp_recovery_codes", ["user_id", "code_hash"])


def downgrade() -> None:
    op.drop_index("ix_totp_recovery_user_hash", table_name="totp_recovery_codes")
    op.drop_index("ix_totp_recovery_codes_user_id", table_name="totp_recovery_codes")
    op.drop_table("totp_recovery_codes")
    op.drop_table("user_totp")
