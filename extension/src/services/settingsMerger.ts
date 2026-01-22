/**
 * Settings merger service
 *
 * Handles deep merging of settings objects with support for:
 * - Deep merging nested objects
 * - null values to remove keys from merged output
 * - Array replacement (not merging)
 */

import type { Settings } from '../types';

export class SettingsMerger {
  /**
   * Deep merge two settings objects
   *
   * @param base - Base settings (e.g., root workspace settings)
   * @param override - Override settings (e.g., folder-specific settings)
   * @returns Merged settings object
   */
  merge(base: Settings, override: Settings): Settings {
    const result = structuredClone(base);

    for (const [key, value] of Object.entries(override)) {
      if (value === null) {
        // null means "remove from merged output"
        delete result[key];
      } else if (this.isPlainObject(value) && this.isPlainObject(result[key])) {
        // Deep merge objects
        result[key] = this.merge(result[key] as Settings, value as Settings);
      } else {
        // Replace value (including arrays)
        result[key] = structuredClone(value);
      }
    }

    return result;
  }

  /**
   * Check if a value is a plain object (not an array or null)
   */
  private isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  /**
   * Calculate the diff between two settings objects
   *
   * Returns the settings in `current` that differ from `expected`.
   * This is used for reverse sync to find what the user changed.
   *
   * @param expected - The expected settings (what forward sync would generate)
   * @param current - The current settings (from .vscode/settings.json)
   * @returns Settings that differ from expected
   */
  diff(expected: Settings, current: Settings): Settings {
    const result: Settings = {};

    // Find keys in current that differ from expected
    for (const [key, currentValue] of Object.entries(current)) {
      const expectedValue = expected[key];

      if (!this.deepEqual(currentValue, expectedValue)) {
        result[key] = structuredClone(currentValue);
      }
    }

    // Find keys in expected that are missing in current (removed by user)
    for (const key of Object.keys(expected)) {
      if (!(key in current)) {
        // User removed this key, mark as null to remove from folder settings
        result[key] = null;
      }
    }

    return result;
  }

  /**
   * Deep equality check for two values
   */
  private deepEqual(a: unknown, b: unknown): boolean {
    if (a === b) return true;
    if (typeof a !== typeof b) return false;
    if (a === null || b === null) return a === b;

    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return false;
      return a.every((item, index) => this.deepEqual(item, b[index]));
    }

    if (this.isPlainObject(a) && this.isPlainObject(b)) {
      const aKeys = Object.keys(a);
      const bKeys = Object.keys(b);

      if (aKeys.length !== bKeys.length) return false;
      return aKeys.every((key) => this.deepEqual(a[key], b[key]));
    }

    return false;
  }
}
