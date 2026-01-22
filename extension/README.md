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

- **Zero configuration** — works out of the box, just install and open your workspace
- **Bidirectional sync** — changes flow both ways automatically
- **Smart merging** — deep merge for nested objects, with `null` to unset inherited values
- **Pattern-based exclusions** — control exactly which settings sync using glob patterns
- **Per-folder control** — enable/disable reverse sync per folder
- **Settings UI integration** — all options available in the standard Settings interface

## How It Works

### Forward Sync (Workspace → Folders)

When you edit the workspace file:
1. Root `settings` are merged with each folder's `folders[].settings`
2. The merged result is written to `<folder>/.vscode/settings.json`
3. Settings with value `null` in folder settings are removed from the output (useful for unsetting inherited values)

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

| Setting | Default | Description |
|---------|---------|-------------|
| `workspaceManager.enabled` | `true` | Master toggle for the extension |
| `workspaceManager.autoSync` | `true` | Enable automatic sync via file watchers |
| `workspaceManager.sync.enabled` | `true` | Enable forward sync |
| `workspaceManager.sync.excludePatterns` | `[]` | Patterns to exclude from forward sync |
| `workspaceManager.reverseSync.enabled` | `true` | Enable reverse sync |
| `workspaceManager.reverseSync.excludePatterns` | `[]` | Patterns to exclude from reverse sync |

### Per-Folder Settings

The `reverseSync` settings can be configured per-folder:

- In Settings UI, select a folder tab (e.g., "Backend Folder")
- Override `reverseSync.enabled` to disable reverse sync for specific folders
- Add folder-specific `reverseSync.excludePatterns`

## Setting Precedence

| Setting | Where It Can Be Set | Precedence |
|---------|---------------------|------------|
| `enabled`, `autoSync`, `sync.*` | Root only | Root → Default |
| `reverseSync.enabled` | Root and Folder | Folder → Root → Default |
| `reverseSync.excludePatterns` | Root and Folder | **Merged** (folder + root) |

For `reverseSync.excludePatterns`, patterns from both root and folder are combined. This lets you define global exclusions at the root level and add folder-specific ones.

## Pattern Matching

Exclude patterns use [picomatch](https://github.com/micromatch/picomatch) syntax with `!` negation support.

### Pattern Examples

| Pattern | Matches | Doesn't Match |
|---------|---------|---------------|
| `editor*` | `editor`, `editor.fontSize`, `editor.stickyScroll.enabled` | `workbench.editor.x` |
| `editor.*` | `editor.fontSize`, `editor.tabSize` | `editor`, `editor.stickyScroll.enabled` |
| `editor.**` | `editor.fontSize`, `editor.stickyScroll.enabled` | `editor` |
| `*editor*` | `editor`, `editor.fontSize`, `workbench.editor.tabSizing` | — |
| `*.editor.*` | `workbench.editor.tabSizing` | `editor.fontSize` |

### Negation with `!`

Use `!` prefix to exclude a pattern from exclusion (i.e., explicitly include it):

```json
"workspaceManager.reverseSync.excludePatterns": [
  "editor.stickyScroll*",        // exclude all stickyScroll settings
  "!editor.stickyScroll.enabled" // except this one (negation has priority)
]
```

Negations always take priority over regular patterns.

## Example Configuration

```json
{
  "folders": [
    {
      "name": "Backend",
      "path": "backend",
      "settings": {
        "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
        "workspaceManager.reverseSync.enabled": false
      }
    },
    {
      "name": "Frontend",
      "path": "frontend",
      "settings": {
        "python.defaultInterpreterPath": null,
        "workspaceManager.reverseSync.excludePatterns": ["files.exclude"]
      }
    }
  ],
  "settings": {
    "editor.rulers": [120],
    "cursor.composer.shouldAutoAcceptDiffs": true,
    "workspaceManager.sync.excludePatterns": ["cursor.composer.*"]
  }
}
```

**What this does:**

- **Backend**: Reverse sync is disabled — UI changes won't sync back to workspace file
- **Frontend**: All settings sync back except `files.exclude`
- **Root**: `cursor.composer.*` settings won't propagate to any folder's `.vscode/settings.json`

## Commands

Open Command Palette (`Cmd+Shift+P`) and search for:

| Command | Description |
|---------|-------------|
| **Workspace Manager: Sync Settings to Folders** | Manually run forward sync |
| **Workspace Manager: Sync Folder Changes to Workspace** | Manually run reverse sync |
| **Workspace Manager: Enable Auto-Sync** | Turn on file watchers |
| **Workspace Manager: Disable Auto-Sync** | Turn off file watchers |

## Status Bar

The status bar shows current sync status:

- **WM: Auto** — Auto-sync is enabled (click to disable)
- **WM: Manual** — Auto-sync is disabled (click to enable)

## Output & Debugging

View detailed logs in **Output → Workspace Manager** panel.

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

### Removing Inherited Settings

Two ways to prevent root settings from appearing in folder output:

**Option 1: `null` value** — removes for a **specific folder**

```json
{
  "folders": [
    {
      "path": "frontend",
      "settings": {
        "python.defaultInterpreterPath": null  // Won't appear in frontend/.vscode/settings.json
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

**Option 2: `excludePatterns`** — excludes from **all folders**

```json
{
  "settings": {
    "workspaceManager.sync.excludePatterns": ["cursor.general.globalCursorIgnoreList"]
    // No folder will get this setting in their .vscode/settings.json
  }
}
```

Use `null` for per-folder exceptions, use `excludePatterns` for global exclusions.
