"""Separate processing status enums for coloring and SVG.

Revision ID: 004
Revises: 003
Create Date: 2026-01-16

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create new enum types
    op.execute("""
        CREATE TYPE coloringprocessingstatus AS ENUM (
            'pending',
            'queued',
            'processing',
            'runpod_submitting',
            'runpod_submitted',
            'runpod_queued',
            'runpod_processing',
            'completed',
            'error'
        )
    """)

    op.execute("""
        CREATE TYPE svgprocessingstatus AS ENUM (
            'pending',
            'queued',
            'processing',
            'vectorizer_processing',
            'completed',
            'error'
        )
    """)

    # Alter coloring_versions.status to use new enum
    # First, drop the default, change type, then re-add default
    op.execute("""
        ALTER TABLE coloring_versions
        ALTER COLUMN status DROP DEFAULT
    """)
    op.execute("""
        ALTER TABLE coloring_versions
        ALTER COLUMN status TYPE coloringprocessingstatus
        USING status::text::coloringprocessingstatus
    """)
    op.execute("""
        ALTER TABLE coloring_versions
        ALTER COLUMN status SET DEFAULT 'pending'::coloringprocessingstatus
    """)

    # Alter svg_versions.status to use new enum
    op.execute("""
        ALTER TABLE svg_versions
        ALTER COLUMN status DROP DEFAULT
    """)
    op.execute("""
        ALTER TABLE svg_versions
        ALTER COLUMN status TYPE svgprocessingstatus
        USING status::text::svgprocessingstatus
    """)
    op.execute("""
        ALTER TABLE svg_versions
        ALTER COLUMN status SET DEFAULT 'pending'::svgprocessingstatus
    """)

    # Drop old enum type (no longer used)
    op.execute("DROP TYPE imageprocessingstatus")


def downgrade() -> None:
    # Recreate old enum type
    op.execute("""
        CREATE TYPE imageprocessingstatus AS ENUM (
            'pending',
            'queued',
            'processing',
            'completed',
            'error'
        )
    """)

    # Revert coloring_versions.status
    # Map new statuses back to old ones (all runpod_* -> processing)
    op.execute("""
        ALTER TABLE coloring_versions
        ALTER COLUMN status DROP DEFAULT
    """)
    op.execute("""
        ALTER TABLE coloring_versions
        ALTER COLUMN status TYPE imageprocessingstatus
        USING (
            CASE status::text
                WHEN 'runpod_submitting' THEN 'processing'
                WHEN 'runpod_submitted' THEN 'processing'
                WHEN 'runpod_queued' THEN 'processing'
                WHEN 'runpod_processing' THEN 'processing'
                ELSE status::text
            END
        )::imageprocessingstatus
    """)
    op.execute("""
        ALTER TABLE coloring_versions
        ALTER COLUMN status SET DEFAULT 'pending'::imageprocessingstatus
    """)

    # Revert svg_versions.status
    # Map vectorizer_processing -> processing
    op.execute("""
        ALTER TABLE svg_versions
        ALTER COLUMN status DROP DEFAULT
    """)
    op.execute("""
        ALTER TABLE svg_versions
        ALTER COLUMN status TYPE imageprocessingstatus
        USING (
            CASE status::text
                WHEN 'vectorizer_processing' THEN 'processing'
                ELSE status::text
            END
        )::imageprocessingstatus
    """)
    op.execute("""
        ALTER TABLE svg_versions
        ALTER COLUMN status SET DEFAULT 'pending'::imageprocessingstatus
    """)

    # Drop new enum types
    op.execute("DROP TYPE coloringprocessingstatus")
    op.execute("DROP TYPE svgprocessingstatus")
