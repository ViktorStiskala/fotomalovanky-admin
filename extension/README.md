# Workspace Manager

Finally, **per-folder settings that actually work** in VS Code and Cursor multi-folder workspaces.

## The Problem

VS Code and Cursor have a frustrating limitation: **`folders[].settings` in workspace files are largely ignored**. Despite the official schema supporting per-folder settings, most settings simply don't work there.

The only reliable way to have different settings per folder? Maintain separate `.vscode/settings.json` files in each folder. This creates a maintenance nightmare:

- Settings are scattered across multiple files
- No single source of truth for your workspace configuration
- Easy to forget which folder has which overrides
- Difficult to share consistent settings across a team

## The Solution

**Workspace Manager** bridges this gap with automatic bidirectional synchronization:

1. **Define all settings in one place** — your `.code-workspace` file
2. **Per-folder overrides work** — use `folders[].settings` as intended
3. **Automatic sync** — changes propagate to `.vscode/settings.json` files instantly
4. **Use the Settings UI freely** — folder tab changes sync back to your workspace file

Keep your configuration centralized, version-controlled, and maintainable — while VS Code/Cursor gets the `.vscode/settings.json` files it needs.

## Features

- **Simple setup** — enable auto-sync via status bar or command palette, then it works automatically
- **Bidirectional sync** — changes flow both ways automatically
- **Smart merging** — deep merge for nested objects, with `null` to unset inherited values
- **Pattern-based exclusions** — control exactly which settings sync using glob patterns
- **Per-folder control** — enable/disable reverse sync per folder
- **Settings UI integration** — all options available in the standard Settings interface

## How It Works

### Forward Sync (Workspace → Folders)

When you edit the workspace file, settings are merged in this order:

```
Root settings → subFolderSettings.defaults → filter rootSettings.exclude → folders[].settings → output
```

1. Root `settings` are merged with `sync.subFolderSettings.defaults`
2. Settings matching `sync.rootSettings.exclude` patterns are filtered out (preventing inheritance)
3. Folder-specific `folders[].settings` are merged on top (can re-add excluded settings)
4. The result is written to `<folder>/.vscode/settings.json`

Settings with value `null` in folder settings are removed from the output (useful for unsetting inherited values).

### Reverse Sync (Folders → Workspace)

When you change settings via the Settings UI (selecting a folder tab like "Backend Folder"):

1. The extension detects changes to `.vscode/settings.json`
2. It calculates what changed compared to what forward sync would produce
3. Those changes are written back to `folders[].settings` in the workspace file

This means you can use the Settings UI normally — your changes won't be lost on the next sync.

## Installation

1. Download the `.vsix` file
2. In Cursor/VS Code: `Cmd+Shift+P` → "Extensions: Install from VSIX..."
3. Select the `.vsix` file and reload

Or via terminal:

```bash
cursor --install-extension workspace-manager-0.1.0.vsix
```

## Configuration

All settings are available in **Settings → Workspace → Extensions → Workspace Manager**.

### Options

| Setting                                               | Default | Where           | Precedence                 | Description                                                    |
| ----------------------------------------------------- | ------- | --------------- | -------------------------- | -------------------------------------------------------------- |
| `workspaceManager.enabled`                            | `true`  | Root only       | Root → Default             | Master toggle for the extension                                |
| `workspaceManager.autoSync.enabled`                   | `false` | Root only       | Root → Default             | Enable automatic sync via file watchers                        |
| `workspaceManager.sync.enabled`                       | `true`  | Root only       | Root → Default             | Enable forward sync                                            |
| `workspaceManager.sync.rootSettings.exclude`          | `[]`    | Root only       | Root → Default             | Patterns to NOT inherit from root (folders can still add them) |
| `workspaceManager.sync.subFolderSettings.defaults`    | `{}`    | Root only       | Root → Default             | Default settings for all subfolders                            |
| `workspaceManager.reverseSync.enabled`                | `true`  | Root and Folder | Folder → Root → Default    | Enable reverse sync                                            |
| `workspaceManager.reverseSync.folderSettings.exclude` | `[]`    | Root and Folder | **Merged** (folder + root) | Patterns to exclude from reverse sync                          |

### Per-Folder Settings

The `reverseSync` settings can be configured per-folder:

- In Settings UI, select a folder tab (e.g., "Backend Folder")
- Override `reverseSync.enabled` to disable reverse sync for specific folders
- Add folder-specific `reverseSync.folderSettings.exclude` patterns (merged with root patterns)

## Pattern Matching

