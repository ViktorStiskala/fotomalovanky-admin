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

  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">
            {selectedColoring
              ? `Vygenerovat SVG (omalovánka v${selectedColoring.version})`
              : "Vygenerovat SVG"}
          </span>
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
            onClick={() => setShowSettings(!showSettings)}
            disabled={!hasCompletedColoring}
          >
            Nastavení
          </Button>
          <Button
            size="sm"
            onClick={() => onGenerate({ shape_stacking: shapeStacking, group_by: groupBy })}
            disabled={!hasCompletedColoring || isPending || isProcessing}
          >
            {isPending || isProcessing ? "Generuji..." : "Generovat"}
          </Button>
        </div>
      </div>

      {showSettings && hasCompletedColoring && (
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
