"""add payments table

Revision ID: 003
Revises: 002
Create Date: 2026-05-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.Text(), nullable=False, server_default='EUR'),
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('provider_ref', sa.Text()),
        sa.Column('paid_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
    )


def downgrade() -> None:
    op.drop_table('payments')
