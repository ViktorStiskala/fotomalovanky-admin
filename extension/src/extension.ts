/**
 * Workspace Manager Extension
 *
 * Bidirectional sync between workspace file and folder settings
 */

import * as vscode from 'vscode';
import { WorkspaceConfigService } from './services/workspaceConfig';
import { ForwardSyncService } from './services/forwardSync';
import { ReverseSyncService } from './services/reverseSync';
import { FileWatcherService } from './services/fileWatcher';
import { DiagnosticsService } from './services/diagnostics';
import { WorkspaceCodeActionProvider } from './services/codeActions';
import { SETTINGS_KEYS, type WorkspaceFile } from './types';
import { initQuickFixHint } from './utils/quickFixHint';

let outputChannel: vscode.OutputChannel;
let statusBarItem: vscode.StatusBarItem;
let workspaceConfig: WorkspaceConfigService;
let forwardSync: ForwardSyncService;
let reverseSync: ReverseSyncService;
let fileWatcher: FileWatcherService;
let diagnosticsService: DiagnosticsService;

/**
 * Extension activation
 */
export async function activate(context: vscode.ExtensionContext): Promise<void> {
  // Create output channel for logging
  outputChannel = vscode.window.createOutputChannel('Workspace Manager');
  outputChannel.appendLine('Workspace Manager activating...');

  // Initialize workspace config service
  workspaceConfig = new WorkspaceConfigService();

  if (!workspaceConfig.hasWorkspaceFile()) {
    outputChannel.appendLine('No workspace file found - extension will not activate');
    return;
  }

  outputChannel.appendLine(`Workspace file: ${workspaceConfig.getWorkspacePath()}`);

  // Initialize Quick Fix hint (cache keybinding for diagnostic messages)
  await initQuickFixHint();

  // Initialize services
  forwardSync = new ForwardSyncService(workspaceConfig, outputChannel);
  reverseSync = new ReverseSyncService(workspaceConfig, outputChannel);
  diagnosticsService = new DiagnosticsService(workspaceConfig, outputChannel);
  fileWatcher = new FileWatcherService(
    workspaceConfig,
    forwardSync,
    reverseSync,
    diagnosticsService,
    outputChannel
  );

  // Create status bar item
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.command = 'workspaceManager.enableAutoSync';
  context.subscriptions.push(statusBarItem);

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('workspaceManager.syncForward', handleSyncForward),
    vscode.commands.registerCommand('workspaceManager.syncReverse', handleSyncReverse),
    vscode.commands.registerCommand('workspaceManager.enableAutoSync', handleEnableAutoSync),
    vscode.commands.registerCommand('workspaceManager.disableAutoSync', handleDisableAutoSync)
  );

  // Register code action provider for quick fixes
  const codeActionProvider = new WorkspaceCodeActionProvider(workspaceConfig);
  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      { pattern: '**/*.code-workspace' },
      codeActionProvider,
      { providedCodeActionKinds: WorkspaceCodeActionProvider.providedCodeActionKinds }
    )
  );

  // Register disposables
  context.subscriptions.push(outputChannel);
  context.subscriptions.push({ dispose: () => fileWatcher.dispose() });
  context.subscriptions.push({ dispose: () => diagnosticsService.dispose() });

  // Listen for configuration changes
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('workspaceManager')) {
        handleConfigurationChange();
      }
    })
  );

  // Listen for workspace file document changes to refresh diagnostics immediately
  // This ensures diagnostics update when edits are applied (before file is saved)
  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((e) => {
      const workspacePath = workspaceConfig.getWorkspacePath();
      if (workspacePath && e.document.uri.fsPath === workspacePath) {
        // Debounce diagnostics refresh
        diagnosticsService.validate();
      }
    })
  );

  // Initialize based on current settings
  await initialize();

  outputChannel.appendLine('Workspace Manager activated');
}

/**
 * Extension deactivation
 */
export function deactivate(): void {
  fileWatcher?.dispose();
  outputChannel?.appendLine('Workspace Manager deactivated');
}

/**
 * Initialize the extension based on current settings
 */
