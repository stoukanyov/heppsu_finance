"""Оферти — регистър на предложенията към клиенти

Revision ID: f2c7a94e81b3
Revises: ffdb0650271c
Create Date: 2026-10-26

Само добавя двете таблици; нищо съществуващо не се пипа. `created_at` и
`updated_at` носят server_default — иначе първият INSERT на PostgreSQL пада,
защото приложението не ги подава (виж tests/test_migrations_schema.py).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2c7a94e81b3"
down_revision: str | None = "ffdb0650271c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("counterparty_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["counterparty_id"], ["counterparties.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "number", name="uq_offer_company_number"),
    )
    op.create_index("ix_offers_company_id", "offers", ["company_id"])
    op.create_index("ix_offers_counterparty_id", "offers", ["counterparty_id"])
    op.create_index("ix_offers_valid_until", "offers", ["valid_until"])

    op.create_table(
        "offer_lines",
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("line_net", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_offer_lines_offer_id", "offer_lines", ["offer_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_lines_offer_id", table_name="offer_lines")
    op.drop_table("offer_lines")
    op.drop_index("ix_offers_valid_until", table_name="offers")
    op.drop_index("ix_offers_counterparty_id", table_name="offers")
    op.drop_index("ix_offers_company_id", table_name="offers")
    op.drop_table("offers")
