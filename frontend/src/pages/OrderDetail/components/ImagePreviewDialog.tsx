/**
 * Fullscreen image preview dialog.
 * Uses Radix UI "scrollable overlay" pattern for proper centering.
 * Works universally for PNG, JPG, and SVG files.
 */

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Icon } from "@/components/icons";

interface ImagePreviewDialogProps {
  image: { src: string; alt: string } | null;
  onClose: () => void;
}

export function ImagePreviewDialog({ image, onClose }: ImagePreviewDialogProps) {
  return (
    <DialogPrimitive.Root open={!!image} onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/90 grid place-items-center data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0">
          <DialogPrimitive.Content
            className="relative outline-none"
            aria-describedby={undefined}
          >
            <DialogPrimitive.Title className="sr-only">
              {image?.alt ?? "Náhled obrázku"}
            </DialogPrimitive.Title>
            <button
              className="absolute top-3 right-3 p-1.5 bg-white/20 hover:bg-white/30 rounded text-white z-10"
              onClick={onClose}
            >
              <Icon name="mdi-close-box-outline" className="w-6 h-6" />
            </button>
            {image && (
              <img
                src={image.src}
                alt={image.alt}
                className="w-[90vw] h-[90vh] object-contain"
              />
            )}
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
