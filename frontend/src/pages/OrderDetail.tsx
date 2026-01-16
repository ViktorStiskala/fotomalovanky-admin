import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Icon } from "@iconify/react";
import {
  fetchOrder,
  syncOrder,
  getImageUrl,
  getShopifyOrderUrl,
  getColoringVersionUrl,
  getSvgVersionUrl,
  generateOrderColoring,
  generateOrderSvg,
  generateImageColoring,
  generateImageSvg,
  selectColoringVersion,
  selectSvgVersion,
  retryColoringVersion,
  retrySvgVersion,
  type OrderImage,
} from "@/lib/api";
import { useOrderEvents } from "@/hooks/useOrderEvents";
import { queryClient } from "@/lib/queryClient";
import { ORDER_STATUS_DISPLAY, getPaymentStatusDisplay, getProcessingStatusDisplay } from "@/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";

// =============================================================================
// Helpers
// =============================================================================

function getShapeStackingLabel(value: string): string {
  const labels: Record<string, string> = {
    stacked: "Vrstvené",
    none: "Žádné",
  };
  return labels[value] || value;
}

function getGroupByLabel(value: string): string {
  const labels: Record<string, string> = {
    color: "Podle barvy",
    none: "Žádné",
  };
  return labels[value] || value;
}

// =============================================================================
// Image Card Component
// =============================================================================

interface ImageCardProps {
  image: OrderImage;
  orderNumber: string;
}

