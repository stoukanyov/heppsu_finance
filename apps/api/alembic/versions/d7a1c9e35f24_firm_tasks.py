"""firm tasks (задачи по клиент за счетоводна кантора)

Revision ID: d7a1c9e35f24
Revises: c3f8e5a41d92
Create Date: 2026-07-25 20:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7a1c9e35f24'
down_revision: Union[str, None] = 'c3f8e5a41d92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = ('OPEN', 'IN_PROGRESS', 'DONE', 'CANCELLED')


def upgrade() -> None:
    op.create_table(
        'firm_tasks',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', sa.Enum(*_STATUSES, native_enum=False, length=20), nullable=False),
        sa.Column('assignee_id', sa.Uuid(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('deadline_key', sa.String(length=100), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_firm_tasks_company_id'), 'firm_tasks', ['company_id'])
    op.create_index(op.f('ix_firm_tasks_assignee_id'), 'firm_tasks', ['assignee_id'])
    op.create_index(op.f('ix_firm_tasks_deadline_key'), 'firm_tasks', ['deadline_key'])


def downgrade() -> None:
    op.drop_table('firm_tasks')
