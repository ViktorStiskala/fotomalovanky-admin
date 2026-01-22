/**
 * Code Actions service
 *
 * Provides quick fixes for workspace configuration issues.
 */

import * as vscode from 'vscode';
import * as jsonc from 'jsonc-parser';
import { WorkspaceConfigService } from './workspaceConfig';
import { SETTINGS_KEYS } from '../types';

export class WorkspaceCodeActionProvider implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  constructor(private workspaceConfig: WorkspaceConfigService) {}

  /**
   * Detect the indentation style used in the document
   */
  private detectIndentationStyle(text: string): jsonc.FormattingOptions {
    // Find the first indented line to detect tab vs spaces
    const lines = text.split('\n');
    for (const line of lines) {
      if (line.startsWith('\t')) {
        return { tabSize: 1, insertSpaces: false };
      }
      const match = line.match(/^( +)/);
      if (match) {
        // Detect tab size from the indentation
        const spaces = match[1].length;
        return { tabSize: spaces, insertSpaces: true };
      }
    }
    // Default to tabs (common for workspace files)
    return { tabSize: 1, insertSpaces: false };
  }

  async provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range,
    context: vscode.CodeActionContext
  ): Promise<vscode.CodeAction[]> {
    // Only provide code actions for the ACTIVE workspace file
    const activeWorkspaceFile = vscode.workspace.workspaceFile;
    if (!activeWorkspaceFile || document.uri.toString() !== activeWorkspaceFile.toString()) {
      return [];
    }

    const actions: vscode.CodeAction[] = [];

    // Quick fix for flat settings (settings.xxx keys on folder)
    const flatSettingsDiagnostics = context.diagnostics.filter((d) => d.code === 'flat-settings');
    if (flatSettingsDiagnostics.length > 0) {
      // Determine if this is on the root folder (affects title and target)
      const isRootFolder = await this.isDiagnosticOnRootFolder(
        document,
        flatSettingsDiagnostics[0]
      );
      const fix = new vscode.CodeAction(
        isRootFolder ? 'Move to root "settings" object' : 'Move to nested "settings" object',
        vscode.CodeActionKind.QuickFix
      );
      fix.diagnostics = flatSettingsDiagnostics;
      fix.edit = this.createFlatSettingsEdit(document, flatSettingsDiagnostics, isRootFolder);
      fix.isPreferred = true;
      actions.push(fix);
    }

    // Quick fix for root folder settings (settings on root folder entry)
    const rootFolderDiagnostics = context.diagnostics.filter(
      (d) => d.code === 'root-folder-settings'
    );
    if (rootFolderDiagnostics.length > 0) {
      const fix = new vscode.CodeAction(
        'Move to root "settings" object',
        vscode.CodeActionKind.QuickFix
      );
      fix.diagnostics = rootFolderDiagnostics;
      fix.edit = this.createRootFolderSettingsEdit(document, rootFolderDiagnostics);
      fix.isPreferred = true;
      actions.push(fix);
    }

    // Quick fix for root-only settings in folder settings
    const rootOnlyDiagnostics = context.diagnostics.filter(
      (d) => d.code === 'root-only-setting-in-folder'
    );
    if (rootOnlyDiagnostics.length > 0) {
      const fix = new vscode.CodeAction('Move to root settings', vscode.CodeActionKind.QuickFix);
      fix.diagnostics = rootOnlyDiagnostics;
      fix.edit = this.createMoveToRootSettingsEdit(document, rootOnlyDiagnostics);
      fix.isPreferred = true;
      actions.push(fix);
    }

    // Quick fix for workspaceManager.* settings in subFolderSettings.defaults
    const wmInDefaultsDiagnostics = context.diagnostics.filter(
      (d) => d.code === 'wm-settings-in-defaults'
    );
    for (const diagnostic of wmInDefaultsDiagnostics) {
      const settingKey = this.extractSettingKeyFromRange(document, diagnostic.range);
      if (settingKey) {
        const fix = new vscode.CodeAction(
          `Remove "${settingKey}" setting`,
          vscode.CodeActionKind.QuickFix
        );
        fix.diagnostics = [diagnostic];
        fix.edit = this.createRemoveFromDefaultsEdit(document, diagnostic);
        fix.isPreferred = true;
        actions.push(fix);
      }
    }

    // Quick fixes for reverseSync exclude patterns with disabled reverseSync
    const reverseExcludeDiagnostics = context.diagnostics.filter(
      (d) => d.code === 'reverse-exclude-when-disabled'
    );
    for (const diagnostic of reverseExcludeDiagnostics) {
      // Option 1: Remove the exclude patterns
      const removeFix = new vscode.CodeAction(
        `Remove "${SETTINGS_KEYS.reverseSyncFolderSettingsExclude}" setting`,
        vscode.CodeActionKind.QuickFix
      );
      removeFix.diagnostics = [diagnostic];
      removeFix.edit = this.createRemoveExcludePatternsEdit(document, diagnostic);
      actions.push(removeFix);

      // Option 2: Enable reverseSync
      const enableFix = new vscode.CodeAction(
        `Set "${SETTINGS_KEYS.reverseSyncEnabled}" to "true"`,
        vscode.CodeActionKind.QuickFix
      );
      enableFix.diagnostics = [diagnostic];
      enableFix.edit = this.createEnableReverseSyncEdit(document, diagnostic);
      enableFix.isPreferred = true;
      actions.push(enableFix);
    }

    return actions;
  }

  /**
   * Extract the setting key name from a diagnostic range
   */
  private extractSettingKeyFromRange(
    document: vscode.TextDocument,
    range: vscode.Range
  ): string | null {
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);
    if (!rootNode) return null;

    const offset = document.offsetAt(range.start);
    const node = jsonc.findNodeAtOffset(rootNode, offset);
    if (!node) return null;

    // Navigate to find the property key
    // The diagnostic range covers the property node, so we need to find the key
    if (node.type === 'property' && node.children && node.children.length >= 1) {
      const keyNode = node.children[0];
      if (keyNode.type === 'string') {
        return keyNode.value as string;
      }
    }

    // If we're on the key node directly
    if (node.type === 'string' && node.parent?.type === 'property') {
      return node.value as string;
    }

    return null;
  }

  /**
   * Determine if a diagnostic is on a folder that resolves to the workspace root
   */
  private async isDiagnosticOnRootFolder(
    document: vscode.TextDocument,
    diagnostic: vscode.Diagnostic
  ): Promise<boolean> {
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);
    if (!rootNode) return false;

    const offset = document.offsetAt(diagnostic.range.start);

    // Find which folder contains this offset
    const foldersNode = jsonc.findNodeAtLocation(rootNode, ['folders']);
    if (!foldersNode?.children) return false;

    for (let i = 0; i < foldersNode.children.length; i++) {
      const folderNode = foldersNode.children[i];
      if (offset >= folderNode.offset && offset < folderNode.offset + folderNode.length) {
        // Found the folder, check if it's root
        const pathNode = jsonc.findNodeAtLocation(rootNode, ['folders', i, 'path']);
        if (pathNode?.value) {
          return this.workspaceConfig.isWorkspaceRoot(pathNode.value as string);
        }
      }
    }

    return false;
  }

  /**
   * Find which folder index contains the given offset
   */
  private findFolderIndexAtOffset(rootNode: jsonc.Node, offset: number): number {
    const foldersNode = jsonc.findNodeAtLocation(rootNode, ['folders']);
    if (!foldersNode?.children) return -1;

    for (let i = 0; i < foldersNode.children.length; i++) {
      const folderNode = foldersNode.children[i];
      if (offset >= folderNode.offset && offset < folderNode.offset + folderNode.length) {
        return i;
      }
    }

    return -1;
  }

  /**
   * Create edit to move ALL flat settings.xxx keys to the appropriate settings object
   *
   * Collects ALL flat settings from the folder (not just from diagnostics),
   * moves them all to the nested settings object, then removes them all.
   */
  private createFlatSettingsEdit(
    document: vscode.TextDocument,
    diagnostics: vscode.Diagnostic[],
    isRootFolder: boolean
  ): vscode.WorkspaceEdit {
    const edit = new vscode.WorkspaceEdit();
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);

    if (!rootNode || diagnostics.length === 0) {
      return edit;
    }

    // Detect indentation style from the document
    const formattingOptions = this.detectIndentationStyle(text);

    // Find the folder index from the first diagnostic
    const firstDiagnosticOffset = document.offsetAt(diagnostics[0].range.start);
    const folderIndex = this.findFolderIndexAtOffset(rootNode, firstDiagnosticOffset);
    if (folderIndex === -1) {
      return edit;
    }

    // Collect ALL flat settings keys from the folder (not just from diagnostics)
    const settingsToMove: Array<{ key: string; value: unknown; originalKey: string }> = [];

    const foldersNode = jsonc.findNodeAtLocation(rootNode, ['folders']);
    const folderNode = foldersNode?.children?.[folderIndex];

    if (folderNode?.type === 'object' && folderNode.children) {
      for (const child of folderNode.children) {
        if (child.type === 'property' && child.children?.length === 2) {
          const keyNode = child.children[0];
          const valueNode = child.children[1];

          if (
            keyNode.type === 'string' &&
            typeof keyNode.value === 'string' &&
            keyNode.value.startsWith('settings.') &&
            keyNode.value.length > 'settings.'.length
          ) {
            // Remove "settings." prefix to get the actual setting key
            const originalKey = keyNode.value;
            const actualKey = keyNode.value.substring('settings.'.length);
            settingsToMove.push({
              key: actualKey,
              value: jsonc.getNodeValue(valueNode),
              originalKey,
            });
          }
        }
      }
    }

    if (settingsToMove.length === 0) {
      return edit;
    }

    // Build edits: add to settings object, then remove flat keys
    let modifiedText = text;

    // First, add ALL settings to the target location
    for (const { key, value } of settingsToMove) {
      let targetPath: jsonc.JSONPath;

      if (isRootFolder) {
        // Move to root settings
        targetPath = ['settings', key];
      } else {
        // Move to folder's nested settings
        targetPath = ['folders', folderIndex, 'settings', key];
      }

      const edits = jsonc.modify(modifiedText, targetPath, value, { formattingOptions });
      modifiedText = jsonc.applyEdits(modifiedText, edits);
    }

    // Then remove ALL the flat settings keys we collected
    for (const { originalKey } of settingsToMove) {
      const edits = jsonc.modify(
        modifiedText,
        ['folders', folderIndex, originalKey],
        undefined, // undefined removes the key
        { formattingOptions }
      );
      modifiedText = jsonc.applyEdits(modifiedText, edits);
    }

    // Apply as a single replace edit
    const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(text.length));
    edit.replace(document.uri, fullRange, modifiedText);

    return edit;
  }

  /**
   * Create edit to move root folder's settings to root settings object
   */
  private createRootFolderSettingsEdit(
    document: vscode.TextDocument,
    diagnostics: vscode.Diagnostic[]
  ): vscode.WorkspaceEdit {
    const edit = new vscode.WorkspaceEdit();
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);

    if (!rootNode || diagnostics.length === 0) {
      return edit;
    }

    // Detect indentation style from the document
    const formattingOptions = this.detectIndentationStyle(text);

    // Find the folder index from the first diagnostic
    const firstDiagnosticOffset = document.offsetAt(diagnostics[0].range.start);
    const folderIndex = this.findFolderIndexAtOffset(rootNode, firstDiagnosticOffset);
    if (folderIndex === -1) {
      return edit;
    }

    // Get the folder's settings value
    const folderSettingsNode = jsonc.findNodeAtLocation(rootNode, [
      'folders',
      folderIndex,
      'settings',
    ]);
    if (!folderSettingsNode) {
      return edit;
    }

    const folderSettings = jsonc.getNodeValue(folderSettingsNode) as Record<string, unknown>;
    if (!folderSettings || typeof folderSettings !== 'object') {
      return edit;
    }

    let modifiedText = text;

    // Add each setting to root settings
    for (const [key, value] of Object.entries(folderSettings)) {
      // Skip workspaceManager settings
      if (key.startsWith('workspaceManager.')) {
        continue;
      }

      const edits = jsonc.modify(modifiedText, ['settings', key], value, { formattingOptions });
      modifiedText = jsonc.applyEdits(modifiedText, edits);
    }

    // Remove the folder's settings property
    const removeEdits = jsonc.modify(
      modifiedText,
      ['folders', folderIndex, 'settings'],
      undefined,
      { formattingOptions }
    );
    modifiedText = jsonc.applyEdits(modifiedText, removeEdits);

    // Apply as a single replace edit
    const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(text.length));
    edit.replace(document.uri, fullRange, modifiedText);

    return edit;
  }

  /**
   * Create edit to move root-only settings from folder settings to root settings
   */
  private createMoveToRootSettingsEdit(
    document: vscode.TextDocument,
    diagnostics: vscode.Diagnostic[]
  ): vscode.WorkspaceEdit {
    const edit = new vscode.WorkspaceEdit();
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);

    if (!rootNode || diagnostics.length === 0) {
      return edit;
    }

    const formattingOptions = this.detectIndentationStyle(text);
    let modifiedText = text;

    for (const diagnostic of diagnostics) {
      const offset = document.offsetAt(diagnostic.range.start);
      const folderIndex = this.findFolderIndexAtOffset(rootNode, offset);
      if (folderIndex === -1) continue;

      // Find the property node at this location
      const currentRootNode = jsonc.parseTree(modifiedText);
      if (!currentRootNode) continue;

      const folderSettingsNode = jsonc.findNodeAtLocation(currentRootNode, [
        'folders',
        folderIndex,
        'settings',
      ]);
      if (!folderSettingsNode || !folderSettingsNode.children) continue;

      // Find settings to move (root-only settings)
      for (const child of folderSettingsNode.children) {
        if (child.type !== 'property' || !child.children || child.children.length < 2) continue;

        const keyNode = child.children[0];
        const valueNode = child.children[1];

        if (keyNode.type !== 'string') continue;
        const key = keyNode.value as string;

        // Check if this is a root-only setting
        if (
          key === SETTINGS_KEYS.autoSyncEnabled ||
          key === SETTINGS_KEYS.syncEnabled ||
          key === SETTINGS_KEYS.syncRootSettingsExclude ||
          key === SETTINGS_KEYS.syncSubFolderSettingsDefaults
        ) {
          const value = jsonc.getNodeValue(valueNode);

          // Add to root settings
          const addEdits = jsonc.modify(modifiedText, ['settings', key], value, {
            formattingOptions,
          });
          modifiedText = jsonc.applyEdits(modifiedText, addEdits);

          // Remove from folder settings
          const removeEdits = jsonc.modify(
            modifiedText,
            ['folders', folderIndex, 'settings', key],
            undefined,
            { formattingOptions }
          );
          modifiedText = jsonc.applyEdits(modifiedText, removeEdits);
        }
      }
    }

    const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(text.length));
    edit.replace(document.uri, fullRange, modifiedText);

    return edit;
  }

  /**
   * Create edit to remove a workspaceManager.* setting from subFolderSettings.defaults
   */
  private createRemoveFromDefaultsEdit(
    document: vscode.TextDocument,
    diagnostic: vscode.Diagnostic
  ): vscode.WorkspaceEdit {
    const edit = new vscode.WorkspaceEdit();
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);

    if (!rootNode) {
      return edit;
    }

    const formattingOptions = this.detectIndentationStyle(text);
    const settingKey = this.extractSettingKeyFromRange(document, diagnostic.range);

    if (!settingKey) {
      return edit;
    }

    // Remove the setting from subFolderSettings.defaults
    const edits = jsonc.modify(
      text,
      ['settings', SETTINGS_KEYS.syncSubFolderSettingsDefaults, settingKey],
      undefined,
      { formattingOptions }
    );
    const modifiedText = jsonc.applyEdits(text, edits);

    const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(text.length));
    edit.replace(document.uri, fullRange, modifiedText);

    return edit;
  }

  /**
   * Create edit to remove reverseSync exclude patterns
   */
  private createRemoveExcludePatternsEdit(
    document: vscode.TextDocument,
    diagnostic: vscode.Diagnostic
  ): vscode.WorkspaceEdit {
    const edit = new vscode.WorkspaceEdit();
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);

    if (!rootNode) {
      return edit;
    }

    const formattingOptions = this.detectIndentationStyle(text);
    const offset = document.offsetAt(diagnostic.range.start);

    // Check if this is in root settings or folder settings
    const folderIndex = this.findFolderIndexAtOffset(rootNode, offset);

    let modifiedText = text;

    if (folderIndex === -1) {
      // Root level - remove from root settings
      const edits = jsonc.modify(
        modifiedText,
        ['settings', SETTINGS_KEYS.reverseSyncFolderSettingsExclude],
        undefined,
        { formattingOptions }
      );
      modifiedText = jsonc.applyEdits(modifiedText, edits);
    } else {
      // Folder level - remove from folder settings
      const edits = jsonc.modify(
        modifiedText,
        ['folders', folderIndex, 'settings', SETTINGS_KEYS.reverseSyncFolderSettingsExclude],
        undefined,
        { formattingOptions }
      );
      modifiedText = jsonc.applyEdits(modifiedText, edits);
    }

    const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(text.length));
    edit.replace(document.uri, fullRange, modifiedText);

    return edit;
  }

  /**
   * Create edit to enable reverseSync
   */
  private createEnableReverseSyncEdit(
    document: vscode.TextDocument,
    diagnostic: vscode.Diagnostic
  ): vscode.WorkspaceEdit {
    const edit = new vscode.WorkspaceEdit();
    const text = document.getText();
    const rootNode = jsonc.parseTree(text);

    if (!rootNode) {
      return edit;
    }

    const formattingOptions = this.detectIndentationStyle(text);
    const offset = document.offsetAt(diagnostic.range.start);

    // Check if this is in root settings or folder settings
    const folderIndex = this.findFolderIndexAtOffset(rootNode, offset);

    let modifiedText = text;

    if (folderIndex === -1) {
      // Root level - enable reverseSync in root settings
      const edits = jsonc.modify(
        modifiedText,
        ['settings', SETTINGS_KEYS.reverseSyncEnabled],
        true,
        { formattingOptions }
      );
      modifiedText = jsonc.applyEdits(modifiedText, edits);
    } else {
      // Folder level - enable reverseSync in folder settings
      const edits = jsonc.modify(
        modifiedText,
        ['folders', folderIndex, 'settings', SETTINGS_KEYS.reverseSyncEnabled],
        true,
        { formattingOptions }
      );
      modifiedText = jsonc.applyEdits(modifiedText, edits);
    }

    const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(text.length));
    edit.replace(document.uri, fullRange, modifiedText);

    return edit;
  }
}
