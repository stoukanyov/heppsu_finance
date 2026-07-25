"""document list indexes

Revision ID: c1a4f7b2d905
Revises: e9c3b6d1f875
Create Date: 2026-07-25 12:10:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c1a4f7b2d905'
down_revision: Union[str, None] = 'e9c3b6d1f875'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Индекси за листването с пагинация и търсене: скоуп по компания + подредба по
    # дата, филтър по статус и досието на контрагента.
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index(
            'ix_documents_company_created_at', ['company_id', 'created_at'], unique=False
        )
        batch_op.create_index(
            'ix_documents_company_status', ['company_id', 'status'], unique=False
        )
        batch_op.create_index(
            'ix_documents_counterparty_id', ['counterparty_id'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index('ix_documents_counterparty_id')
        batch_op.drop_index('ix_documents_company_status')
        batch_op.drop_index('ix_documents_company_created_at')
