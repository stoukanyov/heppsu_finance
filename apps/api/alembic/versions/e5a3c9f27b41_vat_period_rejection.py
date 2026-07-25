"""vat period rejection

Revision ID: e5a3c9f27b41
Revises: d4e8b1c6a2f9
Create Date: 2026-07-25 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a3c9f27b41'
down_revision: Union[str, None] = 'd4e8b1c6a2f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vat_period_rejections',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('period_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('rejected_by_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'], ['accounting_periods.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['rejected_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vat_period_rejections_company_id', 'vat_period_rejections', ['company_id'], unique=False)
    op.create_index('ix_vat_period_rejections_period_id', 'vat_period_rejections', ['period_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_vat_period_rejections_period_id', table_name='vat_period_rejections')
    op.drop_index('ix_vat_period_rejections_company_id', table_name='vat_period_rejections')
    op.drop_table('vat_period_rejections')
