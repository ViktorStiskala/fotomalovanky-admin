# Root-Only Setting in Folder Configuration

## The Issue

You've placed a `workspaceManager.*` setting inside a folder's `settings` object, but this setting only works at the workspace root level.

## Which Settings Are Affected?

These settings only work in the root `settings` object:

- `workspaceManager.autoSync.enabled` - Controls automatic file watching
- `workspaceManager.sync.enabled` - Enables/disables forward sync
- `workspaceManager.sync.rootSettings.exclude` - Patterns to exclude from inheritance
- `workspaceManager.sync.subFolderSettings.defaults` - Default settings for all subfolders

## Example of Incorrect Configuration

```json
{
  "folders": [
    {
      "name": "Backend",
      "path": "backend",
      "settings": {
        "workspaceManager.sync.enabled": false,
        "workspaceManager.sync.rootSettings.exclude": ["python.*"],
        "editor.fontSize": 14
      }
    }
  ],
  "settings": {
    "editor.rulers": [120]
  }
}
```

In this example, `workspaceManager.sync.enabled` and `workspaceManager.sync.rootSettings.exclude` are placed in the Backend folder's settings. **They will be completely ignored.**

## What Actually Happens

- The `workspaceManager.sync.*` settings in the folder are ignored
- Forward sync still runs using the root default (`true`)
- No exclude patterns are applied
- `backend/.vscode/settings.json` gets: `{ "editor.rulers": [120], "editor.fontSize": 14 }`

The folder-level settings have no effect on the extension's behavior.

## Why This Happens

VS Code workspace settings have different "scopes":

- **Window scope** - Applies to the entire VS Code window (only works at root level)
- **Resource scope** - Can be configured per-folder

The affected settings are window-scoped because they control the extension's global behavior, not per-folder behavior.

## How to Fix

Move the setting to the root `settings` object:

```json
{
  "folders": [
    {
      "name": "Backend",
      "path": "backend",
      "settings": {
        "editor.fontSize": 14
      }
    }
  ],
  "settings": {
    "workspaceManager.sync.enabled": false,
    "workspaceManager.sync.rootSettings.exclude": ["python.*"],
    "editor.rulers": [120]
  }
}
```

## Quick Fix

Click on the highlighted setting and press `Cmd+.` (macOS) or `Ctrl+.` (Windows/Linux) to see the Quick Fix option: **"Move to root settings"**.

This will automatically move the setting to the correct location.

## Per-Folder Settings That DO Work

These settings CAN be configured per-folder:

- `workspaceManager.reverseSync.enabled` - Enable/disable reverse sync for this folder
- `workspaceManager.reverseSync.folderSettings.exclude` - Additional exclude patterns for this folder

Example:

```json
{
  "folders": [
    {
      "name": "Backend",
      "path": "backend",
      "settings": {
        "workspaceManager.reverseSync.enabled": false
      }
    }
  ]
}
```
