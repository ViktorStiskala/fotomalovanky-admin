/**
 * Displays the original uploaded image with fullscreen button.
 */

import { Icon } from "@/components/icons";

interface OriginalImageDisplayProps {
  url: string | null;
  position: number;
  uploadedAt: string | null;
  onFullscreen: (image: { src: string; alt: string }) => void;
}

export function OriginalImageDisplay({
  url,
  position,
  uploadedAt,
  onFullscreen,
}: OriginalImageDisplayProps) {
  return (
    <div className="h-[32rem] bg-muted rounded overflow-hidden relative flex items-center justify-center group">
      {url ? (
        <>
          <img
            src={url}
            alt={`Fotka ${position}`}
            className="max-w-full max-h-full object-contain"
            onError={(e) => {
              e.currentTarget.style.display = "none";
              const placeholder = e.currentTarget.parentElement?.querySelector(
                ".placeholder"
              ) as HTMLElement;
              if (placeholder) placeholder.style.display = "flex";
            }}
          />
          <button
            className="absolute top-2 right-2 p-1.5 bg-black/50 hover:bg-black/70 rounded text-white opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={() =>
              onFullscreen({
                src: url,
                alt: `Fotka ${position}`,
              })
            }
          >
            <Icon name="mdi-fullscreen" className="w-5 h-5" />
          </button>
        </>
      ) : null}
      <div
        className="placeholder absolute inset-0 items-center justify-center text-muted-foreground text-sm"
        style={{ display: url ? "none" : "flex" }}
      >
        {uploadedAt ? "Nahráno" : "Čeká na nahrání"}
      </div>
    </div>
  );
}
