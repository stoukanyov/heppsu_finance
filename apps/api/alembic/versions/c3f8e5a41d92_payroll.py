"""payroll (ТРЗ: служители, договори, осигурителни параметри, ведомости)

Revision ID: c3f8e5a41d92
Revises: f7a2c1d84b60
Create Date: 2026-07-25 16:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3f8e5a41d92'
down_revision: Union[str, None] = 'f7a2c1d84b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONTRACT_TYPES = ('PERMANENT', 'FIXED_TERM', 'ADDITIONAL', 'MANAGEMENT')
_CONTRACT_STATUSES = ('ACTIVE', 'TERMINATED')
_CONTRIBUTION_BASES = ('INSURANCE_INCOME', 'GROSS')
_ABSENCE_TYPES = ('PAID_LEAVE', 'UNPAID_LEAVE', 'SICK_EMPLOYER', 'SICK_FUND')
_RUN_STATUSES = ('DRAFT', 'CALCULATED', 'APPROVED', 'POSTED', 'CANCELLED')

_MONEY = sa.Numeric(18, 2)
_PERCENT = sa.Numeric(9, 4)


def upgrade() -> None:
    op.create_table(
        'payroll_rate_sets',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('income_tax_percent', _PERCENT, nullable=False),
        sa.Column('max_insurance_income', _MONEY, nullable=True),
        sa.Column('default_min_insurance_income', _MONEY, nullable=False),
        sa.Column('seniority_percent_per_year', _PERCENT, nullable=False),
        sa.Column('sick_employer_days', sa.Integer(), nullable=False),
        sa.Column('sick_employer_percent', _PERCENT, nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('gl_salary_expense_account_id', sa.Uuid(), nullable=True),
        sa.Column('gl_salary_payable_account_id', sa.Uuid(), nullable=True),
        sa.Column('gl_income_tax_account_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['gl_salary_expense_account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['gl_salary_payable_account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['gl_income_tax_account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_rate_sets_company_id'), 'payroll_rate_sets', ['company_id'])

    op.create_table(
        'payroll_contribution_rates',
        sa.Column('rate_set_id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('employee_percent', _PERCENT, nullable=False),
        sa.Column('employer_percent', _PERCENT, nullable=False),
        sa.Column('base', sa.Enum(*_CONTRIBUTION_BASES, native_enum=False, length=20), nullable=False),
        sa.Column('reduces_taxable_income', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('gl_expense_account_id', sa.Uuid(), nullable=True),
        sa.Column('gl_liability_account_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['rate_set_id'], ['payroll_rate_sets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['gl_expense_account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['gl_liability_account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rate_set_id', 'code', name='uq_payroll_contrib_code'),
    )
    op.create_index(op.f('ix_payroll_contribution_rates_rate_set_id'), 'payroll_contribution_rates', ['rate_set_id'])

    op.create_table(
        'employees',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('first_name', sa.String(length=80), nullable=False),
        sa.Column('middle_name', sa.String(length=80), nullable=True),
        sa.Column('last_name', sa.String(length=80), nullable=False),
        sa.Column('national_id', sa.String(length=20), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('iban', sa.String(length=34), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'national_id', name='uq_employee_company_national_id'),
    )
    op.create_index(op.f('ix_employees_company_id'), 'employees', ['company_id'])

    op.create_table(
        'employment_contracts',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('number', sa.String(length=50), nullable=False),
        sa.Column('contract_type', sa.Enum(*_CONTRACT_TYPES, native_enum=False, length=20), nullable=False),
        sa.Column('position', sa.String(length=160), nullable=False),
        sa.Column('nkpd_code', sa.String(length=20), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('termination_date', sa.Date(), nullable=True),
        sa.Column('base_salary', _MONEY, nullable=False),
        sa.Column('hours_per_day', sa.Numeric(5, 2), nullable=False),
        sa.Column('seniority_years_at_start', sa.Numeric(6, 2), nullable=False),
        sa.Column('min_insurance_income', _MONEY, nullable=True),
        sa.Column('paid_leave_days_per_year', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum(*_CONTRACT_STATUSES, native_enum=False, length=20), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'number', name='uq_contract_company_number'),
    )
    op.create_index(op.f('ix_employment_contracts_company_id'), 'employment_contracts', ['company_id'])
    op.create_index(op.f('ix_employment_contracts_employee_id'), 'employment_contracts', ['employee_id'])

    op.create_table(
        'payroll_absences',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=False),
        sa.Column('absence_type', sa.Enum(*_ABSENCE_TYPES, native_enum=False, length=20), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contract_id'], ['employment_contracts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_absences_company_id'), 'payroll_absences', ['company_id'])
    op.create_index(op.f('ix_payroll_absences_contract_id'), 'payroll_absences', ['contract_id'])

    op.create_table(
        'payroll_runs',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('rate_set_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.Enum(*_RUN_STATUSES, native_enum=False, length=20), nullable=False),
        sa.Column('working_days', sa.Integer(), nullable=False),
        sa.Column('total_gross', _MONEY, nullable=False),
        sa.Column('total_employee_contributions', _MONEY, nullable=False),
        sa.Column('total_employer_contributions', _MONEY, nullable=False),
        sa.Column('total_income_tax', _MONEY, nullable=False),
        sa.Column('total_net', _MONEY, nullable=False),
        sa.Column('journal_entry_id', sa.Uuid(), nullable=True),
        sa.Column('approved_by_id', sa.Uuid(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rate_set_id'], ['payroll_rate_sets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'year', 'month', name='uq_payroll_run_period'),
    )
    op.create_index(op.f('ix_payroll_runs_company_id'), 'payroll_runs', ['company_id'])

    op.create_table(
        'payroll_lines',
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('contract_id', sa.Uuid(), nullable=False),
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('employee_name', sa.String(length=255), nullable=False),
        sa.Column('national_id', sa.String(length=20), nullable=False),
        sa.Column('position', sa.String(length=160), nullable=False),
        sa.Column('working_days', sa.Integer(), nullable=False),
        sa.Column('worked_days', sa.Integer(), nullable=False),
        sa.Column('paid_leave_days', sa.Integer(), nullable=False),
        sa.Column('unpaid_leave_days', sa.Integer(), nullable=False),
        sa.Column('sick_employer_days', sa.Integer(), nullable=False),
        sa.Column('sick_fund_days', sa.Integer(), nullable=False),
        sa.Column('base_amount', _MONEY, nullable=False),
        sa.Column('seniority_amount', _MONEY, nullable=False),
        sa.Column('additional_amount', _MONEY, nullable=False),
        sa.Column('sick_employer_amount', _MONEY, nullable=False),
        sa.Column('gross_amount', _MONEY, nullable=False),
        sa.Column('insurance_income', _MONEY, nullable=False),
        sa.Column('employee_contributions', _MONEY, nullable=False),
        sa.Column('employer_contributions', _MONEY, nullable=False),
        sa.Column('taxable_income', _MONEY, nullable=False),
        sa.Column('tax_relief', _MONEY, nullable=False),
        sa.Column('income_tax', _MONEY, nullable=False),
        sa.Column('other_deductions', _MONEY, nullable=False),
        sa.Column('net_amount', _MONEY, nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['payroll_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contract_id'], ['employment_contracts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'contract_id', name='uq_payroll_line_run_contract'),
    )
    op.create_index(op.f('ix_payroll_lines_run_id'), 'payroll_lines', ['run_id'])

    op.create_table(
        'payroll_line_contributions',
        sa.Column('line_id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('base_amount', _MONEY, nullable=False),
        sa.Column('employee_amount', _MONEY, nullable=False),
        sa.Column('employer_amount', _MONEY, nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['line_id'], ['payroll_lines.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payroll_line_contributions_line_id'), 'payroll_line_contributions', ['line_id'])


def downgrade() -> None:
    op.drop_table('payroll_line_contributions')
    op.drop_table('payroll_lines')
    op.drop_table('payroll_runs')
    op.drop_table('payroll_absences')
    op.drop_table('employment_contracts')
    op.drop_table('employees')
    op.drop_table('payroll_contribution_rates')
    op.drop_table('payroll_rate_sets')
