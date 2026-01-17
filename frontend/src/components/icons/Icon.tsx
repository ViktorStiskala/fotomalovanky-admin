import type { SVGProps } from "react";

/**
 * Available icon names.
 * AUTO-GENERATED - DO NOT EDIT MANUALLY
 */
export type IconName = "mdi-close-box-outline" | "mdi-fullscreen" | "mdi-refresh";

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
      <use href={`#icon-${name}`} />
    </svg>
  );
}
