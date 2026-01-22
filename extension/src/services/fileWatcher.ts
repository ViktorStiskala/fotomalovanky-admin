/**
 * File watcher service
 *
 * Watches workspace and folder settings files for changes
 * with debouncing and sync loop prevention.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import { ForwardSyncService } from './forwardSync';
import { ReverseSyncService } from './reverseSync';
import { WorkspaceConfigService } from './workspaceConfig';
import { DiagnosticsService } from './diagnostics';
import { SETTINGS_KEYS } from '../types';

export class FileWatcherService {
  private workspaceConfig: WorkspaceConfigService;
  private forwardSync: ForwardSyncService;
  private reverseSync: ReverseSyncService;
  private diagnosticsService: DiagnosticsService;
  private outputChannel: vscode.OutputChannel;

  private isForwardSyncing = false;
  private isReverseSyncing = false;
  private debounceTimeout: NodeJS.Timeout | null = null;
  private debounceMs = 300;

  private disposables: vscode.Disposable[] = [];
  private isWatching = false;

  constructor(
    workspaceConfig: WorkspaceConfigService,
    forwardSync: ForwardSyncService,
    reverseSync: ReverseSyncService,
    diagnosticsService: DiagnosticsService,
    outputChannel: vscode.OutputChannel
  ) {
    this.workspaceConfig = workspaceConfig;
    this.forwardSync = forwardSync;
    this.reverseSync = reverseSync;
    this.diagnosticsService = diagnosticsService;
    this.outputChannel = outputChannel;
  }

  /**
   * Start watching for file changes
   */
  startWatching(): void {
    if (this.isWatching) {
      return;
    }

    this.outputChannel.appendLine('Starting file watchers...');

    // Watch workspace file
    this.disposables.push(this.watchWorkspaceFile());

    // Watch folder settings files
    this.disposables.push(this.watchFolderSettings());

    this.isWatching = true;
    this.outputChannel.appendLine('File watchers started');
  }

  /**
   * Stop watching for file changes
   */
  stopWatching(): void {
    if (!this.isWatching) {
      return;
    }

    this.outputChannel.appendLine('Stopping file watchers...');

    for (const disposable of this.disposables) {
      disposable.dispose();
    }
    this.disposables = [];

    if (this.debounceTimeout) {
      clearTimeout(this.debounceTimeout);
      this.debounceTimeout = null;
    }

    this.isWatching = false;
    this.outputChannel.appendLine('File watchers stopped');
  }

  /**
   * Check if watchers are currently active
   */
  isActive(): boolean {
    return this.isWatching;
  }

  /**
   * Dispose all watchers
   */
  dispose(): void {
    this.stopWatching();
  }

  /**
   * Watch the workspace file for changes
   */
  private watchWorkspaceFile(): vscode.Disposable {
    const watcher = vscode.workspace.createFileSystemWatcher('**/*.code-workspace');

    const onChange = async () => {
      // Always update diagnostics when workspace file changes
      await this.diagnosticsService.validate();

      // Skip sync if we're currently doing a reverse sync (we caused this change)
      if (this.isReverseSyncing) {
        this.outputChannel.appendLine(
          'Workspace file change detected, but skipping sync (reverse sync in progress)'
        );
        return;
      }

      this.outputChannel.appendLine('Workspace file change detected');
      this.debounce(() => this.triggerForwardSync());
    };

    return vscode.Disposable.from(
      watcher,
      watcher.onDidChange(onChange),
      watcher.onDidCreate(onChange)
    );
  }

  /**
   * Watch folder .vscode/settings.json files for changes
   */
  private watchFolderSettings(): vscode.Disposable {
    const watcher = vscode.workspace.createFileSystemWatcher('**/.vscode/settings.json');

    const onChange = async (uri: vscode.Uri) => {
      // Skip if we're currently doing a forward sync (we caused this change)
      if (this.isForwardSyncing) {
        this.outputChannel.appendLine(
          `Folder settings change detected at ${uri.fsPath}, but skipping (forward sync in progress)`
        );
        return;
      }

      const folderPath = this.getFolderPathFromUri(uri);
      if (!folderPath) {
        this.outputChannel.appendLine(
          `Folder settings change detected at ${uri.fsPath}, but couldn't determine folder path`
        );
        return;
      }

      this.outputChannel.appendLine(`Folder settings change detected: ${folderPath}`);
      this.debounce(() => this.triggerReverseSync(folderPath));
    };

    return vscode.Disposable.from(
      watcher,
      watcher.onDidChange(onChange),
      watcher.onDidCreate(onChange)
    );
  }

  /**
   * Get the relative folder path from a settings.json URI
   */
  private getFolderPathFromUri(uri: vscode.Uri): string | null {
    const workspaceDir = this.workspaceConfig.getWorkspaceDir();
    if (!workspaceDir) {
      return null;
    }

    // URI is like: /workspace/folder/.vscode/settings.json
    // We need to get "folder" relative to workspace
    const settingsPath = uri.fsPath;
    const vscodeDir = path.dirname(settingsPath);
    const folderAbsPath = path.dirname(vscodeDir);

    // Make relative to workspace
    const relativePath = path.relative(workspaceDir, folderAbsPath);

    // Normalize to forward slashes and handle empty string (workspace root)
    const normalized = relativePath.split(path.sep).join('/');

    return normalized || '.';
  }

  /**
   * Trigger forward sync with sync loop prevention
   */
  private async triggerForwardSync(): Promise<void> {
    // Check if auto sync is enabled
    const isAutoSyncEnabled = await this.isAutoSyncEnabled();
    if (!isAutoSyncEnabled) {
      this.outputChannel.appendLine('Forward sync skipped: autoSync is disabled');
      return;
    }

    this.isForwardSyncing = true;
    try {
      const count = await this.forwardSync.sync();
      if (count > 0) {
        vscode.window.showInformationMessage(
          `Workspace Manager: Synced settings to ${count} folder(s)`
        );
      }
    } catch (error) {
      this.outputChannel.appendLine(
        `Forward sync error: ${error instanceof Error ? error.message : String(error)}`
      );
      vscode.window.showErrorMessage(
        `Workspace Manager: Forward sync failed - ${error instanceof Error ? error.message : String(error)}`
      );
    } finally {
      this.isForwardSyncing = false;
    }
  }

  /**
   * Trigger reverse sync for a specific folder with sync loop prevention
   */
  private async triggerReverseSync(folderPath: string): Promise<void> {
    // Check if auto sync is enabled
    const isAutoSyncEnabled = await this.isAutoSyncEnabled();
    if (!isAutoSyncEnabled) {
      this.outputChannel.appendLine('Reverse sync skipped: autoSync is disabled');
      return;
    }

    this.isReverseSyncing = true;
    try {
      const success = await this.reverseSync.syncFolderToWorkspace(folderPath);
      if (success) {
        vscode.window.showInformationMessage(
          `Workspace Manager: Synced folder changes to workspace file`
        );
      }
    } catch (error) {
      this.outputChannel.appendLine(
        `Reverse sync error: ${error instanceof Error ? error.message : String(error)}`
      );
      vscode.window.showErrorMessage(
        `Workspace Manager: Reverse sync failed - ${error instanceof Error ? error.message : String(error)}`
      );
    } finally {
      this.isReverseSyncing = false;
    }
  }

  /**
   * Check if auto sync is enabled
   */
  private async isAutoSyncEnabled(): Promise<boolean> {
    try {
      const workspace = await this.workspaceConfig.load();
      const enabled = workspace.settings[SETTINGS_KEYS.enabled];
      const autoSync = workspace.settings[SETTINGS_KEYS.autoSyncEnabled];

      if (enabled === false) {
        return false;
      }

      return autoSync === true;
    } catch {
      return false; // Default to disabled
    }
  }

  /**
   * Debounce function calls
   */
  private debounce(fn: () => void): void {
    if (this.debounceTimeout) {
      clearTimeout(this.debounceTimeout);
    }
    this.debounceTimeout = setTimeout(fn, this.debounceMs);
  }
}
