"""стойности по подразбиране за created_at/updated_at

Поправя два пропуска в `a9e2f4c7b108` (crash_reports) и `b4c8d1e60932`
(deadline_filings): колоните са създадени `NOT NULL`, но **без**
`server_default`. Моделите носят `server_default=func.now()` през
`TimestampMixin`, затова на dev машина всичко работи — там схемата се вдига с
`create_all` от моделите. На PostgreSQL схемата идва от миграциите и всеки
INSERT без изрична стойност се проваля с нарушение на NOT NULL.

Открито срещу разгърнатата среда: `POST /mobile/crash` връщаше 500, докато
локално минаваше. Същият дефект щеше да удари и отмятането на срок.

Revision ID: d5b8e3a91c47
Revises: b4c8d1e60932
Create Date: 2026-07-26 10:15:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd5b8e3a91c47'
down_revision: Union[str, None] = 'b4c8d1e60932'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('crash_reports', 'deadline_filings')
_NOW = sa.text('CURRENT_TIMESTAMP')


def upgrade() -> None:
    # `batch_alter_table` заради SQLite: той не поддържа ALTER COLUMN и
    # Alembic пресъздава таблицата. На PostgreSQL е обикновен ALTER.
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column in ('created_at', 'updated_at'):
                batch_op.alter_column(
                    column,
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    server_default=_NOW,
                )


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column in ('created_at', 'updated_at'):
                batch_op.alter_column(
                    column,
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    server_default=None,
                )
