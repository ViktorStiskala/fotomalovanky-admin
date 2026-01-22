/**
 * Diagnostics service
 *
 * Provides IDE diagnostics (errors, warnings) for workspace configuration issues.
 */

import * as vscode from 'vscode';
import * as fs from 'fs/promises';
import * as jsonc from 'jsonc-parser';
import { WorkspaceConfigService } from './workspaceConfig';

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

    const text = await fs.readFile(workspacePath, 'utf-8');
    const rootNode = jsonc.parseTree(text);

    if (!rootNode) {
      return diagnostics;
    }

    // Find the folders array
    const foldersNode = jsonc.findNodeAtLocation(rootNode, ['folders']);
    if (!foldersNode || !foldersNode.children) {
      return diagnostics;
    }

    // Check each folder
    for (let i = 0; i < foldersNode.children.length; i++) {
      const folderNode = foldersNode.children[i];
      const pathNode = jsonc.findNodeAtLocation(rootNode, ['folders', i, 'path']);
      if (!pathNode || pathNode.value === undefined) {
        continue;
      }

      const folderPath = pathNode.value as string;
      const isRoot = await this.workspaceConfig.isWorkspaceRoot(folderPath);

      // Check for flat "settings.xxx" keys on ALL folders
      const flatSettingsKeys = this.findFlatSettingsKeys(folderNode);
      for (const propertyNode of flatSettingsKeys) {
        const range = this.nodeToRange(text, propertyNode);
        const diagnostic = new vscode.Diagnostic(
          range,
          'Flat settings syntax is not supported. Use a nested "settings" object instead.',
          vscode.DiagnosticSeverity.Hint
        );
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
            'Settings on the root folder are ignored. Use root "settings" instead.',
            vscode.DiagnosticSeverity.Hint
          );
          diagnostic.tags = [vscode.DiagnosticTag.Unnecessary];
          diagnostic.source = 'Workspace Manager';
          diagnostic.code = 'root-folder-settings';
          diagnostics.push(diagnostic);
        }
      }
    }

    return diagnostics;
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
   * Returns property nodes for keys that start with "settings."
   */
  private findFlatSettingsKeys(folderNode: jsonc.Node): jsonc.Node[] {
    const result: jsonc.Node[] = [];
    if (folderNode.type !== 'object' || !folderNode.children) {
      return result;
    }

    for (const child of folderNode.children) {
      if (child.type === 'property' && child.children?.[0]) {
        const keyNode = child.children[0];
        if (keyNode.type === 'string' && keyNode.value?.startsWith?.('settings.')) {
          result.push(child);
        }
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
