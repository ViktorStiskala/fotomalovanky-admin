/**
 * Standalone script to generate icon sprite and types.
 * Run this before TypeScript checks to ensure IconName type is up to date.
 *
 * Usage: npx tsx scripts/generateIcons.ts
 */

import path from "path";
import { fileURLToPath } from "url";
import { scanForIcons, generateSprite } from "./iconGenerator.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Main execution
const srcDir = path.resolve(__dirname, "../src");
const iconsDir = path.resolve(srcDir, "components/icons");

const icons = scanForIcons(srcDir);
generateSprite(icons, iconsDir);
