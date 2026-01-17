"""Custom SQLAlchemy types for the application."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator
from ulid import ULID


class ULIDType(TypeDecorator[str]):
    """SQLAlchemy type that stores ULID as PostgreSQL UUID.

    - Database: UUID (16 bytes, efficient indexing, binary comparison)
    - Python: ULID object or string
    - API: 26-character string (via Pydantic serialization)
    """

    impl = Uuid
    cache_ok = True

    def process_bind_param(self, value: str | ULID | None, dialect: Any) -> UUID | None:
        """Convert ULID string/object to UUID for storage."""
        if value is None:
            return None
        if isinstance(value, str):
            value = ULID.from_str(value)
        if isinstance(value, ULID):
            return value.to_uuid()
        raise ValueError(f"Cannot convert {type(value)} to ULID")

    def process_result_value(self, value: UUID | None, dialect: Any) -> str | None:
        """Convert UUID back to ULID string."""
        if value is None:
            return None
        return str(ULID.from_uuid(value))


class S3ObjectRefData(BaseModel):
    """Pydantic model for S3 object reference data."""

    key: str
    bucket: str
    content_type: str | None = None
    size: int | None = None
    etag: str | None = None
    sha256: str | None = None
    original_filename: str | None = None


class S3ObjectRef(TypeDecorator[S3ObjectRefData | None]):
    """SQLAlchemy type for S3 object references stored as JSONB."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(
        self, value: S3ObjectRefData | dict[str, Any] | None, dialect: Any
    ) -> dict[str, Any] | None:
        """Convert S3ObjectRefData to dict for storage."""
        if value is None:
            return None
        if isinstance(value, S3ObjectRefData):
            return value.model_dump(exclude_none=True)
        return value

    def process_result_value(self, value: dict[str, Any] | None, dialect: Any) -> S3ObjectRefData | None:
        """Convert dict back to S3ObjectRefData."""
        if value is None:
            return None
        return S3ObjectRefData.model_validate(value)
