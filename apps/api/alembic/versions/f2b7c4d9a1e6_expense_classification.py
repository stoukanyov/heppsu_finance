"""expense classification (AI данъчно третиране на разход)

Revision ID: f2b7c4d9a1e6
Revises: e5a3c9f27b41
Create Date: 2026-07-25 11:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2b7c4d9a1e6'
down_revision: Union[str, None] = 'e5a3c9f27b41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'expense_classifications',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('document_id', sa.Uuid(), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('account_code', sa.String(length=20), nullable=False),
        sa.Column('account_rationale', sa.String(length=1000), nullable=True),
        sa.Column('is_deductible', sa.Boolean(), nullable=False),
        sa.Column('deductible_ratio', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('tax_rationale', sa.String(length=1000), nullable=False),
        sa.Column('vat_credit', sa.String(length=10), nullable=False),
        sa.Column('vat_rationale', sa.String(length=1000), nullable=True),
        sa.Column('expense_category', sa.String(length=120), nullable=True),
        sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column('warnings', sa.JSON(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_expense_classifications_company_id', 'expense_classifications', ['company_id'], unique=False)
    op.create_index('ix_expense_classifications_document_id', 'expense_classifications', ['document_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_expense_classifications_document_id', table_name='expense_classifications')
    op.drop_index('ix_expense_classifications_company_id', table_name='expense_classifications')
    op.drop_table('expense_classifications')
