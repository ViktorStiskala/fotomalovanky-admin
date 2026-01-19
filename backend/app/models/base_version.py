"""Base model for processing versions (coloring, SVG).

Defines shared field types for ColoringVersion and SvgVersion.
Due to SQLModel/SQLAlchemy inheritance limitations with sa_column,
concrete models must define their own sa_column instances.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)
