"""vat period closing

Revision ID: c7f1a9d3e5b2
Revises: 3b82295f4da8
Create Date: 2026-07-25 09:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7f1a9d3e5b2'
down_revision: Union[str, None] = '3b82295f4da8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vat_period_closings',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('period_id', sa.Uuid(), nullable=False),
        sa.Column('journal_entry_id', sa.Uuid(), nullable=True),
        sa.Column('output_vat', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('input_vat', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('net_payable', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('net_refundable', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('closed_by_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'], ['accounting_periods.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['closed_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'period_id', name='uq_vat_closing_company_period'),
    )
    op.create_index('ix_vat_period_closings_company_id', 'vat_period_closings', ['company_id'], unique=False)
    op.create_index('ix_vat_period_closings_period_id', 'vat_period_closings', ['period_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_vat_period_closings_period_id', table_name='vat_period_closings')
    op.drop_index('ix_vat_period_closings_company_id', table_name='vat_period_closings')
    op.drop_table('vat_period_closings')
