/**
 * SVG sprite containing all icons used in the app.
 * Render this once at the app root - icons are then referenced via <use>.
 */
export function IconSprite() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}
      aria-hidden="true"
    >
      <defs>
        {/* mdi:fullscreen */}
        <symbol id="icon-fullscreen" viewBox="0 0 24 24">
          <path
            fill="currentColor"
            d="M5 5h5v2H7v3H5zm9 0h5v5h-2V7h-3zm3 9h2v5h-5v-2h3zm-7 3v2H5v-5h2v3z"
          />
        </symbol>

        {/* mdi:refresh */}
        <symbol id="icon-refresh" viewBox="0 0 24 24">
          <path
            fill="currentColor"
            d="M17.65 6.35A7.96 7.96 0 0 0 12 4a8 8 0 0 0-8 8a8 8 0 0 0 8 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18a6 6 0 0 1-6-6a6 6 0 0 1 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"
          />
        </symbol>

        {/* mdi:close-box-outline */}
        <symbol id="icon-close-box-outline" viewBox="0 0 24 24">
          <path
            fill="currentColor"
            d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2m0 16H5V5h14zm-3.4-12L12 10.6L8.4 7L7 8.4l3.6 3.6L7 15.6L8.4 17l3.6-3.6l3.6 3.6l1.4-1.4l-3.6-3.6l3.6-3.6z"
          />
        </symbol>
      </defs>
    </svg>
  );
}
