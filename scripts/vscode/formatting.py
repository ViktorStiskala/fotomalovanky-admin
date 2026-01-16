"""Shared formatting helpers for terminal output."""

import json
from typing import Any

import click
from pygments import highlight
from pygments.formatters import Terminal256Formatter
from pygments.lexers import DiffLexer, JsonLexer

FORMATTER = Terminal256Formatter(style="monokai")


def highlight_json(data: dict[str, Any] | str) -> str:
    """Syntax highlight JSON for terminal output."""
    if isinstance(data, dict):
        data = json.dumps(data, indent=4)
    return highlight(data, JsonLexer(), FORMATTER).rstrip()


def highlight_diff(diff_text: str) -> str:
    """Syntax highlight unified diff for terminal output."""
    return highlight(diff_text, DiffLexer(), FORMATTER).rstrip()


def style_header(text: str) -> str:
    """Style section headers (yellow, bold)."""
    return click.style(text, fg="yellow", bold=True)


def style_code(text: str) -> str:
    """Style inline code snippets (cyan)."""
    return click.style(text, fg="cyan")
