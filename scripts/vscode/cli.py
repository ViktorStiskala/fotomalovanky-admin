"""CLI command for generating VS Code settings files."""

import textwrap
from pathlib import Path

import click

from .config import WorkspaceConfig, WorkspaceNotFoundError
from .formatting import highlight_json, style_code, style_header
from .merger import SettingsMerger
from .writer import SettingsWriter

EXAMPLE_JSON = """\
{
  "folders": [
    {
      "name": "Backend",
      "path": "backend",
      "settings": {"python.defaultInterpreterPath": ".venv/bin/python"}
    },
    {
      "name": "Frontend",
      "path": "frontend",
      "settings": {"python.defaultInterpreterPath": null},
      "generator.settings": {
        "exclude": {"python*": true, "[python]*": true}
      }
    },
    {"name": "Root", "path": "."}
  ],
  "settings": {
    "editor.rulers": [120],
    "python.defaultInterpreterPath": ".venv/bin/python",
    "[python]": {"editor.defaultFormatter": "ruff"}
  }
}"""


def get_help_epilog() -> str:
    """Build colored help epilog with syntax-highlighted JSON example."""
    example_block = textwrap.indent(highlight_json(EXAMPLE_JSON), "    ")

    return f"""\
{style_header("Configuration:")}
  Add {style_code('"generator.settings"')} to folder definitions to customize merge/exclude behavior.

  Example workspace configuration:
{example_block}

  {style_header("Per-folder generator.settings:")}
    {style_code("merge.<pattern>")}       - Control deep merging (default: true). Supports * wildcard.
                              {style_code('"[python]": false')} - replace [python] block entirely
                              {style_code('"files.*": false')} - replace all files.* keys
    {style_code("exclude.<pattern>")}     - Remove keys from output. Supports * wildcard.
                              {style_code('"python*": true')} - exclude all python* keys
                              {style_code('"[python]*": true')} - exclude the [python] block

  {style_header("Precedence:")}
    - More specific patterns override wildcards (exact > longer prefix > shorter)
    - {style_code("exclude")} takes precedence over {style_code("merge")} (excluded keys are removed)
    - Use {style_code("exclude.<path>: false")} to keep a key that would be excluded by wildcard

  {style_header("Behavior:")}
    - Folders with a {style_code('"settings"')} key get global settings merged with folder settings
    - Root folder ({style_code('path: "."')}) is always skipped
    - Folders without {style_code('"settings"')} key are skipped
"""


class HelpEpilogCommand(click.Command):
    """Custom Command class that generates epilog lazily and preserves formatting."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Override to set epilog just before formatting."""
        self.epilog = get_help_epilog()
        super().format_help(ctx, formatter)

    def format_epilog(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Override to preserve epilog formatting (no text wrapping)."""
        if self.epilog:
            formatter.write_paragraph()
            # Write epilog directly without wrapping
            formatter.write(self.epilog)


@click.command("settings", cls=HelpEpilogCommand)
@click.option(
    "--workspace",
    type=click.Path(path_type=Path),
    help="Path to workspace file (default: <git-root>/<dirname>.code-workspace)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print what would be generated without writing files",
)
@click.option(
    "--diff",
    is_flag=True,
    help="Show git-diff style comparison of folder settings vs global (implies --dry-run)",
)
def settings(workspace: Path | None, dry_run: bool, diff: bool) -> None:
    """Generate .vscode/settings.json files from workspace configuration."""
    # --diff implies --dry-run
    if diff:
        dry_run = True

    # Find or validate workspace file
    try:
        if workspace:
            if not workspace.exists():
                raise click.ClickException(f"Workspace file not found: {workspace}")
            workspace_path = workspace
        else:
            workspace_path = WorkspaceConfig.find_workspace()
    except WorkspaceNotFoundError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Using workspace: {workspace_path}")

    # Load workspace configuration
    config = WorkspaceConfig(workspace_path)
    writer = SettingsWriter(config.workspace_dir, dry_run=dry_run)

    # Process folders
    generated_count = 0

    for folder in config.folders:
        folder_path = folder.get("path", "")
        folder_name = folder.get("name", folder_path)

        # Skip root folder
        if folder_path == ".":
            click.secho(f"Skipping root folder: {folder_name}", fg="yellow")
            continue

        # Skip folders without settings
        folder_settings = folder.get("settings")
        if folder_settings is None:
            click.echo(f"Skipping (no settings): {folder_name}")
            continue

        # Get per-folder generator config and create merger
        merge_config, exclusions = config.get_folder_generator_config(folder)
        merger = SettingsMerger(merge_config, exclusions)

        # Generate merged settings
        merged_settings = merger.merge(config.global_settings, folder_settings)

        # Write settings file or show diff
        if diff:
            writer.write_diff(
                folder_path, folder_name, config.global_settings, merged_settings
            )
        else:
            writer.write(folder_path, folder_name, merged_settings)
        generated_count += 1

    # Summary
    if generated_count == 0:
        click.echo("\nNo folders with settings found (excluding root).")
    elif not diff:
        click.echo(f"\nGenerated {generated_count} settings file(s).")
