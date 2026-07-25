"""vat refund procedures (чл. 92 ЗДДС)

Revision ID: b3d7f2e9c481
Revises: a1c5e8f3b7d2
Create Date: 2026-07-25 12:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d7f2e9c481'
down_revision: Union[str, None] = 'a1c5e8f3b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = (
    'CALCULATED', 'VAT_CREDIT_VALIDATED', 'DECLARED_IN_CELL_60', 'OFFSET_PERIOD_1',
    'OFFSET_PERIOD_2', 'READY_FOR_CELL_80', 'ACCELERATED_ELIGIBILITY_CONFIRMED',
    'USER_APPROVED', 'DECLARED_IN_CELL_81', 'DECLARED_IN_CELL_82',
    'SUBMITTED_FOR_REFUND', 'UNDER_NRA_CHECK', 'APPROVED', 'PARTIALLY_APPROVED',
    'REFUSED', 'OFFSET_BY_NRA', 'PAID', 'CLOSED',
)


def upgrade() -> None:
    op.create_table(
        'vat_refund_procedures',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('origin_period_id', sa.Uuid(), nullable=False),
        sa.Column('original_refund_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('amount_offset', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('remaining_refund', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('procedure_type', sa.Enum('STANDARD', 'ACCELERATED', 'INVESTMENT_PERMIT', name='refundproceduretype', native_enum=False, length=25), nullable=False),
        sa.Column('legal_basis', sa.String(length=120), nullable=False),
        sa.Column('status', sa.Enum(*_STATUSES, name='refundstatus', native_enum=False, length=40), nullable=False),
        sa.Column('declaration_cell', sa.String(length=2), nullable=True),
        sa.Column('first_offset_period_id', sa.Uuid(), nullable=True),
        sa.Column('second_offset_period_id', sa.Uuid(), nullable=True),
        sa.Column('zero_rate_ratio', sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column('accelerated_eligible', sa.Boolean(), nullable=False),
        sa.Column('user_approved_by_id', sa.Uuid(), nullable=True),
        sa.Column('user_approved_at', sa.DateTime(), nullable=True),
        sa.Column('submission_date', sa.Date(), nullable=True),
        sa.Column('submission_deadline', sa.Date(), nullable=True),
        sa.Column('expected_refund_deadline', sa.Date(), nullable=True),
        sa.Column('nra_check_status', sa.Enum('NONE', 'CHECK', 'AUDIT', 'SUSPENDED', 'COMPLETED', name='nracheckstatus', native_enum=False, length=15), nullable=False),
        sa.Column('offset_against_public_liabilities', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('amount_paid', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('nra_act_reference', sa.String(length=120), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['origin_period_id'], ['accounting_periods.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['first_offset_period_id'], ['accounting_periods.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['second_offset_period_id'], ['accounting_periods.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_approved_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'origin_period_id', name='uq_refund_company_origin'),
    )
    op.create_index('ix_vat_refund_procedures_company_id', 'vat_refund_procedures', ['company_id'], unique=False)
    op.create_index('ix_vat_refund_procedures_origin_period_id', 'vat_refund_procedures', ['origin_period_id'], unique=False)
    op.create_index('ix_vat_refund_procedures_status', 'vat_refund_procedures', ['status'], unique=False)

    op.create_table(
        'vat_refund_offsets',
        sa.Column('procedure_id', sa.Uuid(), nullable=False),
        sa.Column('period_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('vat_payable_in_period', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('payable_remaining', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('refund_remaining_after', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['procedure_id'], ['vat_refund_procedures.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'], ['accounting_periods.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('procedure_id', 'period_id', name='uq_refund_offset_procedure_period'),
    )
    op.create_index('ix_vat_refund_offsets_procedure_id', 'vat_refund_offsets', ['procedure_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_vat_refund_offsets_procedure_id', table_name='vat_refund_offsets')
    op.drop_table('vat_refund_offsets')
    op.drop_index('ix_vat_refund_procedures_status', table_name='vat_refund_procedures')
    op.drop_index('ix_vat_refund_procedures_origin_period_id', table_name='vat_refund_procedures')
    op.drop_index('ix_vat_refund_procedures_company_id', table_name='vat_refund_procedures')
    op.drop_table('vat_refund_procedures')