function ImageCard({ image, orderNumber }: ImageCardProps) {
  const [activeTab, setActiveTab] = useState<"coloring" | "svg">("coloring");
  const [showColoringSettings, setShowColoringSettings] = useState(false);
  const [showSvgSettings, setShowSvgSettings] = useState(false);
  const [coloringMegapixels, setColoringMegapixels] = useState(1.0);
  const [coloringSteps, setColoringSteps] = useState(4);
  const [svgShapeStacking, setSvgShapeStacking] = useState("stacked");
  const [svgGroupBy, setSvgGroupBy] = useState("color");
  const [previewImage, setPreviewImage] = useState<{ src: string; alt: string } | null>(null);

  // Derive SVG versions from coloring versions (now included in order response)
  const svgVersions = image.coloring_versions
    .flatMap((cv) => cv.svg_versions || [])
    .sort((a, b) => b.version - a.version);

  // Find selected versions
  const selectedColoring = image.coloring_versions.find(
    (cv) => cv.id === image.selected_coloring_id
  );
  const hasCompletedColoring = image.coloring_versions.some((cv) => cv.status === "completed");
  const isColoringProcessing = image.coloring_versions.some(
    (cv) => cv.status === "queued" || cv.status === "processing"
  );

  // Generate coloring mutation
  const generateColoringMutation = useMutation({
    mutationFn: () =>
      generateImageColoring(image.id, {
        megapixels: coloringMegapixels,
        steps: coloringSteps,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
      setShowColoringSettings(false);
    },
  });

  // Generate SVG mutation
  const generateSvgMutation = useMutation({
    mutationFn: () =>
      generateImageSvg(image.id, {
        shape_stacking: svgShapeStacking,
        group_by: svgGroupBy,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
      setShowSvgSettings(false);
    },
  });

  // Select coloring version mutation
  const selectColoringMutation = useMutation({
    mutationFn: (versionId: number) => selectColoringVersion(image.id, versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
    },
  });

  // Select SVG version mutation
  const selectSvgMutation = useMutation({
    mutationFn: (versionId: number) => selectSvgVersion(image.id, versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
    },
  });

  // Retry coloring version mutation
  const retryColoringMutation = useMutation({
    mutationFn: (versionId: number) => retryColoringVersion(versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
    },
  });

  // Retry SVG version mutation
  const retrySvgMutation = useMutation({
    mutationFn: (versionId: number) => retrySvgVersion(versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
    },
  });

  const isSvgProcessing = svgVersions.some(
    (sv) => sv.status === "queued" || sv.status === "processing"
  );

  return (
    <div className="space-y-4" data-image-id={image.id}>
      {/* Original Image */}
      <div className="h-[32rem] bg-muted rounded overflow-hidden relative flex items-center justify-center group">
        {image.local_path ? (
          <>
            <img
              src={getImageUrl(image.id)}
              alt={`Fotka ${image.position}`}
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
                setPreviewImage({
                  src: getImageUrl(image.id),
                  alt: `Fotka ${image.position}`,
                })
              }
            >
              <Icon icon="mdi:fullscreen" className="w-5 h-5" />
            </button>
          </>
        ) : null}
        <div
          className="placeholder absolute inset-0 items-center justify-center text-muted-foreground text-sm"
          style={{ display: image.local_path ? "none" : "flex" }}
        >
          {image.downloaded_at ? "Staženo" : "Čeká na stažení"}
        </div>
      </div>

      {/* Coloring Generation Controls */}
      <div className="border rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Vygenerovat omalovánku</span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowColoringSettings(!showColoringSettings)}
            >
              Nastavení
            </Button>
            <Button
              size="sm"
              onClick={() => generateColoringMutation.mutate()}
              disabled={
                !image.local_path || generateColoringMutation.isPending || isColoringProcessing
              }
            >
              {generateColoringMutation.isPending || isColoringProcessing
                ? "Generuji..."
                : "Generovat"}
            </Button>
          </div>
        </div>

        {showColoringSettings && (
          <div className="grid grid-cols-2 gap-4 pt-2 border-t">
            <div>
              <label className="text-xs text-muted-foreground">Megapixels</label>
              <input
                type="number"
                step="0.5"
                min="0.5"
                max="8"
                value={coloringMegapixels}
                onChange={(e) => setColoringMegapixels(parseFloat(e.target.value))}
                className="w-full mt-1 px-2 py-1 border rounded text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Steps</label>
              <input
                type="number"
                min="1"
                max="20"
                value={coloringSteps}
                onChange={(e) => setColoringSteps(parseInt(e.target.value))}
                className="w-full mt-1 px-2 py-1 border rounded text-sm"
              />
            </div>
          </div>
        )}
      </div>

      {/* SVG Generation Controls */}
      <div className="border rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Vygenerovat SVG</span>
            {!hasCompletedColoring && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                Nejprve vygenerujte omalovánku
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowSvgSettings(!showSvgSettings)}
              disabled={!hasCompletedColoring}
            >
              Nastavení
            </Button>
            <Button
              size="sm"
              onClick={() => generateSvgMutation.mutate()}
              disabled={!hasCompletedColoring || generateSvgMutation.isPending || isSvgProcessing}
            >
              {generateSvgMutation.isPending || isSvgProcessing ? "Generuji..." : "Generovat"}
            </Button>
          </div>
        </div>

        {showSvgSettings && hasCompletedColoring && (
          <div className="grid grid-cols-2 gap-4 pt-2 border-t">
            <div>
              <label className="text-xs text-muted-foreground">Vrstvení tvarů</label>
              <select
                value={svgShapeStacking}
                onChange={(e) => setSvgShapeStacking(e.target.value)}
                className="w-full mt-1 px-2 py-1 border rounded text-sm"
              >
                <option value="stacked">Vrstvené</option>
                <option value="none">Žádné</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Seskupení</label>
              <select
                value={svgGroupBy}
                onChange={(e) => setSvgGroupBy(e.target.value)}
                className="w-full mt-1 px-2 py-1 border rounded text-sm"
              >
                <option value="color">Podle barvy</option>
                <option value="none">Žádné</option>
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Version Switcher */}
      {(image.coloring_versions.length > 0 || svgVersions.length > 0) && (
        <div className="border rounded-lg p-4">
          {/* Tab Header */}
          <div className="flex gap-2 mb-4">
            <button
              className={`px-3 py-1 rounded text-sm font-medium ${
                activeTab === "coloring"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
              onClick={() => setActiveTab("coloring")}
            >
              Omalovánka ({image.coloring_versions.length})
            </button>
            <button
              className={`px-3 py-1 rounded text-sm font-medium ${
                activeTab === "svg"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
              onClick={() => setActiveTab("svg")}
            >
              SVG ({svgVersions.length})
            </button>
          </div>

          {/* Coloring Versions */}
          {activeTab === "coloring" && (
            <div className="space-y-3">
              {/* Preview area - always same height */}
              <div className="h-[32rem] bg-muted rounded overflow-hidden relative flex items-center justify-center group">
                {selectedColoring?.file_path ? (
                  <>
                    <img
                      src={getColoringVersionUrl(selectedColoring.id)}
                      alt={`Omalovánka v${selectedColoring.version}`}
                      className="max-w-full max-h-full object-contain"
                    />
                    <button
                      className="absolute top-2 right-2 p-1.5 bg-black/50 hover:bg-black/70 rounded text-white opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={() =>
                        setPreviewImage({
                          src: getColoringVersionUrl(selectedColoring.id),
                          alt: `Omalovánka v${selectedColoring.version}`,
                        })
                      }
                    >
                      <Icon icon="mdi:fullscreen" className="w-5 h-5" />
                    </button>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {image.coloring_versions.length === 0 ? "Žádné verze" : "Generování..."}
                  </p>
                )}
              </div>

              {/* Version list - always show container for consistent height */}
              <div className="flex flex-wrap gap-2 items-stretch min-h-[5rem]">
                {image.coloring_versions.map((cv) => {
                  const status = getProcessingStatusDisplay(cv.status);
                  const isSelected = cv.id === image.selected_coloring_id;
                  const isError = cv.status === "error";

                  return (
                    <button
                      key={cv.id}
                      className={`min-w-[7rem] px-3 py-2 rounded border text-sm flex flex-col gap-1 ${
                        isSelected
                          ? "border-primary bg-primary/10"
                          : "border-muted hover:border-primary/50"
                      }`}
                      onClick={() => {
                        if (cv.status === "completed" && !isSelected) {
                          selectColoringMutation.mutate(cv.id);
                        }
                      }}
                      disabled={cv.status !== "completed" && !isError}
                    >
                      <div className="font-medium">v{cv.version}</div>
                      <div className="text-xs text-muted-foreground">
                        {cv.megapixels}MP / {cv.steps}st
                      </div>
                      <div className="flex-1 flex items-center justify-center">
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded inline-flex items-center gap-1 ${status.color}`}
                        >
                          {status.label}
                          {isError && (
                            <Icon
                              icon="mdi:refresh"
                              className={`w-3.5 h-3.5 cursor-pointer hover:scale-125 transition-transform ${retryColoringMutation.isPending ? "animate-spin" : ""}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                retryColoringMutation.mutate(cv.id);
                              }}
                            />
                          )}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* SVG Versions */}
          {activeTab === "svg" && (
            <div className="space-y-3">
              {/* Preview area - always same height */}
              <div className="h-[32rem] bg-muted rounded overflow-hidden relative flex items-center justify-center group">
                {image.selected_svg_id ? (
                  <>
                    <img
                      src={getSvgVersionUrl(image.selected_svg_id)}
                      alt="SVG"
                      className="max-w-full max-h-full object-contain"
                    />
                    <button
                      className="absolute top-2 right-2 p-1.5 bg-black/50 hover:bg-black/70 rounded text-white opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={() =>
                        setPreviewImage({
                          src: getSvgVersionUrl(image.selected_svg_id!),
                          alt: "SVG",
                        })
                      }
                    >
                      <Icon icon="mdi:fullscreen" className="w-5 h-5" />
                    </button>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {svgVersions.length === 0 ? "Žádné SVG verze" : "Generování..."}
                  </p>
                )}
              </div>

              {/* SVG Version list - always show container for consistent height */}
              <div className="flex flex-wrap gap-2 items-stretch min-h-[5rem]">
                {svgVersions.map((sv) => {
                  const status = getProcessingStatusDisplay(sv.status);
                  const isSelected = sv.id === image.selected_svg_id;
                  const isError = sv.status === "error";
                  // Find the source coloring version number
                  const sourceColoring = image.coloring_versions.find(
                    (cv) => cv.id === sv.coloring_version_id
                  );
                  const sourceVersion = sourceColoring?.version ?? "?";

                  return (
                    <button
                      key={sv.id}
                      className={`min-w-[7rem] px-3 py-2 rounded border text-sm flex flex-col gap-1 ${
                        isSelected
                          ? "border-primary bg-primary/10"
                          : "border-muted hover:border-primary/50"
                      }`}
                      onClick={() => {
                        if (sv.status === "completed" && !isSelected) {
                          selectSvgMutation.mutate(sv.id);
                        }
                      }}
                      disabled={sv.status !== "completed" && !isError}
                    >
                      <div className="font-medium">
                        v{sv.version} (v{sourceVersion})
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {getShapeStackingLabel(sv.shape_stacking)} / {getGroupByLabel(sv.group_by)}
                      </div>
                      <div className="flex-1 flex items-center justify-center">
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded inline-flex items-center gap-1 ${status.color}`}
                        >
                          {status.label}
                          {isError && (
                            <Icon
                              icon="mdi:refresh"
                              className={`w-3.5 h-3.5 cursor-pointer hover:scale-125 transition-transform ${retrySvgMutation.isPending ? "animate-spin" : ""}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                retrySvgMutation.mutate(sv.id);
                              }}
                            />
                          )}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Image Preview Dialog */}
      <Dialog open={!!previewImage} onOpenChange={(open) => !open && setPreviewImage(null)}>
        <DialogContent className="max-w-[95vw] max-h-[95vh] w-auto h-auto p-0 border-0 bg-transparent">
          <div className="relative bg-black/90 rounded-lg overflow-hidden">
            <button
              className="absolute top-3 right-3 p-1.5 bg-white/20 hover:bg-white/30 rounded text-white z-10"
              onClick={() => setPreviewImage(null)}
            >
              <Icon icon="mdi:close-box-outline" className="w-6 h-6" />
            </button>
            {previewImage && (
              <img
                src={previewImage.src}
                alt={previewImage.alt}
                className="max-w-[90vw] max-h-[90vh] object-contain"
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// =============================================================================
// Main OrderDetail Component
// =============================================================================

export default function OrderDetail() {
  const { orderNumber } = useParams<{ orderNumber: string }>();
  const [dismissedSuccess, setDismissedSuccess] = useState(false);
  const [dismissedError, setDismissedError] = useState(false);

  // Subscribe to real-time updates for this specific order
  useOrderEvents(orderNumber || "");

  const {
    data: order,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["order", orderNumber],
    queryFn: () => fetchOrder(orderNumber!),
    enabled: !!orderNumber,
  });

  const syncMutation = useMutation({
    mutationFn: () => syncOrder(orderNumber!),
    onMutate: () => {
      setDismissedSuccess(false);
      setDismissedError(false);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
  });

  // Generate all coloring mutation
  const generateAllColoringMutation = useMutation({
    mutationFn: () => generateOrderColoring(orderNumber!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
    },
  });

  // Generate all SVG mutation
  const generateAllSvgMutation = useMutation({
    mutationFn: () => generateOrderSvg(orderNumber!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
    },
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Načítání...</p>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="p-8">
        <p className="text-destructive">Objednávka nenalezena</p>
        <Link to="/" className="text-primary underline mt-4 inline-block">
          ← Zpět na seznam
        </Link>
      </div>
    );
  }

  const status = ORDER_STATUS_DISPLAY[order.status] || {
    label: order.status,
    color: "bg-gray-100",
  };

  const isProcessing = order.status === "downloading" || order.status === "processing";

  // Check if any images have completed coloring versions
  const hasAnyCompletedColoring = order.line_items.some((li) =>
    li.images.some((img) => img.coloring_versions.some((cv) => cv.status === "completed"))
  );

  // Check if coloring generation is in progress
  const isColoringGenerating = order.line_items.some((li) =>
    li.images.some((img) =>
      img.coloring_versions.some((cv) => cv.status === "queued" || cv.status === "processing")
    )
  );

  // Check if ALL downloaded images either have completed coloring OR are processing
  // If so, disable the "Vygenerovat jednotlivé omalovánky" button
  const downloadedImages = order.line_items.flatMap((li) =>
    li.images.filter((img) => img.local_path)
  );
  const allImagesHaveColoringOrProcessing =
    downloadedImages.length > 0 &&
    downloadedImages.every((img) => {
      const hasCompleted = img.coloring_versions.some((cv) => cv.status === "completed");
      const isProcessing = img.coloring_versions.some(
        (cv) => cv.status === "queued" || cv.status === "processing"
      );
      return hasCompleted || isProcessing;
    });

  return (
    <div className="p-8">
      <div className="flex items-center gap-4 mb-6">
        <Link to="/" className="text-muted-foreground hover:text-foreground">
          ← Objednávka
        </Link>
        <h1 className="text-2xl font-bold underline">{order.shopify_order_number}</h1>
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${status.color}`}>
          {status.label}
        </span>
      </div>

      {/* Sync status message */}
      {syncMutation.isSuccess && !dismissedSuccess && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-800 text-sm flex justify-between items-center">
          <span>Synchronizace spuštěna. Obrázky se stahují na pozadí.</span>
          <button
            onClick={() => setDismissedSuccess(true)}
            className="text-green-600 hover:text-green-800 ml-4"
            aria-label="Zavřít"
          >
            ✕
          </button>
        </div>
      )}

      {syncMutation.isError && !dismissedError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm flex justify-between items-center">
          <span>Chyba při synchronizaci</span>
          <button
            onClick={() => setDismissedError(true)}
            className="text-red-600 hover:text-red-800 ml-4"
            aria-label="Zavřít"
          >
            ✕
          </button>
        </div>
      )}

      {/* Coloring generation status */}
      {generateAllColoringMutation.isSuccess && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-800 text-sm">
          Generování omalovánek zahájeno.
        </div>
      )}

      {generateAllColoringMutation.isError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Chyba při generování omalovánek:{" "}
          {generateAllColoringMutation.error instanceof Error
            ? generateAllColoringMutation.error.message
            : "Neznámá chyba"}
        </div>
      )}

      {/* SVG generation status */}
      {generateAllSvgMutation.isSuccess && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-800 text-sm">
          Generování SVG zahájeno.
        </div>
      )}

      {generateAllSvgMutation.isError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Chyba při generování SVG:{" "}
          {generateAllSvgMutation.error instanceof Error
            ? generateAllSvgMutation.error.message
            : "Neznámá chyba"}
        </div>
      )}

      {isProcessing && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg text-blue-800 text-sm flex justify-between items-center">
          <div className="flex items-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
                fill="none"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span>Stahování a zpracování obrázků...</span>
          </div>
        </div>
      )}

      {isColoringGenerating && (
        <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-800 text-sm flex justify-between items-center">
          <div className="flex items-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
                fill="none"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span>Generování omalovánek...</span>
          </div>
        </div>
      )}

      <div className="flex gap-4 mb-8">
        <Button
          variant="outline"
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending || isProcessing}
        >
          {syncMutation.isPending ? "Spouštím..." : "Stáhnout ze Shopify"}
        </Button>
        <Button
          variant="outline"
          onClick={() => generateAllColoringMutation.mutate()}
          disabled={
            isProcessing ||
            generateAllColoringMutation.isPending ||
            allImagesHaveColoringOrProcessing
          }
        >
          {generateAllColoringMutation.isPending
            ? "Spouštím..."
            : "Vygenerovat jednotlivé omalovánky"}
        </Button>
        <Button
          variant="outline"
          onClick={() => generateAllSvgMutation.mutate()}
          disabled={!hasAnyCompletedColoring || isProcessing || generateAllSvgMutation.isPending}
        >
          {generateAllSvgMutation.isPending ? "Generuji..." : "Vygenerovat SVG"}
        </Button>
        <Button variant="outline" disabled={isProcessing}>
          Vygenerovat PDF
        </Button>
        <Button variant="outline" asChild>
          <a href={getShopifyOrderUrl(order.shopify_id)} target="_blank" rel="noopener noreferrer">
            Otevřít ve Shopify
          </a>
        </Button>
      </div>

      {/* Order info */}
      <table className="mb-12 text-sm">
        <tbody>
          <tr>
            <td className="text-muted-foreground pr-4 py-1.5 font-medium">Zákazník:</td>
            <td className="py-1.5">{order.customer_name || "—"}</td>
          </tr>
          <tr>
            <td className="text-muted-foreground pr-4 py-1.5 font-medium">E-mail:</td>
            <td className="py-1.5">{order.customer_email || "—"}</td>
          </tr>
          <tr>
            <td className="text-muted-foreground pr-4 py-1.5 font-medium">Stav platby:</td>
            <td className="py-1.5">
              {(() => {
                const paymentStatus = getPaymentStatusDisplay(order.payment_status);
                return paymentStatus.color ? (
                  <span
                    className={`px-2 py-0.5 rounded-full text-xs font-medium ${paymentStatus.color}`}
                  >
                    {paymentStatus.label}
                  </span>
                ) : (
                  <span>{paymentStatus.label}</span>
                );
              })()}
            </td>
          </tr>
          <tr>
            <td className="text-muted-foreground pr-4 py-1.5 font-medium">Metoda doručení:</td>
            <td className="py-1.5">{order.shipping_method || "—"}</td>
          </tr>
          <tr>
            <td className="text-muted-foreground pr-4 py-1.5 font-medium align-top">Položky:</td>
            <td className="py-1.5">
              {order.line_items.length > 1 ? (
                <span>
                  {order.line_items.map((item, index) => (
                    <span key={index}>
                      {index > 0 && ", "}
                      <a
                        href={`#variant-${index + 1}`}
                        className="text-primary underline hover:no-underline"
                      >
                        Položka {index + 1}
                        {item.dedication && ` (${item.dedication})`}
                      </a>
                    </span>
                  ))}
                </span>
              ) : (
                <span>{order.line_items.length} omalovánky</span>
              )}
            </td>
          </tr>
        </tbody>
      </table>

      {/* Line items */}
      {order.line_items.length === 0 ? (
        <div className="border rounded-lg p-8 text-center text-muted-foreground">
          <p className="mb-4">Žádné položky. Klikněte na "Stáhnout ze Shopify" pro načtení dat.</p>
        </div>
      ) : (
        <div className="space-y-8">
          {order.line_items.map((lineItem, index) => (
            <div
              key={lineItem.id}
              id={`variant-${index + 1}`}
              className="border rounded-lg p-6 scroll-mt-4"
            >
              <div className="flex items-center gap-4 mb-4">
                <h2 className="text-lg font-semibold">
                  {lineItem.title} {order.line_items.length > 1 && `(${index + 1})`}
                </h2>
              </div>

              <table className="mb-4 text-sm border-collapse">
                <tbody>
                  <tr>
                    <td className="text-muted-foreground pr-4 py-1">Věnování:</td>
                    <td className="py-1">{lineItem.dedication || "—"}</td>
                  </tr>
                  <tr>
                    <td className="text-muted-foreground pr-4 py-1">Rozvržení:</td>
                    <td className="py-1">{lineItem.layout || "—"}</td>
                  </tr>
                </tbody>
              </table>

              {/* Images grid */}
              <div className="grid grid-cols-2 gap-6">
                {lineItem.images.length === 0 ? (
                  <div className="col-span-2 text-center text-muted-foreground py-8">
                    Žádné obrázky
                  </div>
                ) : (
                  lineItem.images.map((image) => (
                    <ImageCard key={image.id} image={image} orderNumber={orderNumber || ""} />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
