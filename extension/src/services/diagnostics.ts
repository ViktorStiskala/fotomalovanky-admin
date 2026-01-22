/**
 * Diagnostics service
 *
 * Provides IDE diagnostics (errors, warnings) for workspace configuration issues.
 */

import * as vscode from 'vscode';
import * as fs from 'fs/promises';
import * as jsonc from 'jsonc-parser';
import { WorkspaceConfigService } from './workspaceConfig';
import { SETTINGS_KEYS, WORKSPACE_MANAGER_PREFIX } from '../types';
import { getQuickFixHint } from '../utils/quickFixHint';

/**
 * Settings that only work at root level (scope: window)
 */
const ROOT_ONLY_SETTINGS = [
  SETTINGS_KEYS.autoSyncEnabled,
  SETTINGS_KEYS.syncEnabled,
  SETTINGS_KEYS.syncRootSettingsExclude,
  SETTINGS_KEYS.syncSubFolderSettingsDefaults,
];

export class DiagnosticsService {
  private diagnosticCollection: vscode.DiagnosticCollection;
  private workspaceConfig: WorkspaceConfigService;
  private outputChannel: vscode.OutputChannel;

  constructor(workspaceConfig: WorkspaceConfigService, outputChannel: vscode.OutputChannel) {
    this.diagnosticCollection = vscode.languages.createDiagnosticCollection('workspaceManager');
    this.workspaceConfig = workspaceConfig;
    this.outputChannel = outputChannel;
  }

