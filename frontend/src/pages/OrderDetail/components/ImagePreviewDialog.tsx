/**
 * Fullscreen image preview dialog.
 */

import { Icon } from "@/components/icons";
import { Dialog, DialogContent } from "@/components/ui/dialog";

interface ImagePreviewDialogProps {
  image: { src: string; alt: string } | null;
  onClose: () => void;
}

export function ImagePreviewDialog({ image, onClose }: ImagePreviewDialogProps) {
  return (
    <Dialog open={!!image} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-[95vw] max-h-[95vh] w-auto h-auto p-0 border-0 bg-transparent">
        <div className="relative bg-black/90 rounded-lg overflow-hidden">
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
              className="max-w-[90vw] max-h-[90vh] object-contain"
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
