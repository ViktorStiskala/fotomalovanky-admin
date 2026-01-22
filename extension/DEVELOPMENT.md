# Development Guide

## Prerequisites

- Node.js 20+
- npm

## Setup

```bash
cd extension
npm install
```

## Development

### Build

```bash
npm run build
```

### Watch Mode

Automatically rebuilds on file changes:

```bash
npm run watch
```

### Type Checking

```bash
npm run check-types
```

### Format Code

```bash
npm run format
```

### Run All Checks

```bash
npm run check
```

## Testing Locally (Extension Development Host)

1. Open the `extension/` folder in VS Code/Cursor
2. Press `F5` or go to **Run → Start Debugging**
3. Select **Run Extension** from the dropdown
4. A new VS Code window (Extension Development Host) will open with the extension loaded

In the Extension Development Host:

- Open a workspace with a `.code-workspace` file
- Check **Output → Workspace Manager** for logs
- Use Command Palette (`Cmd+Shift+P`) to run Workspace Manager commands
- Check the status bar for sync status (WM: Auto / WM: Manual)

### Debug Configuration

The debug configuration is in `.vscode/launch.json`. It runs `npm run build` before launching.

## Packaging for Distribution

### Install vsce (VS Code Extension Manager)

```bash
npm install -g @vscode/vsce
```

### Create .vsix Package

```bash
npm run package
```

Or manually:

```bash
vsce package --allow-missing-repository --skip-license
```

This creates `workspace-manager-{version}.vsix` in the extension folder.

### Install the Package

In VS Code/Cursor:

```bash
cursor --install-extension workspace-manager-0.1.0.vsix
```

Or via UI: `Cmd+Shift+P` → "Extensions: Install from VSIX..."

## Project Structure

```
extension/
├── src/
│   ├── extension.ts              # Entry point, activation, commands
│   ├── types.ts                  # TypeScript interfaces and constants
│   ├── services/
│   │   ├── workspaceConfig.ts    # Read/write workspace file (JSON5)
│   │   ├── settingsMerger.ts     # Deep merge with null removal
│   │   ├── forwardSync.ts        # Root settings → folder .vscode/settings.json
│   │   ├── reverseSync.ts        # Folder settings → workspace folders[].settings
│   │   └── fileWatcher.ts        # Watch both directions with debounce
│   └── utils/
│       └── patternMatcher.ts     # picomatch wrapper with ! negation
├── dist/                         # Build output (gitignored)
├── package.json                  # Extension manifest and scripts
├── tsconfig.json                 # TypeScript configuration
├── esbuild.js                    # Build script
└── .vscodeignore                 # Files to exclude from package
```

## Scripts Reference

| Script                 | Description                        |
| ---------------------- | ---------------------------------- |
| `npm run build`        | Build with esbuild                 |
| `npm run watch`        | Build in watch mode                |
| `npm run check-types`  | TypeScript type checking           |
| `npm run format`       | Format with Prettier               |
| `npm run format:check` | Check formatting                   |
| `npm run check`        | Run type checking and format check |
| `npm run compile`      | Type check + build                 |
| `npm run package`      | Create .vsix package               |

## Dependencies

- **json5** — Parse workspace files with trailing commas and comments
- **picomatch** — Glob pattern matching with negation support
