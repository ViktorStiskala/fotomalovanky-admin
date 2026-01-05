"""Datetime utility functions."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import settings

# Timezone for API responses (from config)
API_TIMEZONE = ZoneInfo(settings.timezone)


def to_api_timezone(dt: datetime | None) -> datetime | None:
    """Convert a datetime to API timezone (from config).

    Args:
        dt: Datetime to convert (can be None)

    Returns:
        Datetime in API timezone, or None if input was None
    """
    if dt is None:
        return None
    # Ensure datetime is timezone-aware (assume UTC if naive)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(API_TIMEZONE)