  /**
   * Validate the workspace file and update diagnostics
   */
  async validate(): Promise<void> {
    const workspacePath = this.workspaceConfig.getWorkspacePath();
    if (!workspacePath) {
      return;
    }

    try {
      const diagnostics = await this.collectDiagnostics(workspacePath);
      const uri = vscode.Uri.file(workspacePath);
      this.diagnosticCollection.set(uri, diagnostics);

      if (diagnostics.length > 0) {
        this.outputChannel.appendLine(
          `Diagnostics: Found ${diagnostics.length} issue(s) in workspace file`
        );
      }
    } catch (error) {
      this.outputChannel.appendLine(
        `Diagnostics error: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  /**
   * Collect diagnostics for the workspace file
   */
  private async collectDiagnostics(workspacePath: string): Promise<vscode.Diagnostic[]> {
    const diagnostics: vscode.Diagnostic[] = [];

    // Prefer reading from the open document (if any) to get in-memory changes
    // This ensures diagnostics update immediately when edits are applied
    const uri = vscode.Uri.file(workspacePath);
    const openDocument = vscode.workspace.textDocuments.find(
      (doc) => doc.uri.toString() === uri.toString()
    );
    const text = openDocument ? openDocument.getText() : await fs.readFile(workspacePath, 'utf-8');
    const rootNode = jsonc.parseTree(text);

    if (!rootNode) {
      return diagnostics;
    }

    // Get the Quick Fix hint
    const quickFixHint = getQuickFixHint();

    // Find the folders array
    const foldersNode = jsonc.findNodeAtLocation(rootNode, ['folders']);
    if (!foldersNode || !foldersNode.children) {
      return diagnostics;
    }

    // Parse workspace settings for later checks
    const workspaceData = jsonc.parse(text) as {
      folders?: Array<{ path: string; settings?: Record<string, unknown> }>;
      settings?: Record<string, unknown>;
    };
    const rootSettings = workspaceData?.settings ?? {};

    // Check for workspaceManager.* settings in subFolderSettings.defaults (Error)
    this.checkWmSettingsInDefaults(rootNode, text, diagnostics, quickFixHint);

    // Check for autoSync enabled with forward sync disabled (Hint)
    this.checkAutoSyncWithForwardDisabled(rootNode, text, workspaceData, diagnostics);

    // Check for reverseSync exclude patterns when reverseSync is disabled at root level
    this.checkReverseSyncExcludeAtRoot(rootNode, text, workspaceData, diagnostics, quickFixHint);

    // Check each folder
    for (let i = 0; i < foldersNode.children.length; i++) {
      const folderNode = foldersNode.children[i];
      const pathNode = jsonc.findNodeAtLocation(rootNode, ['folders', i, 'path']);
      if (!pathNode || pathNode.value === undefined) {
        continue;
      }

      const folderPath = pathNode.value as string;
      const isRoot = await this.workspaceConfig.isWorkspaceRoot(folderPath);
      const folderSettings = workspaceData?.folders?.[i]?.settings ?? {};

      // Check for flat "settings.xxx" keys on ALL folders
      const flatSettingsKeys = this.findFlatSettingsKeys(folderNode);
      for (const propertyNode of flatSettingsKeys) {
        const range = this.nodeToRange(text, propertyNode);

        // Different message for root folder vs non-root folder
        const message = isRoot
          ? `Flat settings syntax is not supported, and settings on the root folder are ignored. Use root "settings" instead.\n\n${quickFixHint}`
          : `Flat settings syntax is not supported. Use a nested "settings" object instead.\n\n${quickFixHint}`;

        const diagnostic = new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Hint);
        diagnostic.tags = [vscode.DiagnosticTag.Unnecessary];
        diagnostic.source = 'Workspace Manager';
        diagnostic.code = 'flat-settings';
        diagnostics.push(diagnostic);
      }

      // Check for nested settings object only on ROOT folder
      if (isRoot) {
        const settingsPropertyNode = this.findPropertyNode(folderNode, 'settings');
        if (settingsPropertyNode) {
          const range = this.nodeToRange(text, settingsPropertyNode);
          const diagnostic = new vscode.Diagnostic(
            range,
            `Settings on the root folder are ignored. Use root "settings" instead.\n\n${quickFixHint}`,
            vscode.DiagnosticSeverity.Hint
          );
          diagnostic.tags = [vscode.DiagnosticTag.Unnecessary];
          diagnostic.source = 'Workspace Manager';
          diagnostic.code = 'root-folder-settings';
          diagnostics.push(diagnostic);
        }
      }

      // Check for root-only settings in folder settings (Warning)
      this.checkRootOnlySettingsInFolder(rootNode, text, i, folderNode, diagnostics, quickFixHint);

      // Check for reverseSync exclude patterns when reverseSync is disabled at folder level
      this.checkReverseSyncExcludeInFolder(
        rootNode,
        text,
        i,
        folderSettings,
        rootSettings,
        diagnostics,
        quickFixHint
      );
    }

    return diagnostics;
  }

  /**
   * Check for root-only settings placed in folder settings (Warning)
   */
  private checkRootOnlySettingsInFolder(
    rootNode: jsonc.Node,
    text: string,
    folderIndex: number,
    _folderNode: jsonc.Node,
    diagnostics: vscode.Diagnostic[],
    quickFixHint: string
  ): void {
    const settingsNode = jsonc.findNodeAtLocation(rootNode, ['folders', folderIndex, 'settings']);
    if (!settingsNode || settingsNode.type !== 'object' || !settingsNode.children) {
      return;
    }

    for (const child of settingsNode.children) {
      if (child.type !== 'property' || !child.children || child.children.length < 1) {
        continue;
      }

      const keyNode = child.children[0];
      if (keyNode.type !== 'string' || typeof keyNode.value !== 'string') {
        continue;
      }

      const key = keyNode.value;
      if ((ROOT_ONLY_SETTINGS as readonly string[]).includes(key)) {
        const range = this.nodeToRange(text, child);
        const diagnostic = new vscode.Diagnostic(
          range,
          `This setting only works in root "settings". It has no effect here.\n\n${quickFixHint}`,
          vscode.DiagnosticSeverity.Warning
        );
        diagnostic.source = 'Workspace Manager';
        diagnostic.code = 'root-only-setting-in-folder';
        diagnostics.push(diagnostic);
      }
    }
  }

  /**
   * Check for workspaceManager.* settings in subFolderSettings.defaults (Error)
   */
  private checkWmSettingsInDefaults(
    rootNode: jsonc.Node,
    text: string,
    diagnostics: vscode.Diagnostic[],
    quickFixHint: string
  ): void {
    const defaultsNode = jsonc.findNodeAtLocation(rootNode, [
      'settings',
      SETTINGS_KEYS.syncSubFolderSettingsDefaults,
    ]);
    if (!defaultsNode || defaultsNode.type !== 'object' || !defaultsNode.children) {
      return;
    }

    for (const child of defaultsNode.children) {
      if (child.type !== 'property' || !child.children || child.children.length < 1) {
        continue;
      }

      const keyNode = child.children[0];
      if (keyNode.type !== 'string' || typeof keyNode.value !== 'string') {
        continue;
      }

      const key = keyNode.value;
      if (key.startsWith(WORKSPACE_MANAGER_PREFIX)) {
        const range = this.nodeToRange(text, child);
        const diagnostic = new vscode.Diagnostic(
          range,
          `"workspaceManager.*" settings are not allowed in subFolderSettings.defaults.\n\nPut settings directly in folders[].settings, or define "workspaceManager.reverseSync.*" options in root settings.\n\n${quickFixHint}`,
          vscode.DiagnosticSeverity.Error
        );
        diagnostic.source = 'Workspace Manager';
        diagnostic.code = 'wm-settings-in-defaults';
        diagnostics.push(diagnostic);
      }
    }
  }

  /**
   * Check for autoSync enabled with forward sync disabled (Hint)
   */
  private checkAutoSyncWithForwardDisabled(
    rootNode: jsonc.Node,
    text: string,
    workspaceData: {
      folders?: Array<{ path: string; settings?: Record<string, unknown> }>;
      settings?: Record<string, unknown>;
    },
    diagnostics: vscode.Diagnostic[]
  ): void {
    const rootSettings = workspaceData?.settings ?? {};
    const autoSyncEnabled = rootSettings[SETTINGS_KEYS.autoSyncEnabled] === true;
    const forwardSyncEnabled = rootSettings[SETTINGS_KEYS.syncEnabled] !== false;

    if (!autoSyncEnabled || forwardSyncEnabled) {
      return; // No issue
    }

    // Forward sync is disabled while autoSync is enabled
    const autoSyncNode = jsonc.findNodeAtLocation(rootNode, [
      'settings',
      SETTINGS_KEYS.autoSyncEnabled,
    ]);
    if (!autoSyncNode) {
      return;
    }

    // Find the property node (parent of the value node)
    const settingsNode = jsonc.findNodeAtLocation(rootNode, ['settings']);
    if (!settingsNode || !settingsNode.children) {
      return;
    }

    const autoSyncPropertyNode = this.findPropertyNode(settingsNode, SETTINGS_KEYS.autoSyncEnabled);
    if (!autoSyncPropertyNode) {
      return;
    }

    // Check if ALL folders have reverseSync disabled
    const allReverseSyncDisabled = this.checkAllFoldersReverseSyncDisabled(workspaceData);

    const range = this.nodeToRange(text, autoSyncPropertyNode);
    let message: string;

    if (allReverseSyncDisabled) {
      message = 'Auto-Sync will have no effect, as both forwardSync and reverseSync are disabled.';
    } else {
      message =
        'Forward sync is disabled.\n\nAuto-Sync will only sync folder setting changes to Workspace.';
    }

    const diagnostic = new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Hint);
    diagnostic.source = 'Workspace Manager';
    diagnostic.code = 'autosync-forward-disabled';
    diagnostics.push(diagnostic);
  }

  /**
   * Check if ALL folders have reverseSync effectively disabled
   */
  private checkAllFoldersReverseSyncDisabled(workspaceData: {
    folders?: Array<{ path: string; settings?: Record<string, unknown> }>;
    settings?: Record<string, unknown>;
  }): boolean {
    const rootSettings = workspaceData?.settings ?? {};
    const rootReverseSyncEnabled = rootSettings[SETTINGS_KEYS.reverseSyncEnabled] !== false;
    const folders = workspaceData?.folders ?? [];

    if (folders.length === 0) {
      return !rootReverseSyncEnabled;
    }

    for (const folder of folders) {
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
   * Check for reverseSync exclude patterns at root level when all folders have reverseSync disabled
   */
  private checkReverseSyncExcludeAtRoot(
    rootNode: jsonc.Node,
    text: string,
    workspaceData: {
      folders?: Array<{ path: string; settings?: Record<string, unknown> }>;
      settings?: Record<string, unknown>;
    },
    diagnostics: vscode.Diagnostic[],
    quickFixHint: string
  ): void {
    const rootSettings = workspaceData?.settings ?? {};
    const excludePatterns = rootSettings[SETTINGS_KEYS.reverseSyncFolderSettingsExclude] as
      | string[]
      | undefined;

    // Only check if there are actually exclude patterns defined at root
    if (!excludePatterns || !Array.isArray(excludePatterns) || excludePatterns.length === 0) {
      return;
    }

    // Only show diagnostic if ALL folders have reverseSync disabled
    // (because root patterns ARE used if any folder has reverseSync enabled)
    if (!this.checkAllFoldersReverseSyncDisabled(workspaceData)) {
      return;
    }

    const settingsNode = jsonc.findNodeAtLocation(rootNode, ['settings']);
    if (!settingsNode) {
      return;
    }

    const excludePropertyNode = this.findPropertyNode(
      settingsNode,
      SETTINGS_KEYS.reverseSyncFolderSettingsExclude
    );
    if (!excludePropertyNode) {
      return;
    }

    const range = this.nodeToRange(text, excludePropertyNode);
    const diagnostic = new vscode.Diagnostic(
      range,
      `Exclude patterns have no effect because reverse sync is disabled.\n\n${quickFixHint}`,
      vscode.DiagnosticSeverity.Hint
    );
    diagnostic.tags = [vscode.DiagnosticTag.Unnecessary];
    diagnostic.source = 'Workspace Manager';
    diagnostic.code = 'reverse-exclude-when-disabled';
    diagnostics.push(diagnostic);
  }

  /**
   * Check for reverseSync exclude patterns in folder settings when that folder has reverseSync disabled
   */
  private checkReverseSyncExcludeInFolder(
    rootNode: jsonc.Node,
    text: string,
    folderIndex: number,
    folderSettings: Record<string, unknown>,
    rootSettings: Record<string, unknown>,
    diagnostics: vscode.Diagnostic[],
    quickFixHint: string
  ): void {
    const folderExcludePatterns = folderSettings[SETTINGS_KEYS.reverseSyncFolderSettingsExclude] as
      | string[]
      | undefined;

    // Only check if there are actually exclude patterns defined in folder
    if (
      !folderExcludePatterns ||
      !Array.isArray(folderExcludePatterns) ||
      folderExcludePatterns.length === 0
    ) {
      return;
    }

    // Check if this specific folder has reverseSync disabled
    const folderReverseSyncEnabled = folderSettings[SETTINGS_KEYS.reverseSyncEnabled];
    const rootReverseSyncEnabled = rootSettings[SETTINGS_KEYS.reverseSyncEnabled] !== false;
    const isEnabled = folderReverseSyncEnabled ?? rootReverseSyncEnabled;

    if (isEnabled) {
      return; // reverseSync is enabled for this folder, patterns are used
    }

    const folderSettingsNode = jsonc.findNodeAtLocation(rootNode, [
      'folders',
      folderIndex,
      'settings',
    ]);
    if (!folderSettingsNode) {
      return;
    }

    const excludePropertyNode = this.findPropertyNode(
      folderSettingsNode,
      SETTINGS_KEYS.reverseSyncFolderSettingsExclude
    );
    if (!excludePropertyNode) {
      return;
    }

    const range = this.nodeToRange(text, excludePropertyNode);
    const diagnostic = new vscode.Diagnostic(
      range,
      `Exclude patterns have no effect because reverse sync is disabled.\n\n${quickFixHint}`,
      vscode.DiagnosticSeverity.Hint
    );
    diagnostic.tags = [vscode.DiagnosticTag.Unnecessary];
    diagnostic.source = 'Workspace Manager';
    diagnostic.code = 'reverse-exclude-when-disabled';
    diagnostics.push(diagnostic);
  }

  /**
   * Find a property node by key name in an object node
   *
   * Returns the full property node (including key and value) rather than just the value.
   */
  private findPropertyNode(objectNode: jsonc.Node, propertyName: string): jsonc.Node | undefined {
    if (objectNode.type !== 'object' || !objectNode.children) {
      return undefined;
    }

    for (const child of objectNode.children) {
      if (child.type === 'property' && child.children && child.children.length >= 1) {
        const keyNode = child.children[0];
        if (keyNode.type === 'string' && keyNode.value === propertyName) {
          return child;
        }
      }
    }

    return undefined;
  }

  /**
   * Find all flat settings keys (e.g., "settings.editor.fontSize") in a folder object
   *
   * Only matches keys that:
   * 1. Are direct children of the folder object (not nested)
   * 2. Start with exactly "settings." (with the dot)
   *
   * Does NOT match:
   * - "settings" (the nested settings object itself)
   * - Keys inside the "settings" object
   * - Keys like "generator.settings" that contain but don't start with "settings."
   */
  private findFlatSettingsKeys(folderNode: jsonc.Node): jsonc.Node[] {
    const result: jsonc.Node[] = [];
    if (folderNode.type !== 'object' || !folderNode.children) {
      return result;
    }

    for (const child of folderNode.children) {
      // Only check property nodes that are direct children
      if (child.type !== 'property' || !child.children || child.children.length < 1) {
        continue;
      }

      const keyNode = child.children[0];

      // Ensure the key is a string and starts with "settings." (with the dot)
      if (
        keyNode.type === 'string' &&
        typeof keyNode.value === 'string' &&
        keyNode.value.startsWith('settings.') &&
        keyNode.value.length > 'settings.'.length // Must have something after the dot
      ) {
        result.push(child);
      }
    }

    return result;
  }

  /**
   * Convert a jsonc-parser node to a VS Code Range
   */
  private nodeToRange(text: string, node: jsonc.Node): vscode.Range {
    const startPos = this.offsetToPosition(text, node.offset);
    const endPos = this.offsetToPosition(text, node.offset + node.length);
    return new vscode.Range(startPos, endPos);
  }

  /**
   * Convert a text offset to a VS Code Position (line, column)
   */
  private offsetToPosition(text: string, offset: number): vscode.Position {
    const textBefore = text.substring(0, offset);
    const lines = textBefore.split('\n');
    const line = lines.length - 1;
    const character = lines[lines.length - 1].length;
    return new vscode.Position(line, character);
  }

  /**
   * Clear all diagnostics
   */
  clear(): void {
    this.diagnosticCollection.clear();
  }

  /**
   * Dispose the diagnostic collection
   */
  dispose(): void {
    this.diagnosticCollection.dispose();
  }
}
