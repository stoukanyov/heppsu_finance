"""bank connections (PSD2 / open banking съгласия и връзки към сметки)

Revision ID: e4b8d2f16a37
Revises: d7a1c9e35f24
Create Date: 2026-07-26 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4b8d2f16a37'
down_revision: Union[str, None] = 'd7a1c9e35f24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = ('PENDING', 'ACTIVE', 'EXPIRED', 'REVOKED')


def upgrade() -> None:
    op.create_table(
        'bank_connections',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('provider_code', sa.String(length=30), nullable=False),
        sa.Column('institution_id', sa.String(length=100), nullable=False),
        sa.Column('institution_name', sa.String(length=255), nullable=True),
        sa.Column('external_id', sa.String(length=100), nullable=False),
        sa.Column('status', sa.Enum(*_STATUSES, native_enum=False, length=20), nullable=False),
        sa.Column('consent_link', sa.String(length=1000), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bank_connections_company_id'), 'bank_connections', ['company_id'])
    op.create_index(op.f('ix_bank_connections_external_id'), 'bank_connections', ['external_id'])

    op.create_table(
        'bank_account_links',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('connection_id', sa.Uuid(), nullable=False),
        sa.Column('account_id', sa.Uuid(), nullable=False),
        sa.Column('external_account_id', sa.String(length=100), nullable=False),
        sa.Column('remote_iban', sa.String(length=34), nullable=True),
        sa.Column('remote_name', sa.String(length=255), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['bank_connections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['bank_accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'external_account_id', name='uq_bank_link_remote'),
    )
    op.create_index(op.f('ix_bank_account_links_company_id'), 'bank_account_links', ['company_id'])
    op.create_index(op.f('ix_bank_account_links_connection_id'), 'bank_account_links', ['connection_id'])
    op.create_index(op.f('ix_bank_account_links_account_id'), 'bank_account_links', ['account_id'])


def downgrade() -> None:
    op.drop_table('bank_account_links')
    op.drop_table('bank_connections')
