/**
 * Quick Fix Hint Helper
 *
 * Provides platform-aware Quick Fix keybinding hints for diagnostic messages.
 * Caches the result since keybindings rarely change during a session.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs/promises';
import * as jsonc from 'jsonc-parser';

// Cache the hint string - keybindings rarely change during a session
let cachedHint: string | null = null;

/**
 * Get the user's keybindings.json path based on platform and app
 */
function getKeybindingsPath(): string {
  const appName = vscode.env.appName.toLowerCase().includes('cursor') ? 'Cursor' : 'Code';

  switch (process.platform) {
    case 'darwin':
      return path.join(
        process.env.HOME || '',
        'Library/Application Support',
        appName,
        'User/keybindings.json'
      );
    case 'win32':
      return path.join(process.env.APPDATA || '', appName, 'User/keybindings.json');
    default:
      return path.join(process.env.HOME || '', '.config', appName, 'User/keybindings.json');
  }
}

/**
 * Get the default Quick Fix keybinding based on platform
 */
function getDefaultKeybinding(): string {
  return process.platform === 'darwin' ? 'Cmd+.' : 'Ctrl+.';
}

/**
 * Format a keybinding string for display (capitalize modifiers)
 */
function formatKeybinding(keybinding: string): string {
  const isMac = process.platform === 'darwin';
  return keybinding
    .replace(/meta/gi, isMac ? 'Cmd' : 'Win')
    .replace(/cmd/gi, 'Cmd')
    .replace(/ctrl/gi, 'Ctrl')
    .replace(/alt/gi, 'Alt')
    .replace(/shift/gi, 'Shift')
    .replace(/win/gi, 'Win');
}

/**
 * Try to find user's custom keybinding for Quick Fix command
 */
async function getUserKeybinding(): Promise<string | null> {
  try {
    const content = await fs.readFile(getKeybindingsPath(), 'utf-8');
    const keybindings = jsonc.parse(content) as Array<{ key: string; command: string }>;
    const binding = keybindings.filter((kb) => kb.command === 'editor.action.quickFix').pop();
    return binding?.key ?? null;
  } catch {
    return null;
  }
}

/**
 * Initialize the Quick Fix hint (call once at extension activation)
 *
 * Reads the user's keybindings.json to find any custom Quick Fix binding,
 * falls back to platform default (Cmd+. on macOS, Ctrl+. on Windows/Linux).
 */
export async function initQuickFixHint(): Promise<void> {
  const customBinding = await getUserKeybinding();
  const keybinding = formatKeybinding(customBinding ?? getDefaultKeybinding());
  cachedHint = `**Quick Fix available:** press ${keybinding} to resolve automatically.`;
}

/**
 * Get the cached Quick Fix hint string
 *
 * Returns a formatted string suitable for appending to diagnostic messages.
 * Call initQuickFixHint() first during extension activation.
 */
export function getQuickFixHint(): string {
  return cachedHint ?? '**Quick Fix available** to resolve automatically.';
}
