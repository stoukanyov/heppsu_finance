"""rbac roles (гъвкави роли с права)

Revision ID: e9c3b6d1f875
Revises: d8f4a2c7e913
Create Date: 2026-07-25 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9c3b6d1f875'
down_revision: Union[str, None] = 'd8f4a2c7e913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'roles',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('permissions', sa.JSON(), nullable=False),
        sa.Column('can_use_mobile', sa.Boolean(), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'code', name='uq_role_company_code'),
    )
    op.create_index('ix_roles_company_id', 'roles', ['company_id'], unique=False)
    op.create_index('ix_roles_code', 'roles', ['code'], unique=False)

    with op.batch_alter_table('memberships', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            'fk_memberships_role_id', 'roles', ['role_id'], ['id'], ondelete='SET NULL'
        )
    op.create_index('ix_memberships_role_id', 'memberships', ['role_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_memberships_role_id', table_name='memberships')
    with op.batch_alter_table('memberships', schema=None) as batch_op:
        batch_op.drop_constraint('fk_memberships_role_id', type_='foreignkey')
        batch_op.drop_column('role_id')
    op.drop_index('ix_roles_code', table_name='roles')
    op.drop_index('ix_roles_company_id', table_name='roles')
    op.drop_table('roles')
