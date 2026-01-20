"""Logging configuration using structlog with colored console output."""

import logging
import sys

import structlog
from structlog.typing import Processor

from app.config import settings


def configure_logging() -> None:
    """Configure structlog for human-readable colored console output.

    This sets up structlog with:
    - Colored log levels (green=info, yellow=warning, red=error/critical)
    - Human-readable timestamps
    - Pretty key-value formatting (not JSON)
    - Exception formatting with tracebacks

    Call this early in application startup (main.py and tasks/__init__.py).
    """
    # Shared processors for both structlog and stdlib logging
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # Development: colored console output
    # Production: could switch to JSON if needed
    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare for ConsoleRenderer
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Console renderer with colors for log levels
    console_renderer = structlog.dev.ConsoleRenderer(
        colors=True,
        exception_formatter=structlog.dev.plain_traceback,
    )

    # Formatter that wraps structlog processors
    formatter = structlog.stdlib.ProcessorFormatter(
        # Foreign pre-chain handles logs from non-structlog loggers (uvicorn, httpx, etc.)
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
    )

    # Configure root handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Reduce noise from third-party loggers
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aioboto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.INFO)
    logging.getLogger("dramatiq").setLevel(logging.INFO)

    # SQLAlchemy logs SQL queries at INFO level when echo=True
    # Set to WARNING to suppress verbose SQL output while keeping errors
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


# Allow re-import without side effects
_configured = False


def setup_logging() -> None:
    """Setup logging once. Safe to call multiple times."""
    global _configured
    if not _configured:
        configure_logging()
        _configured = True
