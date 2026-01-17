"""Manual order sequence model for generating manual order numbers."""

from sqlmodel import Field, SQLModel


class ManualOrderSequence(SQLModel, table=True):
    """Sequence for manual order numbers starting at 1000.

    Uses SELECT ... FOR UPDATE to prevent collisions when
    multiple requests try to create manual orders concurrently.
    """

    __tablename__ = "manual_order_sequence"

    id: int = Field(default=1, primary_key=True)
    next_value: int = Field(default=1000)
