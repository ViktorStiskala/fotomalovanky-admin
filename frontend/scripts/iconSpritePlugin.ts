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
import fs from "fs";
import path from "path";

interface IconifyIcon {
  body: string;
  width?: number;
  height?: number;
}

interface IconifyJSON {
  icons: Record<string, IconifyIcon>;
  width?: number;
  height?: number;
}

function loadIconifyData(): IconifyJSON {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mdiIcons = require("@iconify-json/mdi");
    return mdiIcons.icons as IconifyJSON;
  } catch {
    console.warn("@iconify-json/mdi not installed. Run: npm install -D @iconify-json/mdi");
    return { icons: {} };
  }
}

function scanForIcons(srcDir: string): Set<string> {
  const iconNames = new Set<string>();

  function scanDir(dir: string) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });

    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);

      if (entry.isDirectory()) {
        // Skip node_modules and generated files
        if (entry.name === "node_modules" || entry.name === ".git") continue;
        scanDir(fullPath);
      } else if (entry.isFile() && /\.(tsx?|jsx?)$/.test(entry.name)) {
        // Skip the IconSprite.tsx file itself to avoid circular scanning
        if (entry.name === "IconSprite.tsx") continue;

        const content = fs.readFileSync(fullPath, "utf-8");
        // Match <Icon name="icon-name" /> or <Icon name='icon-name' />
        const matches = content.matchAll(/<Icon[^>]+name=["']([^"']+)["']/g);
        for (const match of matches) {
          iconNames.add(match[1]);
        }
      }
    }
  }

  scanDir(srcDir);
  return iconNames;
}

function generateSprite(icons: Set<string>, iconsDir: string): void {
  const iconifyData = loadIconifyData();
  const iconEntries: Array<{ name: string; body: string; viewBox: string }> = [];

  for (const iconName of Array.from(icons).sort()) {
    // Icon names can be "mdi-fullscreen" or just "fullscreen"
    const mdiName = iconName.replace(/^mdi-/, "");

    const iconData = iconifyData.icons[mdiName];
    if (iconData) {
      const width = iconData.width || iconifyData.width || 24;
      const height = iconData.height || iconifyData.height || 24;
      iconEntries.push({
        name: iconName,
        body: iconData.body,
        viewBox: `0 0 ${width} ${height}`,
      });
    } else {
      console.warn(`Icon "${iconName}" not found in @iconify-json/mdi`);
    }
  }

  // Generate IconSprite.tsx
  const spriteContent = `/**
 * SVG sprite containing all icons used in the app.
 * Render this once at the app root - icons are then referenced via <use>.
 *
 * AUTO-GENERATED - DO NOT EDIT MANUALLY
 * Run \`npm run build\` or restart dev server to regenerate.
 */
export function IconSprite() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}
      aria-hidden="true"
    >
      <defs>
${iconEntries
  .map(
    (icon) => `        {/* ${icon.name} */}
        <symbol id="icon-${icon.name}" viewBox="${icon.viewBox}">
          ${icon.body}
        </symbol>`
  )
  .join("\n\n")}
      </defs>
    </svg>
  );
}
`;

  // Generate IconName type for Icon.tsx
  const iconNames = iconEntries.map((i) => `"${i.name}"`).join(" | ");
  const iconTypeContent = `import type { SVGProps } from "react";

/**
 * Available icon names.
 * AUTO-GENERATED - DO NOT EDIT MANUALLY
 */
export type IconName = ${iconNames || '"placeholder"'};

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
}

/**
 * Icon component that references SVG symbols from IconSprite.
 * Each icon SVG is defined once in the sprite and reused via <use>.
 */
export function Icon({ name, className, ...props }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
      {...props}
    >
      <use href={\`#icon-\${name}\`} />
    </svg>
  );
}
`;

  const spritePath = path.join(iconsDir, "IconSprite.tsx");
  const iconPath = path.join(iconsDir, "Icon.tsx");

  // Only write if content changed
  const existingSprite = fs.existsSync(spritePath) ? fs.readFileSync(spritePath, "utf-8") : "";
  const existingIcon = fs.existsSync(iconPath) ? fs.readFileSync(iconPath, "utf-8") : "";

  if (existingSprite !== spriteContent) {
    fs.writeFileSync(spritePath, spriteContent);
    console.log(`[icon-sprite] Generated ${spritePath} with ${iconEntries.length} icons`);
  }

  if (existingIcon !== iconTypeContent) {
    fs.writeFileSync(iconPath, iconTypeContent);
    console.log(`[icon-sprite] Updated ${iconPath} with IconName type`);
  }
}

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
