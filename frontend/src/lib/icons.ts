/**
 * Pre-register icons to avoid CDN requests at runtime.
 * Icons are bundled into the JavaScript at build time.
 */
import { addIcon } from "@iconify/react";
import { icons as mdiIcons } from "@iconify-json/mdi";

// Register only the icons we use
const iconsToRegister = ["fullscreen", "refresh", "close-box-outline"] as const;

for (const name of iconsToRegister) {
  const iconData = mdiIcons.icons[name];
  if (iconData) {
    addIcon(`mdi:${name}`, {
      body: iconData.body,
      width: iconData.width ?? mdiIcons.width ?? 24,
      height: iconData.height ?? mdiIcons.height ?? 24,
    });
  }
}
