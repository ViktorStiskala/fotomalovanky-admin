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
   *
   * Merge order: Root settings → subFolderSettings.defaults → filter rootSettings.exclude → folders[].settings → output
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

    // Get subFolderSettings.defaults and exclude patterns
    const subFolderDefaults =
      (globalSettings[SETTINGS_KEYS.syncSubFolderSettingsDefaults] as Settings) ?? {};
    const excludePatterns =
      (globalSettings[SETTINGS_KEYS.syncRootSettingsExclude] as string[]) ?? [];
    const matcher = new PatternMatcher(excludePatterns);

    let syncedCount = 0;

    for (const folder of workspace.folders) {
      // Skip root folder (comparing resolved paths)
      const isRoot = await this.workspaceConfig.isWorkspaceRoot(folder.path);
      if (isRoot) {
        this.outputChannel.appendLine(`Skipping root folder`);
        continue;
      }

      try {
        // 1. Remove workspaceManager.* keys from root
        const rootWithoutWM = this.removeWorkspaceManagerKeys(globalSettings);

        // 2. Merge root → subFolderSettings.defaults
        const withDefaults = this.merger.merge(rootWithoutWM, subFolderDefaults);

        // 3. Apply exclude patterns (prevents inheritance, but folders can re-add)
        const filtered = this.filterByPatterns(withDefaults, matcher);

        // 4. Merge with folder settings (folder has final say)
        const merged = this.merger.merge(filtered, folder.settings ?? {});

        // 5. Remove any remaining workspaceManager.* keys and write
        const cleaned = this.removeWorkspaceManagerKeys(merged);

        // Write to .vscode/settings.json
        await this.writeSettingsJson(folder.path, cleaned);

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
   * Filter settings by exclude patterns (excludePatterns = "don't inherit")
   */
  private filterByPatterns(settings: Settings, matcher: PatternMatcher): Settings {
    const result: Settings = {};

    for (const [key, value] of Object.entries(settings)) {
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
    const resolvedPath = await this.workspaceConfig.resolveFolderPath(folderPath);
    const vscodeDir = path.join(resolvedPath, '.vscode');
    const settingsFile = path.join(vscodeDir, 'settings.json');

    // Create .vscode directory if it doesn't exist
    await fs.mkdir(vscodeDir, { recursive: true });

    // Write settings.json with proper formatting
    const content = JSON.stringify(settings, null, 4) + '\n';
    await fs.writeFile(settingsFile, content, 'utf-8');
  }
}
