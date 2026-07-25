"""deadline filings (отметки „подадено“ за срокове)

Revision ID: b4c8d1e60932
Revises: a9e2f4c7b108
Create Date: 2026-07-25 19:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b4c8d1e60932'
down_revision: Union[str, None] = 'a9e2f4c7b108'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'deadline_filings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('filed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('filed_by_id', sa.Uuid(), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['filed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        # В базата, а не само в кода: две едновременни заявки от два телефона
        # иначе минават и се получават два реда за един срок.
        sa.UniqueConstraint('company_id', 'key', name='uq_deadline_filing'),
    )
    op.create_index('ix_deadline_filings_company_id', 'deadline_filings', ['company_id'])


def downgrade() -> None:
    op.drop_index('ix_deadline_filings_company_id', table_name='deadline_filings')
    op.drop_table('deadline_filings')
