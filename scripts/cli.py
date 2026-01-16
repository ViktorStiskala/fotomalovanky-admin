"""Parent CLI for workspace scripts."""

import click

try:
    # Module execution: python -m scripts
    from .vscode.cli import settings as vscode_settings
except ImportError:
    # Direct execution: uv run scripts
    from vscode.cli import (  # type: ignore[import-not-found,no-redef]
        settings as vscode_settings,
    )


@click.group()
def cli() -> None:
    """Scripts for workspace management."""
    pass


cli.add_command(vscode_settings, name="vscode-settings")
