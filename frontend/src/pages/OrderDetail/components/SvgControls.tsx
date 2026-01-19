/**
 * SVG generation controls with settings form.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { ColoringVersion } from "@/lib/api";

interface SvgControlsProps {
  selectedColoring: ColoringVersion | undefined;
  hasCompletedColoring: boolean;
  isProcessing: boolean;
  isPending: boolean;
  onGenerate: (settings: { shape_stacking: string; group_by: string }) => void;
}

export function SvgControls({
  selectedColoring,
  hasCompletedColoring,
  isProcessing,
  isPending,
  onGenerate,
}: SvgControlsProps) {
  const [showSettings, setShowSettings] = useState(false);
  const [shapeStacking, setShapeStacking] = useState("stacked");
  const [groupBy, setGroupBy] = useState("color");

  // Only allow SVG generation if the selected coloring is completed
  const selectedColoringCompleted = selectedColoring?.status === "completed";
  const canGenerateSvg = hasCompletedColoring && selectedColoringCompleted;

  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">
            {selectedColoringCompleted
              ? `Vygenerovat SVG (omalovánka v${selectedColoring.version})`
              : "Vygenerovat SVG"}
          </span>
          {!canGenerateSvg && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
              {!hasCompletedColoring
                ? "Nejprve vygenerujte omalovánku"
                : "Čeká se na dokončení omalovánky"}
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowSettings(!showSettings)}
            disabled={!canGenerateSvg}
          >
            Nastavení
          </Button>
          <Button
            size="sm"
            onClick={() => onGenerate({ shape_stacking: shapeStacking, group_by: groupBy })}
            disabled={!canGenerateSvg || isPending || isProcessing}
          >
            {isPending || isProcessing ? "Generuji..." : "Generovat"}
          </Button>
        </div>
      </div>

      {showSettings && canGenerateSvg && (
        <div className="grid grid-cols-2 gap-4 pt-2 border-t">
          <div>
            <label className="text-xs text-muted-foreground">Vrstvení tvarů</label>
            <select
              value={shapeStacking}
              onChange={(e) => setShapeStacking(e.target.value)}
              className="w-full mt-1 px-2 py-1 border rounded text-sm"
            >
              <option value="stacked">Vrstvené</option>
              <option value="none">Žádné</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Seskupení</label>
            <select
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value)}
              className="w-full mt-1 px-2 py-1 border rounded text-sm"
            >
              <option value="color">Podle barvy</option>
              <option value="none">Žádné</option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
