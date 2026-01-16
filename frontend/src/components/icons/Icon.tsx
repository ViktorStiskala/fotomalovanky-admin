import type { SVGProps } from "react";

export type IconName = "fullscreen" | "refresh" | "close-box-outline";

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
