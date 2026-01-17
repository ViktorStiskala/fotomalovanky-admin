/**
 * Image card component for displaying an image with coloring/SVG generation controls.
 */

import { useState } from "react";
import type { OrderImage } from "@/lib/api";
import { isColoringProcessing, isSvgProcessing, hasCompletedColoring } from "@/lib/statusHelpers";
import { useImageMutations } from "./hooks/useImageMutations";
import {
  ColoringControls,
  SvgControls,
  OriginalImageDisplay,
  VersionTabs,
  ImagePreviewDialog,
} from "./components";

interface ImageCardProps {
  image: OrderImage;
  orderId: string; // ULID string
}

export function ImageCard({ image, orderId }: ImageCardProps) {
  const [previewImage, setPreviewImage] = useState<{ src: string; alt: string } | null>(null);

  const coloringVersions = image.versions.coloring;
  const svgVersions = image.versions.svg;

  // Processing state checks
  const coloringProcessing = isColoringProcessing(coloringVersions);
  const svgProcessing = isSvgProcessing(svgVersions);
  const hasCompleted = hasCompletedColoring(coloringVersions);

  // Find selected coloring for SVG controls
  const selectedColoring = coloringVersions.find(
    (cv) => cv.id === image.selected_version_ids.coloring
  );

  // Setup mutations
  const {
    generateColoringMutation,
    generateSvgMutation,
    selectColoringMutation,
    selectSvgMutation,
    retryColoringMutation,
    retrySvgMutation,
  } = useImageMutations({
    imageId: image.id,
    orderId,
  });

  return (
    <div className="space-y-4" data-image-id={image.id}>
      {/* Original Image */}
      <OriginalImageDisplay
        url={image.url}
        position={image.position}
        uploadedAt={image.uploaded_at}
        onFullscreen={setPreviewImage}
      />

      {/* Coloring Generation Controls */}
      <ColoringControls
        disabled={!image.url}
        isProcessing={coloringProcessing}
        isPending={generateColoringMutation.isPending}
        onGenerate={(settings) => generateColoringMutation.mutate(settings)}
      />

      {/* SVG Generation Controls */}
      <SvgControls
        selectedColoring={selectedColoring}
        hasCompletedColoring={hasCompleted}
        isProcessing={svgProcessing}
        isPending={generateSvgMutation.isPending}
        onGenerate={(settings) => generateSvgMutation.mutate(settings)}
      />

      {/* Version Tabs */}
      <VersionTabs
        coloringVersions={coloringVersions}
        svgVersions={svgVersions}
        selectedVersionIds={image.selected_version_ids}
        onSelectColoring={(id) => selectColoringMutation.mutate(id)}
        onSelectSvg={(id) => selectSvgMutation.mutate(id)}
        onRetryColoring={(id) => retryColoringMutation.mutate(id)}
        onRetrySvg={(id) => retrySvgMutation.mutate(id)}
        onFullscreen={setPreviewImage}
        isRetryingColoring={retryColoringMutation.isPending}
        isRetryingSvg={retrySvgMutation.isPending}
      />

      {/* Image Preview Dialog */}
      <ImagePreviewDialog image={previewImage} onClose={() => setPreviewImage(null)} />
    </div>
  );
}
