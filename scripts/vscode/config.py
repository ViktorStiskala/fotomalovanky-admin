"""Workspace configuration loading and parsing."""

from pathlib import Path
from typing import Any

import json5


class WorkspaceNotFoundError(Exception):
    """Raised when workspace file cannot be found."""

    pass


class WorkspaceConfig:
    """
    Encapsulates workspace file loading and configuration extraction.

    Handles:
    - Loading JSON5 workspace files (with trailing commas)
    - Extracting global settings
    - Extracting folder definitions
    - Extracting generator configuration (merge config, exclusions)
    """

    def __init__(self, workspace_path: Path) -> None:
        """
        Load and parse a workspace file.

        Args:
            workspace_path: Path to the .code-workspace file

        Raises:
            FileNotFoundError: If workspace file doesn't exist
        """
        self.path = workspace_path
        self.workspace_dir = workspace_path.parent
        self._data = self._load(workspace_path)

    @staticmethod
    def _load(workspace_path: Path) -> dict[str, Any]:
        """Load and parse the workspace file using json5."""
        with workspace_path.open("r", encoding="utf-8") as f:
            return json5.load(f)

    @classmethod
    def find_workspace(cls) -> Path:
        """
        Auto-detect workspace file from .git root.

        Traverses up from current directory to find nearest .git folder,
        then looks for <folder_name>.code-workspace in that directory.

        Returns:
            Path to the workspace file

        Raises:
            WorkspaceNotFoundError: If no .git folder or workspace file found
        """
        current = Path.cwd()

        # Find nearest parent with .git folder (workspace root)
        workspace_root = None
        for parent in [current, *current.parents]:
            if (parent / ".git").exists():
                workspace_root = parent
                break

        if workspace_root is None:
            raise WorkspaceNotFoundError(
                "Could not find workspace root (no .git folder found). "
                "Use --workspace to specify path."
            )

        # Look for <folder_name>.code-workspace in the workspace root
        workspace_path = workspace_root / f"{workspace_root.name}.code-workspace"
        if not workspace_path.exists():
            raise WorkspaceNotFoundError(
                f"Workspace file not found: {workspace_path}\n"
                "Use --workspace to specify path."
            )

        return workspace_path

    @property
    def global_settings(self) -> dict[str, Any]:
        """Get global settings from the workspace file."""
        return self._data.get("settings", {})

    @property
    def folders(self) -> list[dict[str, Any]]:
        """Get folder definitions from the workspace file."""
        return self._data.get("folders", [])

    @staticmethod
    def get_folder_generator_config(
        folder: dict[str, Any],
    ) -> tuple[dict[str, bool], dict[str, bool]]:
        """
        Get generator config (merge, exclude) from a folder definition.

        Each folder can have its own `generator.settings` to control merge/exclude behavior.
        Supports * wildcard for prefix matching in both merge and exclude patterns.

        Args:
            folder: A folder definition dict from the workspace file

        Returns:
            Tuple of (merge_config, exclusions)
        """
        gen_config = folder.get("generator.settings", {})
        return (gen_config.get("merge", {}), gen_config.get("exclude", {}))
