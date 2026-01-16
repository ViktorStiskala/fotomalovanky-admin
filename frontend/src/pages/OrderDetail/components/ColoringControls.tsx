/**
 * Coloring generation controls with settings form.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";

interface ColoringControlsProps {
  disabled: boolean;
  isProcessing: boolean;
  isPending: boolean;
  onGenerate: (settings: { megapixels: number; steps: number }) => void;
}

export function ColoringControls({
  disabled,
  isProcessing,
  isPending,
  onGenerate,
}: ColoringControlsProps) {
  const [showSettings, setShowSettings] = useState(false);
  const [megapixels, setMegapixels] = useState(1.0);
  const [steps, setSteps] = useState(4);

  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Vygenerovat omalovánku</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowSettings(!showSettings)}>
            Nastavení
          </Button>
          <Button
            size="sm"
            onClick={() => onGenerate({ megapixels, steps })}
            disabled={disabled || isPending || isProcessing}
          >
            {isPending || isProcessing ? "Generuji..." : "Generovat"}
          </Button>
        </div>
      </div>

      {showSettings && (
        <div className="grid grid-cols-2 gap-4 pt-2 border-t">
          <div>
            <label className="text-xs text-muted-foreground">Megapixels</label>
            <input
              type="number"
              step="0.5"
              min="0.5"
              max="8"
              value={megapixels}
              onChange={(e) => setMegapixels(parseFloat(e.target.value))}
              className="w-full mt-1 px-2 py-1 border rounded text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Steps</label>
            <input
              type="number"
              min="1"
              max="20"
              value={steps}
              onChange={(e) => setSteps(parseInt(e.target.value))}
              className="w-full mt-1 px-2 py-1 border rounded text-sm"
            />
          </div>
        </div>
      )}
    </div>
  );
}
