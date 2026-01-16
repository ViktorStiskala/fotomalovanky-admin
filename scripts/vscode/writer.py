"""Settings file writer for VS Code configuration."""

import difflib
import json
from pathlib import Path
from typing import Any

import click

from .formatting import highlight_diff, highlight_json


class SettingsWriter:
    """
    Handles writing settings.json files to .vscode directories.

    Supports dry-run mode for previewing changes without writing,
    and diff mode for showing differences from global settings.
    """

    def __init__(self, workspace_dir: Path, dry_run: bool = False) -> None:
        """
        Initialize the writer.

        Args:
            workspace_dir: Base directory for resolving relative folder paths
            dry_run: If True, print output instead of writing files
        """
        self.workspace_dir = workspace_dir
        self.dry_run = dry_run

    def write(
        self,
        folder_path: str,
        folder_name: str,
        settings: dict[str, Any],
    ) -> None:
        """
        Write settings.json to a folder's .vscode directory.

        Args:
            folder_path: Relative path to the folder from workspace root
            folder_name: Display name of the folder
            settings: Settings dictionary to write
        """
        resolved_path = self.workspace_dir / folder_path
        settings_file = resolved_path / ".vscode" / "settings.json"

        if self.dry_run:
            click.secho(
                f"\n--- {folder_name} ({settings_file}) ---", fg="cyan", bold=True
            )
            click.echo(highlight_json(settings))
        else:
            self._write_file(resolved_path, settings)
            click.secho(f"Generated: {settings_file}", fg="green")

    def write_diff(
        self,
        folder_path: str,
        folder_name: str,
        global_settings: dict[str, Any],
        merged_settings: dict[str, Any],
    ) -> None:
        """
        Show diff between global and merged settings.

        Args:
            folder_path: Relative path to the folder from workspace root
            folder_name: Display name of the folder
            global_settings: Original global settings (before merge)
            merged_settings: Final merged settings (after merge and exclusions)
        """
        resolved_path = self.workspace_dir / folder_path
        settings_file = resolved_path / ".vscode" / "settings.json"

        # Generate JSON with sorted keys for consistent diff
        global_json = json.dumps(global_settings, indent=4, sort_keys=True)
        merged_json = json.dumps(merged_settings, indent=4, sort_keys=True)

        # Generate unified diff
        diff_lines = list(
            difflib.unified_diff(
                global_json.splitlines(keepends=True),
                merged_json.splitlines(keepends=True),
                fromfile="global settings",
                tofile=str(settings_file),
            )
        )

        if not diff_lines:
            click.echo(f"\n{folder_name}: No differences from global settings")
            return

        click.secho(f"\n--- {folder_name} ---", fg="cyan", bold=True)
        diff_text = "".join(diff_lines)
        click.echo(highlight_diff(diff_text))

    def _write_file(self, folder_path: Path, settings: dict[str, Any]) -> None:
        """Write settings.json to the folder's .vscode directory."""
        vscode_dir = folder_path / ".vscode"
        vscode_dir.mkdir(parents=True, exist_ok=True)

        settings_file = vscode_dir / "settings.json"
        with settings_file.open("w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
            f.write("\n")  # Trailing newline
