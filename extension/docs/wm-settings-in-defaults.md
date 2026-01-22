# workspaceManager Settings in subFolderSettings.defaults

## The Issue

You've placed `workspaceManager.*` settings inside `workspaceManager.sync.subFolderSettings.defaults`. These settings are **not allowed** in defaults and will be silently removed.

## Example of Incorrect Configuration

```json
{
  "folders": [
    { "name": "Backend", "path": "backend" },
    { "name": "Frontend", "path": "frontend" }
  ],
  "settings": {
    "workspaceManager.sync.subFolderSettings.defaults": {
      "files.exclude": { ".vscode": true },
      "workspaceManager.reverseSync.enabled": false,
      "workspaceManager.reverseSync.folderSettings.exclude": ["files.exclude"]
    }
  }
}
```

In this example, the user expects all folders to have:

- `files.exclude` set
- Reverse sync disabled
- `files.exclude` excluded from reverse sync

## What Actually Happens

The `workspaceManager.*` keys are **stripped** by the extension before writing to `.vscode/settings.json` files.

Each folder's `.vscode/settings.json` only gets:

```json
{
  "files.exclude": { ".vscode": true }
}
```

The `workspaceManager.reverseSync.*` settings are completely ignored:

- Reverse sync is still **enabled** for all folders (using the root default of `true`)
- No patterns are excluded from reverse sync

## Why This Happens

The `subFolderSettings.defaults` object is designed to provide default settings that get written to `.vscode/settings.json` files. Since `workspaceManager.*` settings are internal to the extension (not actual VS Code settings), they are filtered out before writing.

Putting `workspaceManager.*` in defaults would:

1. Write them to `.vscode/settings.json` (where they do nothing)
2. Create confusion about where the extension reads its configuration

## How to Fix

### Option 1: Configure Per-Folder

Put `workspaceManager.reverseSync.*` settings directly in each folder that needs them:

```json
{
  "folders": [
    {
      "name": "Backend",
      "path": "backend",
      "settings": {
        "workspaceManager.reverseSync.enabled": false,
        "workspaceManager.reverseSync.folderSettings.exclude": ["files.exclude"]
      }
    },
    {
      "name": "Frontend",
      "path": "frontend",
      "settings": {
        "workspaceManager.reverseSync.enabled": false,
        "workspaceManager.reverseSync.folderSettings.exclude": ["files.exclude"]
      }
    }
  ],
  "settings": {
    "workspaceManager.sync.subFolderSettings.defaults": {
      "files.exclude": { ".vscode": true }
    }
  }
}
```

### Option 2: Configure at Root Level

For settings that should apply to all folders, use root `settings`:

```json
{
  "folders": [
    { "name": "Backend", "path": "backend" },
    { "name": "Frontend", "path": "frontend" }
  ],
  "settings": {
    "workspaceManager.reverseSync.enabled": false,
    "workspaceManager.reverseSync.folderSettings.exclude": ["files.exclude"],
    "workspaceManager.sync.subFolderSettings.defaults": {
      "files.exclude": { ".vscode": true }
    }
  }
}
```

Root-level `reverseSync` settings serve as defaults for all folders.

## Quick Fix

Click on the highlighted setting and press `Cmd+.` (macOS) or `Ctrl+.` (Windows/Linux) to see the Quick Fix option: **"Remove [setting name] setting"**.

This removes the invalid setting from defaults. You'll need to add it to the correct location (root settings or individual folder settings) separately.

## Summary

| Where to Put                 | What It Does                                     |
| ---------------------------- | ------------------------------------------------ |
| Root `settings`              | Default for all folders (folders can override)   |
| `folders[].settings`         | Specific to that folder                          |
| `subFolderSettings.defaults` | **NOT ALLOWED** for workspaceManager.\* settings |
