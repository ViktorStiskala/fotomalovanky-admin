/**
 * Vite plugin for auto-generating IconSprite.tsx from @iconify/json.
 *
 * This plugin:
 * 1. Scans source files for `<Icon name="..." />` usages
 * 2. Extracts unique icon names
 * 3. Fetches SVG data from @iconify-json/mdi
 * 4. Generates IconSprite.tsx with only the used icons
 * 5. Updates IconName type in Icon.tsx
 */

import type { Plugin } from "vite";
import path from "path";
import { scanForIcons, generateSprite } from "./iconGenerator";

export function iconSpritePlugin(): Plugin {
  let srcDir: string;
  let iconsDir: string;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function regenerate() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const icons = scanForIcons(srcDir);
      generateSprite(icons, iconsDir);
    }, 100);
  }

  return {
    name: "icon-sprite-generator",

    configResolved(config) {
      srcDir = path.resolve(config.root, "src");
      iconsDir = path.resolve(srcDir, "components/icons");
    },

    buildStart() {
      const icons = scanForIcons(srcDir);
      generateSprite(icons, iconsDir);
    },

    handleHotUpdate({ file }) {
      // Regenerate on file changes in src/ (excluding the generated files)
      if (
        file.includes(srcDir) &&
        !file.endsWith("IconSprite.tsx") &&
        !file.endsWith("Icon.tsx") &&
        /\.(tsx?|jsx?)$/.test(file)
      ) {
        regenerate();
      }
    },
  };
}
