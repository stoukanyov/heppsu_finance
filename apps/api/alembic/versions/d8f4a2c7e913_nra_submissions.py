"""nra submissions (пакети за НАП и разписки)

Revision ID: d8f4a2c7e913
Revises: b3d7f2e9c481
Create Date: 2026-07-25 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8f4a2c7e913'
down_revision: Union[str, None] = 'b3d7f2e9c481'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = ('VAT_RETURN', 'INCOME_REPORT_73', 'SAFT', 'OTHER')
_STATUSES = (
    'PREPARED', 'DOWNLOADED', 'SUBMITTED_EXTERNALLY', 'RECEIPT_IMPORTED',
    'ACCEPTED', 'REJECTED', 'CANCELLED',
)


def upgrade() -> None:
    op.create_table(
        'nra_submissions',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('period_id', sa.Uuid(), nullable=True),
        sa.Column('period_code', sa.String(length=10), nullable=False),
        sa.Column('kind', sa.Enum(*_KINDS, name='submissionkind', native_enum=False, length=25), nullable=False),
        sa.Column('status', sa.Enum(*_STATUSES, name='submissionstatus', native_enum=False, length=25), nullable=False),
        sa.Column('provider_code', sa.String(length=40), nullable=False),
        sa.Column('package_document_id', sa.Uuid(), nullable=True),
        sa.Column('package_filename', sa.String(length=255), nullable=False),
        sa.Column('package_sha256', sa.String(length=64), nullable=False),
        sa.Column('package_size', sa.Integer(), nullable=False),
        sa.Column('package_contents', sa.String(length=500), nullable=True),
        sa.Column('submission_deadline', sa.Date(), nullable=True),
        sa.Column('submitted_at', sa.Date(), nullable=True),
        sa.Column('receipt_document_id', sa.Uuid(), nullable=True),
        sa.Column('receipt_number', sa.String(length=120), nullable=True),
        sa.Column('receipt_date', sa.Date(), nullable=True),
        sa.Column('receipt_imported_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('prepared_by_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'], ['accounting_periods.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['package_document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['receipt_document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['prepared_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_nra_submissions_company_id', 'nra_submissions', ['company_id'], unique=False)
    op.create_index('ix_nra_submissions_period_id', 'nra_submissions', ['period_id'], unique=False)
    op.create_index('ix_nra_submissions_status', 'nra_submissions', ['status'], unique=False)
    op.create_index('ix_nra_submissions_package_sha256', 'nra_submissions', ['package_sha256'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_nra_submissions_package_sha256', table_name='nra_submissions')
    op.drop_index('ix_nra_submissions_status', table_name='nra_submissions')
    op.drop_index('ix_nra_submissions_period_id', table_name='nra_submissions')
    op.drop_index('ix_nra_submissions_company_id', table_name='nra_submissions')
    op.drop_table('nra_submissions')
