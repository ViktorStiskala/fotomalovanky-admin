"""Coloring version and SVG version database models."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import ColoringProcessingStatus, SvgProcessingStatus
from app.models.types import S3ObjectRef, S3ObjectRefData

if TYPE_CHECKING:
    from app.models.order import Image


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


# PostgreSQL enum types for each status
_coloring_status_enum = PgEnum(
    ColoringProcessingStatus,
    name="coloringprocessingstatus",
    create_type=False,
    values_callable=lambda e: [member.value for member in e],
)

_svg_status_enum = PgEnum(
    SvgProcessingStatus,
    name="svgprocessingstatus",
    create_type=False,
    values_callable=lambda e: [member.value for member in e],
)

# Constraint for ColoringVersion uniqueness per image
COLORING_VERSION_CONSTRAINT = UniqueConstraint("image_id", "version", name="uq_coloring_version_image_version")

# Constraint for SvgVersion uniqueness per coloring version
SVG_VERSION_CONSTRAINT = UniqueConstraint("coloring_version_id", "version", name="uq_svg_version_coloring_version")


class ColoringVersion(SQLModel, table=True):
    """A generated coloring book version for an image."""

    __tablename__ = "coloring_versions"
    __table_args__ = (COLORING_VERSION_CONSTRAINT,)

    id: int | None = Field(default=None, primary_key=True)
    image_id: int = Field(foreign_key="images.id", index=True)
    version: int  # Auto-increment per image using AutoIncrementOnConflict

    # S3 storage reference (replaces file_path)
    file_ref: S3ObjectRefData | None = Field(
        default=None,
        sa_column=Column(S3ObjectRef, nullable=True),
    )

    status: ColoringProcessingStatus = Field(
        default=ColoringProcessingStatus.PENDING,
        sa_column=Column(
            _coloring_status_enum,
            nullable=False,
            default=ColoringProcessingStatus.PENDING,
        ),
    )

    # Generation settings used
    megapixels: float = 1.0
    steps: int = 4

    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Relationships (string annotations required for cross-module SQLAlchemy resolution)
    image: "Image" = Relationship(  # noqa: UP037
        back_populates="coloring_versions",
        sa_relationship_kwargs={"foreign_keys": "[ColoringVersion.image_id]"},
    )
    svg_versions: list["SvgVersion"] = Relationship(back_populates="coloring_version")  # noqa: UP037


class SvgVersion(SQLModel, table=True):
    """A vectorized SVG version generated from a coloring version."""

    __tablename__ = "svg_versions"
    __table_args__ = (SVG_VERSION_CONSTRAINT,)

    id: int | None = Field(default=None, primary_key=True)
    coloring_version_id: int = Field(foreign_key="coloring_versions.id", index=True)
    version: int  # Auto-increment per coloring version using AutoIncrementOnConflict

    # S3 storage reference (replaces file_path)
    file_ref: S3ObjectRefData | None = Field(
        default=None,
        sa_column=Column(S3ObjectRef, nullable=True),
    )

    status: SvgProcessingStatus = Field(
        default=SvgProcessingStatus.PENDING,
        sa_column=Column(
            _svg_status_enum,
            nullable=False,
            default=SvgProcessingStatus.PENDING,
        ),
    )

    # Vectorizer settings used
    shape_stacking: str = "stacked"
    group_by: str = "color"

    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Relationships
    coloring_version: ColoringVersion = Relationship(back_populates="svg_versions")
