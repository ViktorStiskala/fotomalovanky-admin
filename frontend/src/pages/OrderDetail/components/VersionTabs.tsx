/**
 * Tab switcher for coloring and SVG versions with version lists.
 */

import { useState } from "react";
import { Icon } from "@/components/icons";
import type { ColoringVersion, SvgVersion, SelectedVersionIds } from "@/lib/api";
import {
  getColoringStatusDisplay,
  getSvgStatusDisplay,
  getShapeStackingLabel,
  getGroupByLabel,
} from "@/types";

interface VersionTabsProps {
  coloringVersions: ColoringVersion[];
  svgVersions: SvgVersion[];
  selectedVersionIds: SelectedVersionIds;
  onSelectColoring: (versionId: number) => void;
  onSelectSvg: (versionId: number) => void;
  onRetryColoring: (versionId: number) => void;
  onRetrySvg: (versionId: number) => void;
  onFullscreen: (image: { src: string; alt: string }) => void;
  isRetryingColoring: boolean;
  isRetryingSvg: boolean;
  defaultTab?: "coloring" | "svg";
}

export function VersionTabs({
  coloringVersions,
  svgVersions,
  selectedVersionIds,
  onSelectColoring,
  onSelectSvg,
  onRetryColoring,
  onRetrySvg,
  onFullscreen,
  isRetryingColoring,
  isRetryingSvg,
  defaultTab,
}: VersionTabsProps) {
  const [activeTab, setActiveTab] = useState<"coloring" | "svg">(
    defaultTab || (svgVersions.length > 0 ? "svg" : "coloring")
  );

  const selectedColoring = coloringVersions.find((cv) => cv.id === selectedVersionIds.coloring);
  const selectedSvg = svgVersions.find((sv) => sv.id === selectedVersionIds.svg);

  if (coloringVersions.length === 0 && svgVersions.length === 0) {
    return null;
  }

  return (
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
          Omalovánka ({coloringVersions.length})
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
          {/* Preview area */}
          <div className="h-[32rem] bg-muted rounded overflow-hidden relative flex items-center justify-center group">
            {selectedColoring?.url ? (
              <>
                <img
                  src={selectedColoring.url}
                  alt={`Omalovánka v${selectedColoring.version}`}
                  className="max-w-full max-h-full object-contain"
                />
                <button
                  className="absolute top-2 right-2 p-1.5 bg-black/50 hover:bg-black/70 rounded text-white opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() =>
                    onFullscreen({
                      src: selectedColoring.url!,
                      alt: `Omalovánka v${selectedColoring.version}`,
                    })
                  }
                >
                  <Icon name="mdi-fullscreen" className="w-5 h-5" />
                </button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                {coloringVersions.length === 0 ? "Žádné verze" : "Generování..."}
              </p>
            )}
          </div>

          {/* Version list */}
          <div className="flex flex-wrap gap-2 items-stretch min-h-[5rem]">
            {coloringVersions.map((cv) => {
              const status = getColoringStatusDisplay(cv.status);
              const isSelected = cv.id === selectedVersionIds.coloring;
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
                      onSelectColoring(cv.id);
                    }
                  }}
                  disabled={cv.status !== "completed" && !isError}
                >
                  <div className="font-medium">v{cv.version}</div>
                  <div className="text-xs text-muted-foreground">
                    {cv.options.megapixels}MP / {cv.options.steps}st
                  </div>
                  <div className="flex-1 flex items-center justify-center">
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded inline-flex items-center gap-1 transition-all duration-300 ${status.color}`}
                    >
                      {status.label}
                      {isError && (
                        <Icon
                          name="mdi-refresh"
                          className={`w-3.5 h-3.5 cursor-pointer hover:scale-125 transition-transform ${isRetryingColoring ? "animate-spin" : ""}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onRetryColoring(cv.id);
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
          {/* Preview area */}
          <div className="h-[32rem] bg-muted rounded overflow-hidden relative flex items-center justify-center group">
            {selectedSvg?.url ? (
              <>
                <img
                  src={selectedSvg.url}
                  alt="SVG"
                  className="max-w-full max-h-full object-contain"
                />
                <button
                  className="absolute top-2 right-2 p-1.5 bg-black/50 hover:bg-black/70 rounded text-white opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() =>
                    onFullscreen({
                      src: selectedSvg.url!,
                      alt: "SVG",
                    })
                  }
                >
                  <Icon name="mdi-fullscreen" className="w-5 h-5" />
                </button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                {svgVersions.length === 0 ? "Žádné SVG verze" : "Generování..."}
              </p>
            )}
          </div>

          {/* SVG Version list */}
          <div className="flex flex-wrap gap-2 items-stretch min-h-[5rem]">
            {svgVersions.map((sv) => {
              const status = getSvgStatusDisplay(sv.status);
              const isSelected = sv.id === selectedVersionIds.svg;
              const isError = sv.status === "error";
              // Find the source coloring version number
              const sourceColoring = coloringVersions.find(
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
                      onSelectSvg(sv.id);
                    }
                  }}
                  disabled={sv.status !== "completed" && !isError}
                >
                  <div className="font-medium">
                    v{sv.version} (v{sourceVersion})
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {getShapeStackingLabel(sv.options.shape_stacking)} /{" "}
                    {getGroupByLabel(sv.options.group_by)}
                  </div>
                  <div className="flex-1 flex items-center justify-center">
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded inline-flex items-center gap-1 transition-all duration-300 ${status.color}`}
                    >
                      {status.label}
                      {isError && (
                        <Icon
                          name="mdi-refresh"
                          className={`w-3.5 h-3.5 cursor-pointer hover:scale-125 transition-transform ${isRetryingSvg ? "animate-spin" : ""}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onRetrySvg(sv.id);
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
  );
}
