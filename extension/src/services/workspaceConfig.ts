/**
 * Workspace configuration service
 *
 * Handles reading and writing .code-workspace files with JSON5 support
 */

import * as vscode from 'vscode';
import * as fs from 'fs/promises';
import * as path from 'path';
import JSON5 from 'json5';
import type { FolderConfig, Settings, WorkspaceFile } from '../types';

export class WorkspaceConfigService {
  private workspacePath: string | undefined;

  constructor() {
    this.workspacePath = this.findWorkspaceFile();
  }

  /**
   * Find the .code-workspace file for the current workspace
   */
  private findWorkspaceFile(): string | undefined {
    const workspaceFile = vscode.workspace.workspaceFile;
    if (workspaceFile && workspaceFile.scheme === 'file') {
      return workspaceFile.fsPath;
    }
    return undefined;
  }

  /**
   * Get the workspace file path
   */
  getWorkspacePath(): string | undefined {
    return this.workspacePath;
  }

  /**
   * Get the workspace root directory
   */
  getWorkspaceDir(): string | undefined {
    return this.workspacePath ? path.dirname(this.workspacePath) : undefined;
  }

  /**
   * Check if a workspace file is available
   */
  hasWorkspaceFile(): boolean {
    return this.workspacePath !== undefined;
  }

  /**
   * Load and parse the workspace file
   */
  async load(): Promise<WorkspaceFile> {
    if (!this.workspacePath) {
      throw new Error('No workspace file found');
    }

    const content = await fs.readFile(this.workspacePath, 'utf-8');
    const data = JSON5.parse(content) as WorkspaceFile;

    return {
      folders: data.folders || [],
      settings: data.settings || {},
    };
  }

  /**
   * Save the workspace file
   *
   * Preserves JSON5 formatting by using JSON.stringify with indentation
   */
  async save(workspaceFile: WorkspaceFile): Promise<void> {
    if (!this.workspacePath) {
      throw new Error('No workspace file found');
    }

    // Read the original file to preserve any extra fields
    const content = await fs.readFile(this.workspacePath, 'utf-8');
    const originalData = JSON5.parse(content) as Record<string, unknown>;

    // Update only folders and settings
    const updatedData = {
      ...originalData,
      folders: workspaceFile.folders,
      settings: workspaceFile.settings,
    };

    // Write back with proper formatting
    const output = JSON.stringify(updatedData, null, '\t') + '\n';
    await fs.writeFile(this.workspacePath, output, 'utf-8');
  }

  /**
   * Update settings for a specific folder
   *
   * @param folderPath - The folder path (relative to workspace root)
   * @param newSettings - The new settings to merge into folder.settings
   */
  async updateFolderSettings(folderPath: string, newSettings: Settings): Promise<void> {
    const workspace = await this.load();

    const folderIndex = workspace.folders.findIndex((f) => f.path === folderPath);
    if (folderIndex === -1) {
      throw new Error(`Folder not found: ${folderPath}`);
    }

    const folder = workspace.folders[folderIndex];

    // Merge new settings into existing folder settings
    workspace.folders[folderIndex] = {
      ...folder,
      settings: {
        ...folder.settings,
        ...newSettings,
      },
    };

    await this.save(workspace);
  }

  /**
   * Get the folders defined in the workspace (excluding root ".")
   */
  async getFolders(): Promise<FolderConfig[]> {
    const workspace = await this.load();
    return workspace.folders.filter((f) => f.path !== '.');
  }

  /**
   * Get a specific folder by path
   */
  async getFolder(folderPath: string): Promise<FolderConfig | undefined> {
    const workspace = await this.load();
    return workspace.folders.find((f) => f.path === folderPath);
  }

  /**
   * Get global settings from the workspace file
   */
  async getGlobalSettings(): Promise<Settings> {
    const workspace = await this.load();
    return workspace.settings;
  }

  /**
   * Resolve a relative folder path to an absolute path
   */
  resolveFolderPath(folderPath: string): string {
    const workspaceDir = this.getWorkspaceDir();
    if (!workspaceDir) {
      throw new Error('No workspace directory found');
    }
    return path.join(workspaceDir, folderPath);
  }
}