Exclude patterns use [picomatch](https://github.com/micromatch/picomatch) syntax with `!` negation support.

### Pattern Examples

| Pattern      | Matches                                                    | Doesn't Match                           |
| ------------ | ---------------------------------------------------------- | --------------------------------------- |
| `editor*`    | `editor`, `editor.fontSize`, `editor.stickyScroll.enabled` | `workbench.editor.x`                    |
| `editor.*`   | `editor.fontSize`, `editor.tabSize`                        | `editor`, `editor.stickyScroll.enabled` |
| `editor.**`  | `editor.fontSize`, `editor.stickyScroll.enabled`           | `editor`                                |
| `*editor*`   | `editor`, `editor.fontSize`, `workbench.editor.tabSizing`  | —                                       |
| `*.editor.*` | `workbench.editor.tabSizing`                               | `editor.fontSize`                       |

### Negation with `!`

Use `!` prefix to exclude a pattern from exclusion (i.e., explicitly include it):

```json
"workspaceManager.reverseSync.folderSettings.exclude": [
  "editor.stickyScroll*",        // exclude all stickyScroll settings
  "!editor.stickyScroll.enabled" // except this one (negation has priority)
]
```

Negations always take priority over regular patterns.

### "Don't Inherit" vs "Never Allow"

**Important:** `sync.rootSettings.exclude` means **"don't inherit these to subfolders"**, NOT "never allow these settings".

- Settings matching the patterns won't be inherited from root or `subFolderSettings.defaults`
- Folder-specific settings can still **explicitly add** these settings if needed
- This allows preventing unwanted inheritance while giving folders full control

## Example Configuration

```json
{
  "folders": [
    {
      "name": "Backend",
      "path": "backend",
      "settings": {
        "python.defaultInterpreterPath": ".venv/bin/python3.12",
        "workspaceManager.reverseSync.enabled": false
      }
    },
    {
      "name": "Frontend",
      "path": "frontend",
      "settings": {
        "workspaceManager.reverseSync.folderSettings.exclude": ["files.exclude"]
      }
    }
  ],
  "settings": {
    "editor.rulers": [120],
    "python.defaultInterpreterPath": ".venv/bin/python",
    "workspaceManager.sync.rootSettings.exclude": ["python.*"],
    "workspaceManager.sync.subFolderSettings.defaults": {
      "files.exclude": { ".vscode": true }
    }
  }
}
```

**What this does:**

- **All subfolders**: Get `files.exclude: { ".vscode": true }` from `subFolderSettings.defaults`
- **Root**: `python.*` settings won't be inherited (excluded via `rootSettings.exclude`)
- **Backend**: Explicitly adds `python.defaultInterpreterPath` (overriding the exclusion), reverse sync disabled
- **Frontend**: Does NOT get `python.defaultInterpreterPath` (excluded, no folder override), reverse sync excludes `files.exclude`

## Commands

Open Command Palette (`Cmd+Shift+P`) and search for:

| Command                                                 | Description               |
| ------------------------------------------------------- | ------------------------- |
| **Workspace Manager: Sync Settings to Folders**         | Manually run forward sync |
| **Workspace Manager: Sync Folder Changes to Workspace** | Manually run reverse sync |
| **Workspace Manager: Enable Auto-Sync**                 | Turn on file watchers     |
| **Workspace Manager: Disable Auto-Sync**                | Turn off file watchers    |

## Status Bar

The status bar shows current sync status:

- **WM: Auto** — Auto-sync is enabled (click to disable)
- **WM: Manual** — Auto-sync is disabled (click to enable)

## Output & Debugging

View detailed logs in **Output → Workspace Manager** panel.

## Diagnostics & Quick Fixes

The extension shows hints for common workspace configuration issues:

### Flat Settings Syntax

If you write settings using the flat `"settings.xxx"` syntax directly on a folder object:

```json
{
  "name": "Frontend",
  "path": "frontend",
  "settings.editor.fontSize": 14 // This is invalid!
}
```

The extension will show a faded hint and offer a quick fix to move it to the proper nested `settings` object:

```json
{
  "name": "Frontend",
  "path": "frontend",
  "settings": {
    "editor.fontSize": 14
  }
}
```

### Root Folder Settings

If you add a `settings` object to the folder entry that represents the workspace root (e.g., `"path": "."`), those settings are ignored by VS Code. The extension will show a hint and offer to move them to the root `settings` object.

Both diagnostics appear as faded text (like unused code) to indicate that the settings are being ignored, not that they're breaking errors. Click on the lightbulb or press `Cmd+.` to apply the quick fix.

## Deep Merge Behavior

When merging settings:

- **Objects**: Recursively merged (nested keys combined)
- **Arrays**: Replaced entirely (not concatenated)
- **`null` values**: Remove the key from output

Example:

```json
// Root settings
{ "files.exclude": { ".git": true, "node_modules": true } }

// Folder settings
{ "files.exclude": { "node_modules": false } }

// Result in .vscode/settings.json
{ "files.exclude": { ".git": true, "node_modules": false } }
```

## Tips

### Gitignore Generated Files

Since `.vscode/settings.json` files are auto-generated, consider adding them to `.gitignore`:

```
**/.vscode/settings.json
```

Your `.code-workspace` file becomes the single source of truth that you commit.

### Preventing Inheritance

Three ways to control which settings appear in folder output:

**Option 1: `null` value** — removes for a **specific folder**

```json
{
  "folders": [
    {
      "path": "frontend",
      "settings": {
        "python.defaultInterpreterPath": null // Won't appear in frontend/.vscode/settings.json
      }
    },
    {
      "path": "backend"
      // backend still gets python.defaultInterpreterPath from root
    }
  ],
  "settings": {
    "python.defaultInterpreterPath": ".venv/bin/python"
  }
}
```

**Option 2: `rootSettings.exclude`** — don't inherit, but folders can override

```json
{
  "settings": {
    "python.defaultInterpreterPath": ".venv/bin/python",
    "workspaceManager.sync.rootSettings.exclude": ["python.*"]
  },
  "folders": [
    {
      "path": "backend",
      "settings": {
        "python.defaultInterpreterPath": ".venv/bin/python3.12" // Explicitly added
      }
    },
    {
      "path": "frontend"
      // Does NOT get python.defaultInterpreterPath
    }
  ]
}
```

**Option 3: `subFolderSettings.defaults`** — add defaults for all subfolders

```json
{
  "settings": {
    "workspaceManager.sync.subFolderSettings.defaults": {
      "files.exclude": { ".vscode": true }
    }
  }
}
```

Use `null` for per-folder exceptions, `rootSettings.exclude` to prevent inheritance (folders can override), and `subFolderSettings.defaults` for subfolder-only defaults.
