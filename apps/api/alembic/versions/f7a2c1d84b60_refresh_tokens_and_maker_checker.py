"""refresh tokens with rotation + maker-checker policy

Revision ID: f7a2c1d84b60
Revises: c1a4f7b2d905
Create Date: 2026-07-25 15:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f7a2c1d84b60'
down_revision: Union[str, None] = 'c1a4f7b2d905'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Refresh токени: непрозрачни низове, пазени само като SHA-256 хеш ----
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        # Семейство = една верига от ротации; отменя се наведнъж при кражба.
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('parent_id', sa.Uuid(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.String(length=20), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('client_ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['refresh_tokens.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(
        'ix_refresh_tokens_user_family', 'refresh_tokens', ['user_id', 'family_id'], unique=False
    )

    # ---- Maker-checker на ниво компания ----
    # NULL = дружеството не е решавало → важи глобалното MAKER_CHECKER_ENABLED (False).
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('maker_checker_enabled', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_column('maker_checker_enabled')

    op.drop_index('ix_refresh_tokens_user_family', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
