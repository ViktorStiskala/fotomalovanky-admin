"""Dramatiq worker entry point."""

# Import tasks package to register broker and tasks
from app import tasks  # noqa: F401
