#!/usr/bin/env python
"""Dramatiq worker entry point with recovery dispatch."""

import os
import shutil
import sys

import structlog

from app.logging import setup_logging

setup_logging()
logger = structlog.get_logger(__name__)


def main() -> None:
    """Dispatch recovery task and start Dramatiq workers."""
    # Import tasks to register broker (this triggers app.tasks.__init__.py)
    from app.tasks.utils.recovery import run_recovery

    # Dispatch recovery task
    run_recovery.send()
    logger.info("Dispatched recovery task")

    # Exec into dramatiq CLI with any additional args
    # sys.argv[0] is this script, pass the rest to dramatiq
    # When running via `uv run`, the virtualenv's bin is in PATH
    dramatiq_path = shutil.which("dramatiq")
    if dramatiq_path is None:
        logger.error("Dramatiq executable not found in PATH")
        sys.exit(1)

    os.execv(dramatiq_path, [dramatiq_path, "app.tasks", *sys.argv[1:]])


if __name__ == "__main__":
    main()
