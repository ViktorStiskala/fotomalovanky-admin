"""Race-condition-safe auto-increment helper using savepoints."""

from collections.abc import AsyncIterator
from typing import Any, TypeVar

import structlog
from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class AutoIncrementOnConflict:
    """Async iterator with savepoint-based retry on unique constraint conflict.

    Uses an async for loop to retry on unique constraint violations.
    Each iteration provides a new calculated value and a savepoint.

    Usage:
        async for attempt in AutoIncrementOnConflict(
            session=self.session,
            model_class=LineItem,
            increment_column=LineItem.position,
            filter_columns={LineItem.order_id: order_id},
            constraint=LINE_ITEM_POSITION_CONSTRAINT,
        ):
            async with attempt:
                line_item = LineItem(order_id=order_id, position=attempt.value, ...)
                session.add(line_item)
                await session.flush()
    """

    def __init__(
        self,
        session: AsyncSession,
        model_class: type[T],
        increment_column: Any,  # InstrumentedAttribute at runtime
        filter_columns: dict[Any, Any],  # InstrumentedAttribute keys
        constraint: UniqueConstraint,
        max_retries: int = 5,
    ):
        self.session = session
        self.model_class = model_class
        self.increment_column = increment_column
        self.filter_columns = filter_columns
        self.constraint = constraint
        self.max_retries = max_retries
        self.current_attempt = 0
        self._value: int | None = None
        self._success = False

        if not self.constraint.name:
            raise ValueError("UniqueConstraint must have a name for conflict detection.")

    async def __aiter__(self) -> AsyncIterator["AutoIncrementOnConflict"]:
        while self.current_attempt < self.max_retries and not self._success:
            self.current_attempt += 1
            self._value = await self._get_next_value()
            yield self
        if not self._success:
            raise RuntimeError(
                f"Failed to allocate unique value after {self.max_retries} retries "
                f"(constraint: {self.constraint.name})"
            )

    @property
    def value(self) -> int:
        if self._value is None:
            raise RuntimeError("Value not yet calculated for this attempt.")
        return self._value

    async def _get_next_value(self) -> int:
        filters = [col == val for col, val in self.filter_columns.items()]
        stmt = select(func.coalesce(func.max(self.increment_column), 0) + 1).where(*filters)
        result = await self.session.execute(stmt)
        value: int = result.scalar_one()
        return value

    async def __aenter__(self) -> "AutoIncrementOnConflict":
        await self.session.begin_nested()  # Create a savepoint
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        if exc_type is None:
            await self.session.commit()  # Commit the savepoint
            self._success = True
            return False  # Do not suppress exception
        elif exc_type is IntegrityError:
            error_str = str(exc_val).lower() if exc_val else ""
            # Check if it's a unique constraint violation for the specific constraint
            if self.constraint.name and f'"{self.constraint.name}"' in error_str:
                logger.warning(
                    "Unique constraint conflict, retrying",
                    attempt=self.current_attempt,
                    max_retries=self.max_retries,
                    constraint=self.constraint.name,
                    error=str(exc_val),
                )
                await self.session.rollback()  # Rollback to savepoint
                return True  # Suppress exception, allow retry
            else:
                await self.session.rollback()  # Rollback to savepoint
                return False  # Re-raise other IntegrityErrors
        else:
            await self.session.rollback()  # Rollback to savepoint
            return False  # Re-raise other exceptions
