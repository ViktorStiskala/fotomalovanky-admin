"""Custom SQLAlchemy types for the application."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Uuid, and_, or_, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import ColumnElement
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

    class comparator_factory(TypeDecorator.Comparator):  # type: ignore[type-arg]
        """Custom comparator for S3ObjectRef columns.

        Handles JSONB columns that can be SQL NULL or contain JSON null.
        Overrides comparison operators so `== None` and `.is_(None)` check for both.

        Usage:
            .where(Model.file_ref.is_(None))      # nullish (SQL NULL or JSON null)
            .where(Model.file_ref == None)        # same as above
            .where(Model.file_ref.is_not(None))   # not nullish
            .where(Model.file_ref != None)        # same as above
        """

        def _nullish(self) -> ColumnElement[bool]:
            """SQL NULL or JSONB literal null."""
            # Use parent methods directly to avoid recursion
            return or_(
                super().is_(None),  # type: ignore[arg-type]
                super().__eq__(text("'null'::jsonb")),  # type: ignore[arg-type]
            )

        def _not_nullish(self) -> ColumnElement[bool]:
            """Neither SQL NULL nor JSONB literal null."""
            # Use parent methods directly to avoid recursion
            return and_(
                super().is_not(None),  # type: ignore[arg-type]
                super().__ne__(text("'null'::jsonb")),  # type: ignore[arg-type]
            )

        def __eq__(self, other: object) -> ColumnElement[bool]:  # type: ignore[override]
            if other is None:
                return self._nullish()
            return super().__eq__(other)  # type: ignore[return-value]

        def __ne__(self, other: object) -> ColumnElement[bool]:  # type: ignore[override]
            if other is None:
                return self._not_nullish()
            return super().__ne__(other)  # type: ignore[return-value]

        def is_(self, other: object) -> ColumnElement[bool]:
            if other is None:
                return self._nullish()
            return super().is_(other)  # type: ignore[return-value]

        def is_not(self, other: object) -> ColumnElement[bool]:
            if other is None:
                return self._not_nullish()
            return super().is_not(other)  # type: ignore[return-value]

    def process_bind_param(self, value: S3ObjectRefData | dict[str, Any] | None, dialect: Any) -> dict[str, Any] | None:
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
