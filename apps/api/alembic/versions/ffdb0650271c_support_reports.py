"""Доклади от потребителите (дефект, инцидент, предложение) → Control Center

Revision ID: ffdb0650271c
Revises: b9d4f1a76c53
Create Date: 2026-10-11

Само добавя таблица и индекси; нищо съществуващо не се пипа.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ffdb0650271c"
down_revision: str | None = "b9d4f1a76c53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # SET NULL: изтриването на акаунт/дружество не трие следата от сигнала.
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("page", sa.String(length=200), nullable=True),
        sa.Column("submitter_ip", sa.String(length=64), nullable=True),
        sa.Column("forward_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("reference", sa.String(length=32), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_reports_user_id", "support_reports", ["user_id"])
    op.create_index("ix_support_reports_company_id", "support_reports", ["company_id"])
    # Фоновият цикъл пита „чакащите, чийто ред е дошъл“ — по индекс.
    op.create_index("ix_support_reports_due", "support_reports", ["forward_status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_support_reports_due", table_name="support_reports")
    op.drop_index("ix_support_reports_company_id", table_name="support_reports")
    op.drop_index("ix_support_reports_user_id", table_name="support_reports")
    op.drop_table("support_reports")
