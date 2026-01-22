# Auto-Sync with Forward Sync Disabled

## The Issue

You have `workspaceManager.autoSync.enabled` set to `true`, but `workspaceManager.sync.enabled` is set to `false`. This means auto-sync is watching for changes, but forward sync won't run.

## Example Configuration

```json
{
  "folders": [{ "name": "Backend", "path": "backend" }],
  "settings": {
    "workspaceManager.sync.enabled": false,
    "workspaceManager.autoSync.enabled": true,
    "editor.fontSize": 14
  }
}
```

## What Actually Happens

With this configuration:

- **Forward sync is skipped**: Changes you make in the workspace file (root `settings` or `folders[].settings`) will NOT be written to `.vscode/settings.json` files
- **Reverse sync still runs**: If you change settings via the Settings UI (selecting a folder tab), those changes will be synced back to the workspace file

In essence: **Workspace file → Folders** is disabled, but **Folders → Workspace file** still works.

## When This Might Be Intentional

This configuration makes sense if you want to:

1. **Manually manage folder settings**: You create and edit `.vscode/settings.json` files yourself
2. **Only use reverse sync**: You want folder changes to sync back to the workspace file, but not the other way around
3. **Prevent overwriting existing folder settings**: You have custom `.vscode/settings.json` files you don't want to lose

## When This Is Probably a Mistake

This is likely unintentional if you:

- Expect changes to the workspace file to propagate to folders
- Set up `sync.rootSettings.exclude` or `sync.subFolderSettings.defaults` (they have no effect when sync is disabled)
- Wonder why your folder settings don't match your workspace file

## The "No Effect" Scenario

If you also have reverse sync disabled for all folders:

```json
{
  "settings": {
    "workspaceManager.sync.enabled": false,
    "workspaceManager.autoSync.enabled": true,
    "workspaceManager.reverseSync.enabled": false
  }
}
```

Auto-sync will have **no effect at all**:

- Forward sync is disabled
- Reverse sync is disabled for all folders
- The file watchers are running but doing nothing

The extension will show a warning: "Auto-Sync will have no effect, as both forwardSync and reverseSync are disabled."

## How to Fix

### If You Want Bidirectional Sync

Enable forward sync:

```json
{
  "settings": {
    "workspaceManager.sync.enabled": true,
    "workspaceManager.autoSync.enabled": true
  }
}
```

### If You Only Want Reverse Sync

This is valid! Just be aware that:

- You need to manually manage `.vscode/settings.json` files
- Make sure at least some folders have `reverseSync.enabled: true` (the default)

### If You Don't Want Any Sync

Disable auto-sync entirely:

```json
{
  "settings": {
    "workspaceManager.autoSync.enabled": false
  }
}
```

Or use the status bar to disable auto-sync (click "WM: Auto" to switch to "WM: Manual").

## Diagnostic Severity

This diagnostic is shown as a **Hint** (not an error or warning) because this configuration might be intentional. It's informational - the extension is letting you know how your configuration will behave.

No Quick Fix is provided because the correct action depends on your intent.
