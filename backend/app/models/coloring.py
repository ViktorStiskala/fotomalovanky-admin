"""Coloring version and SVG version database models."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.base_version import utc_now
from app.models.enums import (
    COLORING_STATUS_PG_ENUM,
    SVG_STATUS_PG_ENUM,
    ColoringProcessingStatus,
    SvgProcessingStatus,
)
from app.models.types import S3ObjectRef, S3ObjectRefData

if TYPE_CHECKING:
    from app.models.order import Image


# Constraint for ColoringVersion uniqueness per image
COLORING_VERSION_CONSTRAINT = UniqueConstraint("image_id", "version", name="uq_coloring_version_image_version")

# Constraint for SvgVersion uniqueness per image (changed from coloring_version_id)
SVG_VERSION_CONSTRAINT = UniqueConstraint("image_id", "version", name="uq_svg_version_image_version")


class ColoringVersion(SQLModel, table=True):
    """A generated coloring book version for an image.

    Fields:
    - id, image_id, version, file_ref
    - created_at, started_at, completed_at
    - status, runpod_job_id, megapixels, steps
    """

    __tablename__ = "coloring_versions"
    __table_args__ = (COLORING_VERSION_CONSTRAINT,)

    id: int | None = Field(default=None, primary_key=True)
    image_id: int = Field(foreign_key="images.id", index=True)
    version: int  # Auto-increment per image using AutoIncrementOnConflict

    # S3 storage reference
    file_ref: S3ObjectRefData | None = Field(
        default=None,
        sa_column=Column(S3ObjectRef, nullable=True),
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # RunPod job ID for resuming interrupted polling
    runpod_job_id: str | None = Field(default=None, max_length=100)

    status: ColoringProcessingStatus = Field(
        default=ColoringProcessingStatus.PENDING,
        sa_column=Column(
            COLORING_STATUS_PG_ENUM,
            nullable=False,
            default=ColoringProcessingStatus.PENDING,
        ),
    )

    # Generation settings used
    megapixels: float = 1.0
    steps: int = 4

    # Relationships (string annotations required for cross-module SQLAlchemy resolution)
    image: "Image" = Relationship(  # noqa: UP037
        back_populates="coloring_versions",
        sa_relationship_kwargs={"foreign_keys": "[ColoringVersion.image_id]"},
    )
    svg_versions: list["SvgVersion"] = Relationship(back_populates="coloring_version")  # noqa: UP037


class SvgVersion(SQLModel, table=True):
    """A vectorized SVG version generated from a coloring version.

    Fields:
    - id, image_id, version, file_ref
    - created_at, started_at, completed_at
    - status, coloring_version_id, vectorizer_job_id

    Note: Has both image_id and coloring_version_id.
    The image_id enables direct queries, coloring_version_id tracks the source.
    Unique constraint is on (image_id, version), not (coloring_version_id, version).
    """

    __tablename__ = "svg_versions"
    __table_args__ = (SVG_VERSION_CONSTRAINT,)

    id: int | None = Field(default=None, primary_key=True)
    image_id: int = Field(foreign_key="images.id", index=True)
    version: int  # Auto-increment per image using AutoIncrementOnConflict

    # S3 storage reference
    file_ref: S3ObjectRefData | None = Field(
        default=None,
        sa_column=Column(S3ObjectRef, nullable=True),
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Reference to the coloring version used as source for vectorization
    coloring_version_id: int = Field(foreign_key="coloring_versions.id", index=True)

    # Vectorizer.ai job ID for resuming interrupted polling
    vectorizer_job_id: str | None = Field(default=None, max_length=100)

    status: SvgProcessingStatus = Field(
        default=SvgProcessingStatus.PENDING,
        sa_column=Column(
            SVG_STATUS_PG_ENUM,
            nullable=False,
            default=SvgProcessingStatus.PENDING,
        ),
    )

    # Vectorizer settings used
    shape_stacking: str = "stacked"
    group_by: str = "color"

    # Relationships
    coloring_version: ColoringVersion = Relationship(back_populates="svg_versions")
