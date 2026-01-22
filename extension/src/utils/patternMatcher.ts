/**
 * Pattern matcher using picomatch with negation support
 *
 * Patterns starting with ! are treated as negations (explicitly include).
 * Regular patterns are treated as exclusions.
 *
 * Examples:
 *   - "editor*" excludes all settings starting with "editor"
 *   - "!editor.fontSize" explicitly includes editor.fontSize even if another pattern would exclude it
 */

import picomatch from 'picomatch';

export class PatternMatcher {
  private includePatterns: string[];
  private negationPatterns: string[]; // patterns starting with ! (explicitly include)

  constructor(patterns: string[]) {
    this.negationPatterns = patterns.filter((p) => p.startsWith('!')).map((p) => p.slice(1));
    this.includePatterns = patterns.filter((p) => !p.startsWith('!'));
  }

  /**
   * Check if a settings key should be excluded based on patterns
   *
   * @param key - The settings key to check (e.g., "editor.fontSize")
   * @returns true if the key should be excluded, false otherwise
   */
  isExcluded(key: string): boolean {
    // If explicitly included via negation pattern, not excluded
    if (this.negationPatterns.some((p) => picomatch.isMatch(key, p))) {
      return false;
    }

    // If matches any include (exclusion) pattern, it's excluded
    return this.includePatterns.some((p) => picomatch.isMatch(key, p));
  }

  /**
   * Filter a settings object, removing excluded keys
   *
   * @param settings - The settings object to filter
   * @returns New settings object with excluded keys removed
   */
  filterSettings<T extends Record<string, unknown>>(settings: T): Partial<T> {
    const result: Partial<T> = {};

    for (const [key, value] of Object.entries(settings)) {
      if (!this.isExcluded(key)) {
        result[key as keyof T] = value as T[keyof T];
      }
    }

    return result;
  }
}
