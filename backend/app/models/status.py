"""Processing status base classes with flag-based metadata.

This module provides a declarative way to define processing statuses with
combinable flags for metadata (recoverable, retryable, final, etc.).

Usage:
    class MyProcessingStatus(ProcessingStatusEnum):
        PENDING = Status("pending", Flags.STARTABLE, display="Čeká")
        PROCESSING = Status("processing", Flags.RECOVERABLE, display="Zpracovává se")
        COMPLETED = Status("completed", Flags.FINAL, display="Dokončeno")
        ERROR = Status("error", Flags.FINAL | Flags.RETRYABLE, display="Chyba")
"""

from dataclasses import dataclass
from enum import IntFlag, StrEnum, auto
from typing import Any


class Flags(IntFlag):
    """Processing status metadata flags.

    Flags:
        STARTABLE         - Task can be picked up by a worker (initial states)
        RECOVERABLE       - Task recovery should re-dispatch if stuck (active states)
        AWAITING_EXTERNAL - External service is processing async (requires polling/webhook)
        FINAL             - Final state, no more processing
        RETRYABLE         - User can manually retry (requires FINAL)
    """

    NONE = 0
    STARTABLE = auto()  # Task can be picked up by a worker
    RECOVERABLE = auto()  # Task recovery should re-dispatch if stuck
    AWAITING_EXTERNAL = auto()  # External service processing async (poll or wait for webhook)
    FINAL = auto()  # Final state, no more processing
    RETRYABLE = auto()  # User can retry (only valid with FINAL)


@dataclass(frozen=True)
class FlagRule:
    """Rule for validating flag combinations.

    Attributes:
        when: All these bits must be present to trigger the rule
        required: These bits must also be present (when rule triggers)
        forbidden: These bits must be absent (when rule triggers)
    """

    when: Flags
    required: Flags = Flags.NONE
    forbidden: Flags = Flags.NONE

    def __post_init__(self) -> None:
        if self.when == Flags.NONE:
            raise ValueError("when may not be empty")
        if self.required & self.forbidden:
            raise ValueError("required and forbidden overlap")


# Validation rules for flag combinations
FLAG_RULES: set[FlagRule] = {
    # RETRYABLE requires FINAL
    FlagRule(
        when=Flags.RETRYABLE,
        required=Flags.FINAL,
    ),
    # FINAL forbids RECOVERABLE, STARTABLE, and AWAITING_EXTERNAL
    FlagRule(
        when=Flags.FINAL,
        forbidden=Flags.RECOVERABLE | Flags.STARTABLE | Flags.AWAITING_EXTERNAL,
    ),
    # AWAITING_EXTERNAL requires RECOVERABLE (must be able to resume polling)
    # and forbids STARTABLE (already past the start phase)
    FlagRule(
        when=Flags.AWAITING_EXTERNAL,
        required=Flags.RECOVERABLE,
        forbidden=Flags.STARTABLE,
    ),
}


def validate_flags(value: Flags) -> None:
    """Validate flag combination against rules."""
    for rule in FLAG_RULES:
        # Rule triggers only if all `when` bits are present
        if (value & rule.when) != rule.when:
            continue

        missing = rule.required & ~value
        present_forbidden = value & rule.forbidden

        if missing or present_forbidden:
            parts: list[str] = []
            if missing:
                missing_name = missing.name or str(missing)
                parts.append(f"{missing_name.replace('|', ' and ')} must be present")
            if present_forbidden:
                forbidden_name = present_forbidden.name or str(present_forbidden)
                parts.append(f"{forbidden_name.replace('|', ' and ')} cannot be present")

            when_name = rule.when.name or str(rule.when)
            when_txt = when_name.replace("|", " and ")
            raise ValueError(f"When {when_txt}: " + " and ".join(parts))


@dataclass(frozen=True, slots=True)
class Status:
    """Status definition with value, flags, and display name."""

    value: str
    flags: Flags = Flags.NONE
    display: str = ""

    def __post_init__(self) -> None:
        # Validate flags on creation
        validate_flags(self.flags)

    @property
    def is_startable(self) -> bool:
        return bool(self.flags & Flags.STARTABLE)

    @property
    def is_recoverable(self) -> bool:
        return bool(self.flags & Flags.RECOVERABLE)

    @property
    def is_final(self) -> bool:
        return bool(self.flags & Flags.FINAL)

    @property
    def is_retryable(self) -> bool:
        return bool(self.flags & Flags.RETRYABLE)

    @property
    def is_awaiting_external(self) -> bool:
        return bool(self.flags & Flags.AWAITING_EXTERNAL)


# Registry to store Status metadata for each enum class
_status_registries: dict[type, dict[str, Status]] = {}


class ProcessingStatusEnum(StrEnum):
    """Base class for processing status enums with metadata support.

    Subclasses define members using Status objects:
        PENDING = Status("pending", Flags.STARTABLE, display="...")

    The enum value is the string (for DB), metadata accessible via .meta
    """

    def __new__(cls, status: Status | str) -> "ProcessingStatusEnum":
        # Handle both Status objects and plain strings
        if isinstance(status, Status):
            value = status.value
            # Store metadata in global registry keyed by class
            if cls not in _status_registries:
                _status_registries[cls] = {}
            _status_registries[cls][value] = status
        else:
            value = status

        obj = str.__new__(cls, value)
        obj._value_ = value
        return obj

    @property
    def meta(self) -> Status:
        """Get metadata for this status."""
        registry = _status_registries.get(type(self), {})
        return registry.get(self._value_, Status(self._value_))

    @classmethod
    def intermediate_states(cls) -> "frozenset[Any]":
        """States where task recovery should re-dispatch (RECOVERABLE flag)."""
        return frozenset(s for s in cls if s.meta.is_recoverable)

    @classmethod
    def startable_states(cls) -> "frozenset[Any]":
        """States from which a task can be started (STARTABLE or RETRYABLE).

        Includes initial states (PENDING, QUEUED) and failed states (ERROR, CANCELLED)
        that can be retried by user action.
        """
        return frozenset(s for s in cls if s.meta.is_startable or s.meta.is_retryable)

    @classmethod
    def final_states(cls) -> "frozenset[Any]":
        """Final states (FINAL flag) - completed, error, cancelled."""
        return frozenset(s for s in cls if s.meta.is_final)

    @classmethod
    def retryable_states(cls) -> "frozenset[Any]":
        """States where user can manually retry (RETRYABLE flag)."""
        return frozenset(s for s in cls if s.meta.is_retryable)

    @classmethod
    def awaiting_external_states(cls) -> "frozenset[Any]":
        """States where external service is processing async (poll or webhook)."""
        return frozenset(s for s in cls if s.meta.is_awaiting_external)
