"""add discount_code column to orders

Revision ID: 003
Revises: 002
Create Date: 2024-01-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: str = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("discount_code", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "discount_code")
