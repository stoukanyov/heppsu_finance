"""crash reports (отчети за сривове от мобилния клиент)

Revision ID: a9e2f4c7b108
Revises: f7a2c1d84b60
Create Date: 2026-07-25 18:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a9e2f4c7b108'
down_revision: Union[str, None] = 'f7a2c1d84b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crash_reports',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        # Nullable: сривът може да е преди вход или преди избор на компания.
        sa.Column('company_id', sa.Uuid(), nullable=True),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('app_version', sa.String(length=40), nullable=False),
        sa.Column('build_number', sa.String(length=40), nullable=True),
        sa.Column('os_version', sa.String(length=60), nullable=True),
        sa.Column('device_model', sa.String(length=80), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_crash_reports_company_id', 'crash_reports', ['company_id'])
    op.create_index('ix_crash_reports_user_id', 'crash_reports', ['user_id'])
    # Триажът върви по отпечатък — един дефект от много устройства е един ред.
    op.create_index('ix_crash_reports_fingerprint', 'crash_reports', ['fingerprint'])


def downgrade() -> None:
    op.drop_index('ix_crash_reports_fingerprint', table_name='crash_reports')
    op.drop_index('ix_crash_reports_user_id', table_name='crash_reports')
    op.drop_index('ix_crash_reports_company_id', table_name='crash_reports')
    op.drop_table('crash_reports')
