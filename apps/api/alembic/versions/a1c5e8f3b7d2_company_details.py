"""company details (реквизити на дружеството)

Revision ID: a1c5e8f3b7d2
Revises: f2b7c4d9a1e6
Create Date: 2026-07-25 11:25:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c5e8f3b7d2'
down_revision: Union[str, None] = 'f2b7c4d9a1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ('name_latin', sa.String(length=255)),
    ('legal_form', sa.String(length=50)),
    ('address_city', sa.String(length=120)),
    ('address_postcode', sa.String(length=10)),
    ('address_line', sa.String(length=255)),
    ('manager_name', sa.String(length=255)),
    ('owner_name', sa.String(length=255)),
    ('phone', sa.String(length=30)),
    ('email', sa.String(length=255)),
    ('activity', sa.String(length=500)),
    ('vat_registration_date', sa.Date()),
    ('incorporation_date', sa.Date()),
    ('share_capital', sa.Numeric(precision=18, scale=2)),
)


def upgrade() -> None:
    with op.batch_alter_table('companies', schema=None) as batch_op:
        for name, type_ in _COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('companies', schema=None) as batch_op:
        for name, _type in reversed(_COLUMNS):
            batch_op.drop_column(name)
