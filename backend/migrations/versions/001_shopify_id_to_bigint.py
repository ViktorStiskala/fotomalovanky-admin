"""Change shopify_id columns to BIGINT.

Revision ID: 001
Revises:
Create Date: 2026-01-05

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Change orders.shopify_id from INTEGER to BIGINT
    op.alter_column(
        "orders",
        "shopify_id",
        existing_type=sa.INTEGER(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    # Change line_items.shopify_line_item_id from INTEGER to BIGINT
    op.alter_column(
        "line_items",
        "shopify_line_item_id",
        existing_type=sa.INTEGER(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Revert line_items.shopify_line_item_id back to INTEGER
    op.alter_column(
        "line_items",
        "shopify_line_item_id",
        existing_type=sa.BigInteger(),
        type_=sa.INTEGER(),
        existing_nullable=False,
    )

    # Revert orders.shopify_id back to INTEGER
    op.alter_column(
        "orders",
        "shopify_id",
        existing_type=sa.BigInteger(),
        type_=sa.INTEGER(),
        existing_nullable=False,
    )
