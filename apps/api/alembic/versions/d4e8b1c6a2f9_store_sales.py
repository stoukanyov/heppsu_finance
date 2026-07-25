"""store sales

Revision ID: d4e8b1c6a2f9
Revises: c7f1a9d3e5b2
Create Date: 2026-07-25 09:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e8b1c6a2f9'
down_revision: Union[str, None] = 'c7f1a9d3e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'store_sales',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sa.Enum('APP_STORE', 'GOOGLE_PLAY', name='storeplatform', native_enum=False, length=20), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('app_name', sa.String(length=200), nullable=False),
        sa.Column('app_identifier', sa.String(length=200), nullable=False),
        sa.Column('product_type', sa.Enum('APP', 'IN_APP', 'SUBSCRIPTION', name='storeproducttype', native_enum=False, length=20), nullable=False),
        sa.Column('country', sa.String(length=2), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False),
        sa.Column('proceeds', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('source_ref', sa.String(length=64), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'source_ref', name='uq_store_sale_company_ref'),
    )
    op.create_index('ix_store_sales_company_id', 'store_sales', ['company_id'], unique=False)
    op.create_index('ix_store_sales_platform', 'store_sales', ['platform'], unique=False)
    op.create_index('ix_store_sales_report_date', 'store_sales', ['report_date'], unique=False)
    op.create_index('ix_store_sales_country', 'store_sales', ['country'], unique=False)
    op.create_index('ix_store_sales_source_ref', 'store_sales', ['source_ref'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_store_sales_source_ref', table_name='store_sales')
    op.drop_index('ix_store_sales_country', table_name='store_sales')
    op.drop_index('ix_store_sales_report_date', table_name='store_sales')
    op.drop_index('ix_store_sales_platform', table_name='store_sales')
    op.drop_index('ix_store_sales_company_id', table_name='store_sales')
    op.drop_table('store_sales')
