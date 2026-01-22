/**
 * Forward sync service
 *
 * Generates .vscode/settings.json files from workspace root settings
 * merged with folder-specific settings.
 */

import * as vscode from 'vscode';
import * as fs from 'fs/promises';
import * as path from 'path';
import { WorkspaceConfigService } from './workspaceConfig';
import { SettingsMerger } from './settingsMerger';
import { PatternMatcher } from '../utils/patternMatcher';
import { SETTINGS_KEYS, WORKSPACE_MANAGER_PREFIX, type Settings } from '../types';

export class ForwardSyncService {
  private workspaceConfig: WorkspaceConfigService;
  private merger: SettingsMerger;
  private outputChannel: vscode.OutputChannel;

  constructor(workspaceConfig: WorkspaceConfigService, outputChannel: vscode.OutputChannel) {
    this.workspaceConfig = workspaceConfig;
    this.merger = new SettingsMerger();
    this.outputChannel = outputChannel;
  }

  /**
   * Perform forward sync for all folders
   */
  async sync(): Promise<number> {
    const workspace = await this.workspaceConfig.load();
    const globalSettings = workspace.settings;

    // Check if extension is enabled
    if (globalSettings[SETTINGS_KEYS.enabled] === false) {
      this.outputChannel.appendLine('Forward sync skipped: extension disabled');
      return 0;
    }

    // Check if forward sync is enabled
    if (globalSettings[SETTINGS_KEYS.syncEnabled] === false) {
      this.outputChannel.appendLine('Forward sync skipped: sync.enabled is false');
      return 0;
    }

    // Get exclude patterns
    const excludePatterns = (globalSettings[SETTINGS_KEYS.syncExcludePatterns] as string[]) ?? [];
    const matcher = new PatternMatcher(excludePatterns);

    // Filter global settings (remove excluded patterns and workspaceManager.* keys)
    const filteredGlobalSettings = this.filterGlobalSettings(globalSettings, matcher);

    let syncedCount = 0;

    for (const folder of workspace.folders) {
      // Skip root folder
      if (folder.path === '.') {
        this.outputChannel.appendLine(`Skipping root folder`);
        continue;
      }

      // Skip folders without settings key
      if (folder.settings === undefined) {
        this.outputChannel.appendLine(
          `Skipping folder "${folder.name || folder.path}": no settings`
        );
        continue;
      }

      try {
        // Merge global settings with folder settings
        const mergedSettings = this.merger.merge(filteredGlobalSettings, folder.settings);

        // Remove workspaceManager.* keys from output
        const cleanedSettings = this.removeWorkspaceManagerKeys(mergedSettings);

        // Write to .vscode/settings.json
        await this.writeSettingsJson(folder.path, cleanedSettings);

        this.outputChannel.appendLine(
          `Synced settings to ${folder.name || folder.path}/.vscode/settings.json`
        );
        syncedCount++;
      } catch (error) {
        this.outputChannel.appendLine(
          `Error syncing ${folder.name || folder.path}: ${error instanceof Error ? error.message : String(error)}`
        );
      }
    }

    return syncedCount;
  }

  /**
   * Filter global settings, removing excluded patterns and workspaceManager.* keys
   */
  private filterGlobalSettings(settings: Settings, matcher: PatternMatcher): Settings {
    const result: Settings = {};

    for (const [key, value] of Object.entries(settings)) {
      // Skip workspaceManager.* keys
      if (key.startsWith(WORKSPACE_MANAGER_PREFIX)) {
        continue;
      }

      // Skip keys matching exclude patterns
      if (matcher.isExcluded(key)) {
        continue;
      }

      result[key] = value;
    }

    return result;
  }

  /**
   * Remove all workspaceManager.* keys from settings
   */
  private removeWorkspaceManagerKeys(settings: Settings): Settings {
    const result: Settings = {};

    for (const [key, value] of Object.entries(settings)) {
      if (!key.startsWith(WORKSPACE_MANAGER_PREFIX)) {
        result[key] = value;
      }
    }

    return result;
  }

  /**
   * Write settings to a folder's .vscode/settings.json
   */
  private async writeSettingsJson(folderPath: string, settings: Settings): Promise<void> {
    const resolvedPath = this.workspaceConfig.resolveFolderPath(folderPath);
    const vscodeDir = path.join(resolvedPath, '.vscode');
    const settingsFile = path.join(vscodeDir, 'settings.json');

    // Create .vscode directory if it doesn't exist
    await fs.mkdir(vscodeDir, { recursive: true });

    // Write settings.json with proper formatting
    const content = JSON.stringify(settings, null, 4) + '\n';
    await fs.writeFile(settingsFile, content, 'utf-8');
  }
}
