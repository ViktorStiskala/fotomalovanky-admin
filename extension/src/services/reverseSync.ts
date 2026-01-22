/**
 * Reverse sync service
 *
 * Syncs UI changes from folder's .vscode/settings.json back to
 * the workspace file's folders[].settings.
 */

import * as vscode from 'vscode';
import * as fs from 'fs/promises';
import * as path from 'path';
import * as jsonc from 'jsonc-parser';
import { WorkspaceConfigService } from './workspaceConfig';
import { SettingsMerger } from './settingsMerger';
import { PatternMatcher } from '../utils/patternMatcher';
import {
  SETTINGS_KEYS,
  WORKSPACE_MANAGER_PREFIX,
  type Settings,
  type FolderConfig,
} from '../types';

export class ReverseSyncService {
  private workspaceConfig: WorkspaceConfigService;
  private merger: SettingsMerger;
  private outputChannel: vscode.OutputChannel;

  constructor(workspaceConfig: WorkspaceConfigService, outputChannel: vscode.OutputChannel) {
    this.workspaceConfig = workspaceConfig;
    this.merger = new SettingsMerger();
    this.outputChannel = outputChannel;
  }

  /**
   * Sync a folder's .vscode/settings.json back to the workspace file
   *
   * @param folderPath - The relative folder path
   */
  async syncFolderToWorkspace(folderPath: string): Promise<boolean> {
    try {
      const workspace = await this.workspaceConfig.load();
      const folder = workspace.folders.find((f) => f.path === folderPath);

      if (!folder) {
        this.outputChannel.appendLine(`Reverse sync skipped: folder not found - ${folderPath}`);
        return false;
      }

      // Skip root folder (comparing resolved paths)
      const isRoot = await this.workspaceConfig.isWorkspaceRoot(folderPath);
      if (isRoot) {
        this.outputChannel.appendLine('Reverse sync skipped: root folder');
        return false;
      }

      // Check if reverse sync is enabled (folder setting has precedence over root)
      const folderReverseSyncEnabled = folder.settings?.[SETTINGS_KEYS.reverseSyncEnabled];
      const rootReverseSyncEnabled = workspace.settings[SETTINGS_KEYS.reverseSyncEnabled];

      const isEnabled = folderReverseSyncEnabled ?? rootReverseSyncEnabled ?? true;

      if (!isEnabled) {
        this.outputChannel.appendLine(
          `Reverse sync skipped for ${folder.name || folderPath}: reverseSync.enabled is false`
        );
        return false;
      }

      // Get exclude patterns (folder + root merged)
      const rootExclude =
        (workspace.settings[SETTINGS_KEYS.reverseSyncFolderSettingsExclude] as string[]) ?? [];
      const folderExclude =
        (folder.settings?.[SETTINGS_KEYS.reverseSyncFolderSettingsExclude] as string[]) ?? [];
      const matcher = new PatternMatcher([...rootExclude, ...folderExclude]);

      // Read current .vscode/settings.json
      const currentSettings = await this.readSettingsJson(folderPath);
      if (!currentSettings) {
        this.outputChannel.appendLine(
          `Reverse sync skipped for ${folder.name || folderPath}: no settings.json found`
        );
        return false;
      }

      // Calculate what forward sync would generate
      const expectedSettings = this.calculateExpectedSettings(workspace.settings, folder);

      // Find differences (settings changed in UI)
      const diff = this.calculateFilteredDiff(expectedSettings, currentSettings, matcher);

      // If no changes, skip
      if (Object.keys(diff).length === 0) {
        this.outputChannel.appendLine(
          `Reverse sync skipped for ${folder.name || folderPath}: no changes detected`
        );
        return false;
      }

      // Update folder.settings in workspace file
      await this.updateFolderSettings(folderPath, folder, diff);

      this.outputChannel.appendLine(
        `Reverse synced ${Object.keys(diff).length} setting(s) from ${folder.name || folderPath}`
      );
      return true;
    } catch (error) {
      this.outputChannel.appendLine(
        `Error in reverse sync for ${folderPath}: ${error instanceof Error ? error.message : String(error)}`
      );
      return false;
    }
  }

