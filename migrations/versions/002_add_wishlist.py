"""add wishlist table

Revision ID: 002
Revises: 001
Create Date: 2026-05-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wishlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "product_id", name="wishlists_unique_user_product"),
    )


def downgrade() -> None:
    op.drop_table("wishlists")