async function initialize(): Promise<void> {
  try {
    // Run diagnostics validation on initialization
    await diagnosticsService.validate();

    const workspace = await workspaceConfig.load();
    const autoSync = workspace.settings[SETTINGS_KEYS.autoSyncEnabled] === true;

    if (autoSync) {
      fileWatcher.startWatching();
      updateStatusBar(true);

      // Check for configuration warnings
      await checkAutoSyncWarnings();

      // Perform initial forward sync
      outputChannel.appendLine('Performing initial forward sync...');
      await forwardSync.sync();
    } else {
      updateStatusBar(false);
    }
  } catch (error) {
    outputChannel.appendLine(
      `Initialization error: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Handle configuration changes
 */
async function handleConfigurationChange(): Promise<void> {
  outputChannel.appendLine('Configuration changed');

  try {
    const workspace = await workspaceConfig.load();
    const autoSync = workspace.settings[SETTINGS_KEYS.autoSyncEnabled] === true;

    if (autoSync && !fileWatcher.isActive()) {
      fileWatcher.startWatching();
      updateStatusBar(true);

      // Check for configuration warnings when autoSync transitions to enabled
      await checkAutoSyncWarnings();
    } else if (!autoSync && fileWatcher.isActive()) {
      fileWatcher.stopWatching();
      updateStatusBar(false);
    }
  } catch (error) {
    outputChannel.appendLine(
      `Configuration change error: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Check if ALL folders have reverseSync effectively disabled
 */
function checkAllFoldersReverseSyncDisabled(workspace: WorkspaceFile): boolean {
  const rootReverseSyncEnabled = workspace.settings[SETTINGS_KEYS.reverseSyncEnabled] !== false;

  for (const folder of workspace.folders) {
    const folderReverseSyncEnabled = folder.settings?.[SETTINGS_KEYS.reverseSyncEnabled];
    // Folder is enabled if: explicit true, OR undefined and root is enabled
    const isEnabled = folderReverseSyncEnabled ?? rootReverseSyncEnabled;
    if (isEnabled) {
      return false; // At least one folder has reverseSync enabled
    }
  }

  return true; // All folders have reverseSync disabled
}

/**
 * Check configuration and show warning when enabling autoSync with issues
 */
async function checkAutoSyncWarnings(): Promise<void> {
  try {
    const workspace = await workspaceConfig.load();
    const forwardSyncEnabled = workspace.settings[SETTINGS_KEYS.syncEnabled] !== false;
    const allReverseSyncDisabled = checkAllFoldersReverseSyncDisabled(workspace);

    if (!forwardSyncEnabled && allReverseSyncDisabled) {
      // Both disabled - no effect
      vscode.window.showWarningMessage(
        'Auto-Sync will have no effect, as both forwardSync and reverseSync are disabled.'
      );
    } else if (!forwardSyncEnabled) {
      // Forward disabled, some reverseSync works
      vscode.window.showWarningMessage(
        'Forward sync is disabled.\n\nAuto-Sync will only sync folder setting changes to Workspace.'
      );
    }
  } catch (error) {
    outputChannel.appendLine(
      `Check auto-sync warnings error: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Update status bar item
 */
function updateStatusBar(isAutoSyncEnabled: boolean): void {
  if (isAutoSyncEnabled) {
    statusBarItem.text = '$(sync) WM: Auto';
    statusBarItem.tooltip = 'Workspace Manager: Auto-sync enabled. Click to disable.';
    statusBarItem.command = 'workspaceManager.disableAutoSync';
  } else {
    statusBarItem.text = '$(sync-ignored) WM: Manual';
    statusBarItem.tooltip = 'Workspace Manager: Auto-sync disabled. Click to enable.';
    statusBarItem.command = 'workspaceManager.enableAutoSync';
  }
  statusBarItem.show();
}

/**
 * Command: Sync Settings to Folders (forward sync)
 */
async function handleSyncForward(): Promise<void> {
  outputChannel.appendLine('Manual forward sync triggered');

  try {
    const count = await forwardSync.sync();
    if (count > 0) {
      vscode.window.showInformationMessage(
        `Workspace Manager: Synced settings to ${count} folder(s)`
      );
    } else {
      vscode.window.showInformationMessage('Workspace Manager: Settings already up to date');
    }
  } catch (error) {
    outputChannel.appendLine(
      `Forward sync error: ${error instanceof Error ? error.message : String(error)}`
    );
    vscode.window.showErrorMessage(
      `Workspace Manager: Sync failed - ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Command: Sync Folder Changes to Workspace (reverse sync)
 */
async function handleSyncReverse(): Promise<void> {
  outputChannel.appendLine('Manual reverse sync triggered');

  try {
    const folders = await workspaceConfig.getFolders();

    if (folders.length === 0) {
      vscode.window.showInformationMessage('Workspace Manager: No folders to sync');
      return;
    }

    let syncedCount = 0;
    for (const folder of folders) {
      const success = await reverseSync.syncFolderToWorkspace(folder.path);
      if (success) {
        syncedCount++;
      }
    }

    if (syncedCount > 0) {
      vscode.window.showInformationMessage(
        `Workspace Manager: Synced changes from ${syncedCount} folder(s)`
      );
    } else {
      vscode.window.showInformationMessage('Workspace Manager: No changes to sync');
    }
  } catch (error) {
    outputChannel.appendLine(
      `Reverse sync error: ${error instanceof Error ? error.message : String(error)}`
    );
    vscode.window.showErrorMessage(
      `Workspace Manager: Sync failed - ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Command: Enable Auto-Sync
 */
async function handleEnableAutoSync(): Promise<void> {
  outputChannel.appendLine('Enabling auto-sync');

  try {
    const workspace = await workspaceConfig.load();
    workspace.settings[SETTINGS_KEYS.autoSyncEnabled] = true;
    await workspaceConfig.save(workspace);

    fileWatcher.startWatching();
    updateStatusBar(true);

    vscode.window.showInformationMessage('Workspace Manager: Auto-sync enabled');

    // Check for configuration warnings after enabling
    await checkAutoSyncWarnings();
  } catch (error) {
    outputChannel.appendLine(
      `Enable auto-sync error: ${error instanceof Error ? error.message : String(error)}`
    );
    vscode.window.showErrorMessage(
      `Workspace Manager: Failed to enable auto-sync - ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Command: Disable Auto-Sync
 */
async function handleDisableAutoSync(): Promise<void> {
  outputChannel.appendLine('Disabling auto-sync');

  try {
    const workspace = await workspaceConfig.load();
    workspace.settings[SETTINGS_KEYS.autoSyncEnabled] = false;
    await workspaceConfig.save(workspace);

    fileWatcher.stopWatching();
    updateStatusBar(false);

    vscode.window.showInformationMessage('Workspace Manager: Auto-sync disabled');
  } catch (error) {
    outputChannel.appendLine(
      `Disable auto-sync error: ${error instanceof Error ? error.message : String(error)}`
    );
    vscode.window.showErrorMessage(
      `Workspace Manager: Failed to disable auto-sync - ${error instanceof Error ? error.message : String(error)}`
    );
  }
}
