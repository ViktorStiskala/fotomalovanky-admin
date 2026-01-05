"""Add payment_status and shipping_method to orders.

Revision ID: 002
Revises: 001
Create Date: 2026-01-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_status", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("shipping_method", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "shipping_method")
    op.drop_column("orders", "payment_status")
