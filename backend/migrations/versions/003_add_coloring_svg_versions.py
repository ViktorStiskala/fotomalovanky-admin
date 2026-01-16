"""Add coloring and SVG version tables.

Revision ID: 003
Revises: 002_add_payment_status_shipping_method
Create Date: 2026-01-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Define the enum type for image processing status
imageprocessingstatus_enum = postgresql.ENUM(
    "pending",
    "queued",
    "processing",
    "completed",
    "error",
    name="imageprocessingstatus",
    create_type=False,
)


def upgrade() -> None:
    # Create the PostgreSQL enum type
    imageprocessingstatus_enum.create(op.get_bind(), checkfirst=True)

    # Create coloring_versions table
    op.create_table(
        "coloring_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("status", imageprocessingstatus_enum, nullable=False, server_default="pending"),
        sa.Column("megapixels", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="4"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_coloring_versions_image_id", "coloring_versions", ["image_id"])

    # Create svg_versions table
    op.create_table(
        "svg_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coloring_version_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("status", imageprocessingstatus_enum, nullable=False, server_default="pending"),
        sa.Column("shape_stacking", sa.String(), nullable=False, server_default="stacked"),
        sa.Column("group_by", sa.String(), nullable=False, server_default="color"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["coloring_version_id"], ["coloring_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_svg_versions_coloring_version_id", "svg_versions", ["coloring_version_id"])

    # Add selected version columns to images table
    op.add_column(
        "images",
        sa.Column("selected_coloring_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "images",
        sa.Column("selected_svg_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_images_selected_coloring_id",
        "images",
        "coloring_versions",
        ["selected_coloring_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_images_selected_svg_id",
        "images",
        "svg_versions",
        ["selected_svg_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Remove foreign keys from images
    op.drop_constraint("fk_images_selected_svg_id", "images", type_="foreignkey")
    op.drop_constraint("fk_images_selected_coloring_id", "images", type_="foreignkey")

    # Remove columns from images
    op.drop_column("images", "selected_svg_id")
    op.drop_column("images", "selected_coloring_id")

    # Drop svg_versions table
    op.drop_index("ix_svg_versions_coloring_version_id", table_name="svg_versions")
    op.drop_table("svg_versions")

    # Drop coloring_versions table
    op.drop_index("ix_coloring_versions_image_id", table_name="coloring_versions")
    op.drop_table("coloring_versions")

    # Drop the PostgreSQL enum type
    imageprocessingstatus_enum.drop(op.get_bind(), checkfirst=True)
