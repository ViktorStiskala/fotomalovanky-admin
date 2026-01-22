/**
 * TypeScript interfaces for Workspace Manager extension
 */

/**
 * Raw settings object from workspace file or .vscode/settings.json
 */
export type Settings = Record<string, unknown>;

/**
 * Folder definition from .code-workspace file
 */
export interface FolderConfig {
  name?: string;
  path: string;
  settings?: Settings;
}

/**
 * Parsed workspace file structure
 */
export interface WorkspaceFile {
  folders: FolderConfig[];
  settings: Settings;
}

/**
 * Extension settings (workspaceManager.*)
 */
export interface ExtensionSettings {
  /** Master toggle for the extension */
  enabled: boolean;
  /** Enable automatic sync via file watchers */
  autoSync: boolean;
  /** Forward sync settings */
  sync: {
    /** Enable forward sync (root settings -> folder .vscode/settings.json) */
    enabled: boolean;
    /** Patterns to exclude from forward sync (picomatch with ! negation) */
    excludePatterns: string[];
  };
  /** Reverse sync settings */
  reverseSync: {
    /** Enable reverse sync (folder UI changes -> workspace file) */
    enabled: boolean;
    /** Patterns to exclude from reverse sync (picomatch with ! negation) */
    excludePatterns: string[];
  };
}

/**
 * Default extension settings
 */
export const DEFAULT_EXTENSION_SETTINGS: ExtensionSettings = {
  enabled: true,
  autoSync: false,
  sync: {
    enabled: true,
    excludePatterns: [],
  },
  reverseSync: {
    enabled: true,
    excludePatterns: [],
  },
};

/**
 * Settings keys for the extension configuration
 */
export const SETTINGS_KEYS = {
  enabled: 'workspaceManager.enabled',
  autoSyncEnabled: 'workspaceManager.autoSync.enabled',
  syncEnabled: 'workspaceManager.sync.enabled',
  syncRootSettingsExclude: 'workspaceManager.sync.rootSettings.exclude',
  syncSubFolderSettingsDefaults: 'workspaceManager.sync.subFolderSettings.defaults',
  reverseSyncEnabled: 'workspaceManager.reverseSync.enabled',
  reverseSyncFolderSettingsExclude: 'workspaceManager.reverseSync.folderSettings.exclude',
} as const;

/**
 * Prefix for all workspaceManager settings - used to filter them from output
 */
export const WORKSPACE_MANAGER_PREFIX = 'workspaceManager';
