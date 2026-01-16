"""Settings merger with configurable deep merge and exclusion support."""

import copy
from typing import Any


class SettingsMerger:
    """
    Handles merging of VS Code settings with configurable behavior.

    Supports:
    - Deep merging of nested dictionaries
    - Per-key merge control (replace vs merge) with * wildcard
    - Exclusion of keys with * wildcard for prefix matching
    - Precedence: more specific patterns override wildcards
    - Exclusions take precedence over merge settings
    """

    def __init__(
        self,
        merge_config: dict[str, bool],
        exclusions: dict[str, bool],
    ) -> None:
        """
        Initialize the merger.

        Args:
            merge_config: Per-key merge behavior with * wildcard support.
                          If False, replace entirely instead of deep merge.
                          Default (no match) is True (deep merge).
            exclusions: Keys to exclude from output with * wildcard support.
                        Use `path: false` to keep a key that would be excluded by wildcard.
                        Exclusions take precedence over merge settings.
        """
        self.merge_config = merge_config
        self.exclusions = exclusions

    def merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """
        Merge override into base, respecting merge_config for per-key behavior.

        Args:
            base: Base dictionary (global settings)
            override: Override dictionary (folder settings)

        Returns:
            Merged dictionary with exclusions applied
        """
        result = self._deep_merge(base, override, prefix="")
        self._apply_exclusions(result)
        return result

    @staticmethod
    def _match_pattern(path: str, patterns: dict[str, bool], default: bool) -> bool:
        """
        Match a path against patterns with * wildcard support.

        Patterns ending with * match any path starting with that prefix.
        More specific (longer) patterns take precedence over shorter ones.
        Exact matches have highest priority.

        Args:
            path: The dot notation path to check (e.g., "files.include.git")
            patterns: Dict of pattern -> value
            default: Value to return if no pattern matches

        Returns:
            The value from the most specific matching pattern, or default

        Examples:
            patterns = {"files.*": False, "files.include.*": True}
            _match_pattern("files.exclude.git", patterns, True)  -> False (matches files.*)
            _match_pattern("files.include.node", patterns, True) -> True (files.include.*)
        """
        matches: list[tuple[str, bool, int]] = []

        for pattern, value in patterns.items():
            if pattern == path:
                # Exact match has highest priority
                matches.append((pattern, value, 1000 + len(pattern)))
            elif pattern.endswith("*"):
                # Wildcard: "files.*" matches "files.exclude", "files.include.node", etc.
                prefix = pattern[:-1]  # Remove trailing *
                if path.startswith(prefix):
                    matches.append((pattern, value, len(prefix)))

        if not matches:
            return default

        # Most specific (longest prefix) wins
        matches.sort(key=lambda x: x[2], reverse=True)
        return matches[0][1]

    def _should_merge(self, path: str) -> bool:
        """Check if a path should be deep merged (default: True)."""
        return self._match_pattern(path, self.merge_config, default=True)

    def _should_exclude(self, path: str) -> bool:
        """Check if a path should be excluded (default: False)."""
        return self._match_pattern(path, self.exclusions, default=False)

    def _deep_merge(
        self,
        base: dict[str, Any],
        override: dict[str, Any],
        prefix: str,
    ) -> dict[str, Any]:
        """Recursively merge dictionaries respecting merge config."""
        result = copy.deepcopy(base)

        for key, value in override.items():
            # Build full path for pattern matching
            full_path = f"{prefix}.{key}" if prefix else key
            should_merge = self._should_merge(full_path)

            if (
                should_merge
                and key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                # Recursively merge nested dicts
                result[key] = self._deep_merge(result[key], value, full_path)
            else:
                # Replace entirely (either merge=false or non-dict values)
                result[key] = copy.deepcopy(value)

        return result

    def _apply_exclusions(self, settings: dict[str, Any], prefix: str = "") -> None:
        """
        Remove keys marked for exclusion using dot notation paths.

        Processes the settings recursively and checks each key against exclusion patterns.
        Exclusions take precedence over merge settings.
        """
        keys_to_delete: list[str] = []

        for key in list(settings.keys()):
            # Build the full path for this key
            full_path = f"{prefix}.{key}" if prefix else key

            # Check if this key should be excluded
            if self._should_exclude(full_path):
                keys_to_delete.append(key)
            elif isinstance(settings[key], dict):
                # Recursively process nested dicts
                self._apply_exclusions(settings[key], full_path)

        # Delete excluded keys
        for key in keys_to_delete:
            del settings[key]
