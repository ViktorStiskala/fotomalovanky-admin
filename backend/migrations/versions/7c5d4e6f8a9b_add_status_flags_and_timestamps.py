"""Add new status values, timestamps, and image_id to svg_versions

Revision ID: 7c5d4e6f8a9b
Revises: 59d0e8a1b461
Create Date: 2026-01-19 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c5d4e6f8a9b"
down_revision: str | None = "59d0e8a1b461"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new enum values to coloringprocessingstatus
    # PostgreSQL requires using raw SQL for adding enum values
    op.execute("ALTER TYPE coloringprocessingstatus ADD VALUE IF NOT EXISTS 'storage_upload'")
    op.execute("ALTER TYPE coloringprocessingstatus ADD VALUE IF NOT EXISTS 'runpod_completed'")
    op.execute("ALTER TYPE coloringprocessingstatus ADD VALUE IF NOT EXISTS 'runpod_cancelled'")

    # Add new enum values to svgprocessingstatus
    op.execute("ALTER TYPE svgprocessingstatus ADD VALUE IF NOT EXISTS 'storage_upload'")
    op.execute("ALTER TYPE svgprocessingstatus ADD VALUE IF NOT EXISTS 'vectorizer_completed'")

    # Add timestamp columns to coloring_versions
    op.add_column(
        "coloring_versions", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "coloring_versions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Add timestamp columns to svg_versions
    op.add_column(
        "svg_versions", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "svg_versions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )

    # === SCHEMA CHANGE: Add image_id to svg_versions ===
    # This enables direct Image queries without joining through ColoringVersion

    # 1. Add column (nullable first)
    op.add_column("svg_versions", sa.Column("image_id", sa.Integer(), nullable=True))

    # 2. Populate from existing data
    op.execute("""
        UPDATE svg_versions sv
        SET image_id = cv.image_id
        FROM coloring_versions cv
        WHERE sv.coloring_version_id = cv.id
    """)

    # 3. Make NOT NULL + add FK/index
    op.alter_column("svg_versions", "image_id", nullable=False)
    op.create_foreign_key(
        "fk_svg_versions_image_id", "svg_versions", "images", ["image_id"], ["id"]
    )
    op.create_index("ix_svg_versions_image_id", "svg_versions", ["image_id"])

    # 4. Change unique constraint from (coloring_version_id, version) to (image_id, version)
    op.drop_constraint("uq_svg_version_coloring_version", "svg_versions")
    op.create_unique_constraint(
        "uq_svg_version_image_version", "svg_versions", ["image_id", "version"]
    )


def downgrade() -> None:
    # Reverse the unique constraint change
    op.drop_constraint("uq_svg_version_image_version", "svg_versions")
    op.create_unique_constraint(
        "uq_svg_version_coloring_version", "svg_versions", ["coloring_version_id", "version"]
    )

    # Remove image_id column
    op.drop_index("ix_svg_versions_image_id", "svg_versions")
    op.drop_constraint("fk_svg_versions_image_id", "svg_versions")
    op.drop_column("svg_versions", "image_id")

    # Remove timestamp columns from svg_versions
    op.drop_column("svg_versions", "completed_at")
    op.drop_column("svg_versions", "started_at")

    # Remove timestamp columns from coloring_versions
    op.drop_column("coloring_versions", "completed_at")
    op.drop_column("coloring_versions", "started_at")

    # Note: Cannot remove enum values in PostgreSQL without recreating the enum type
    # The extra values will remain in the enum but won't be used
