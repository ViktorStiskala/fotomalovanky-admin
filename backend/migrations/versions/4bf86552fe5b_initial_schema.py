"""initial_schema

Revision ID: 4bf86552fe5b
Revises:
Create Date: 2026-01-17 23:40:49.845648

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4bf86552fe5b"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums first
    op.execute(
        """
        CREATE TYPE coloringprocessingstatus AS ENUM (
            'pending', 'queued', 'processing', 'runpod_submitting',
            'runpod_submitted', 'runpod_queued', 'runpod_processing',
            'completed', 'error'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE svgprocessingstatus AS ENUM (
            'pending', 'queued', 'processing', 'vectorizer_processing',
            'completed', 'error'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE orderstatus AS ENUM (
            'pending', 'downloading', 'processing', 'ready_for_review', 'error'
        )
        """
    )

    # Create manual_order_sequence table
    op.create_table(
        "manual_order_sequence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create orders table (ULID as UUID)
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("order_number", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("shopify_id", sa.BigInteger(), nullable=True),
        sa.Column("shopify_order_number", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("customer_email", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("customer_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("payment_status", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("shipping_method", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "downloading", "processing", "ready_for_review", "error", name="orderstatus", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orders_order_number"), "orders", ["order_number"], unique=True)
    op.create_index(op.f("ix_orders_shopify_id"), "orders", ["shopify_id"], unique=True)
    op.create_index(op.f("ix_orders_shopify_order_number"), "orders", ["shopify_order_number"], unique=False)

    # Create line_items table
    op.create_table(
        "line_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("shopify_line_item_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("dedication", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("layout", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "position", name="uq_line_item_order_position"),
        sa.UniqueConstraint("shopify_line_item_id"),
    )
    op.create_index(op.f("ix_line_items_order_id"), "line_items", ["order_id"], unique=False)

    # Create images table (without FK constraints to versions initially)
    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("line_item_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("original_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("file_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selected_coloring_id", sa.Integer(), nullable=True),
        sa.Column("selected_svg_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["line_item_id"], ["line_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("line_item_id", "position", name="uq_image_line_item_position"),
    )
    op.create_index(op.f("ix_images_line_item_id"), "images", ["line_item_id"], unique=False)

    # Create coloring_versions table
    op.create_table(
        "coloring_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "queued",
                "processing",
                "runpod_submitting",
                "runpod_submitted",
                "runpod_queued",
                "runpod_processing",
                "completed",
                "error",
                name="coloringprocessingstatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("megapixels", sa.Float(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("image_id", "version", name="uq_coloring_version_image_version"),
    )
    op.create_index(op.f("ix_coloring_versions_image_id"), "coloring_versions", ["image_id"], unique=False)

    # Create svg_versions table
    op.create_table(
        "svg_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coloring_version_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "queued",
                "processing",
                "vectorizer_processing",
                "completed",
                "error",
                name="svgprocessingstatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("shape_stacking", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("group_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["coloring_version_id"], ["coloring_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coloring_version_id", "version", name="uq_svg_version_coloring_version"),
    )
    op.create_index(op.f("ix_svg_versions_coloring_version_id"), "svg_versions", ["coloring_version_id"], unique=False)

    # Now add the foreign key constraints from images to versions
    op.create_foreign_key(
        "fk_images_selected_coloring_id",
        "images",
        "coloring_versions",
        ["selected_coloring_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_images_selected_svg_id",
        "images",
        "svg_versions",
        ["selected_svg_id"],
        ["id"],
    )


def downgrade() -> None:
    # Drop foreign keys first
    op.drop_constraint("fk_images_selected_svg_id", "images", type_="foreignkey")
    op.drop_constraint("fk_images_selected_coloring_id", "images", type_="foreignkey")

    # Drop tables in reverse order
    op.drop_index(op.f("ix_svg_versions_coloring_version_id"), table_name="svg_versions")
    op.drop_table("svg_versions")

    op.drop_index(op.f("ix_coloring_versions_image_id"), table_name="coloring_versions")
    op.drop_table("coloring_versions")

    op.drop_index(op.f("ix_images_line_item_id"), table_name="images")
    op.drop_table("images")

    op.drop_index(op.f("ix_line_items_order_id"), table_name="line_items")
    op.drop_table("line_items")

    op.drop_index(op.f("ix_orders_shopify_order_number"), table_name="orders")
    op.drop_index(op.f("ix_orders_shopify_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_order_number"), table_name="orders")
    op.drop_table("orders")

    op.drop_table("manual_order_sequence")

    # Drop enums
    op.execute("DROP TYPE orderstatus")
    op.execute("DROP TYPE svgprocessingstatus")
    op.execute("DROP TYPE coloringprocessingstatus")