  /**
   * Read a folder's .vscode/settings.json
   */
  private async readSettingsJson(folderPath: string): Promise<Settings | null> {
    try {
      const resolvedPath = await this.workspaceConfig.resolveFolderPath(folderPath);
      const settingsFile = path.join(resolvedPath, '.vscode', 'settings.json');

      const content = await fs.readFile(settingsFile, 'utf-8');
      return jsonc.parse(content) as Settings;
    } catch {
      return null;
    }
  }

  /**
   * Calculate what forward sync would generate for this folder
   *
   * Merge order: Root settings → subFolderSettings.defaults → filter rootSettings.exclude → folders[].settings
   */
  private calculateExpectedSettings(globalSettings: Settings, folder: FolderConfig): Settings {
    // 1. Remove workspaceManager.* keys from root
    const rootWithoutWM: Settings = {};
    for (const [key, value] of Object.entries(globalSettings)) {
      if (!key.startsWith(WORKSPACE_MANAGER_PREFIX)) {
        rootWithoutWM[key] = value;
      }
    }

    // 2. Merge with subFolderSettings.defaults
    const subFolderDefaults =
      (globalSettings[SETTINGS_KEYS.syncSubFolderSettingsDefaults] as Settings) ?? {};
    const withDefaults = this.merger.merge(rootWithoutWM, subFolderDefaults);

    // 3. Apply rootSettings.exclude (filter - "don't inherit")
    const excludePatterns =
      (globalSettings[SETTINGS_KEYS.syncRootSettingsExclude] as string[]) ?? [];
    const matcher = new PatternMatcher(excludePatterns);
    const filtered: Settings = {};
    for (const [key, value] of Object.entries(withDefaults)) {
      if (!matcher.isExcluded(key)) {
        filtered[key] = value;
      }
    }

    // 4. Merge with folder settings (also filter workspaceManager.* from folder settings)
    const filteredFolderSettings: Settings = {};
    if (folder.settings) {
      for (const [key, value] of Object.entries(folder.settings)) {
        if (!key.startsWith(WORKSPACE_MANAGER_PREFIX)) {
          filteredFolderSettings[key] = value;
        }
      }
    }

    return this.merger.merge(filtered, filteredFolderSettings);
  }

  /**
   * Calculate diff between expected and current settings, filtering excluded keys
   */
  private calculateFilteredDiff(
    expected: Settings,
    current: Settings,
    matcher: PatternMatcher
  ): Settings {
    const diff = this.merger.diff(expected, current);

    // Filter out excluded patterns and workspaceManager.* keys
    const filteredDiff: Settings = {};
    for (const [key, value] of Object.entries(diff)) {
      if (key.startsWith(WORKSPACE_MANAGER_PREFIX)) {
        continue;
      }
      if (matcher.isExcluded(key)) {
        continue;
      }
      filteredDiff[key] = value;
    }

    return filteredDiff;
  }

  /**
   * Update folder settings in the workspace file
   */
  private async updateFolderSettings(
    folderPath: string,
    folder: FolderConfig,
    diff: Settings
  ): Promise<void> {
    const workspace = await this.workspaceConfig.load();

    const folderIndex = workspace.folders.findIndex((f) => f.path === folderPath);
    if (folderIndex === -1) {
      throw new Error(`Folder not found: ${folderPath}`);
    }

    // Get current folder settings
    const currentFolderSettings = folder.settings ?? {};

    // Apply diff to folder settings
    const newFolderSettings: Settings = { ...currentFolderSettings };

    for (const [key, value] of Object.entries(diff)) {
      if (value === null) {
        // User removed this setting
        delete newFolderSettings[key];
      } else {
        newFolderSettings[key] = value;
      }
    }

    // Update folder in workspace
    workspace.folders[folderIndex] = {
      ...folder,
      settings: newFolderSettings,
    };

    await this.workspaceConfig.save(workspace);
  }
}
