"""Coloring version and SVG version database models."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import ImageProcessingStatus

if TYPE_CHECKING:
    from app.models.order import Image


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


# PostgreSQL enum type that uses lowercase values
_processing_status_enum = PgEnum(
    ImageProcessingStatus,
    name="imageprocessingstatus",
    create_type=False,
    values_callable=lambda e: [member.value for member in e],
)


class ColoringVersion(SQLModel, table=True):
    """A generated coloring book version for an image."""

    __tablename__ = "coloring_versions"

    id: int | None = Field(default=None, primary_key=True)
    image_id: int = Field(foreign_key="images.id", index=True)
    version: int  # Auto-increment per image, starting at 1
    file_path: str | None = None
    status: ImageProcessingStatus = Field(
        default=ImageProcessingStatus.PENDING,
        sa_column=Column(
            _processing_status_enum,
            nullable=False,
            default=ImageProcessingStatus.PENDING,
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

    id: int | None = Field(default=None, primary_key=True)
    coloring_version_id: int = Field(foreign_key="coloring_versions.id", index=True)
    version: int  # Auto-increment per image
    file_path: str | None = None
    status: ImageProcessingStatus = Field(
        default=ImageProcessingStatus.PENDING,
        sa_column=Column(
            _processing_status_enum,
            nullable=False,
            default=ImageProcessingStatus.PENDING,
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
