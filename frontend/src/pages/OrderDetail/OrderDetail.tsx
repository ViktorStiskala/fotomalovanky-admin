/**
 * Order detail page component.
 */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  fetchOrder,
  syncOrder,
  getShopifyOrderUrl,
  generateOrderColoring,
  generateOrderSvg,
} from "@/lib/api";
import { isColoringProcessing, hasCompletedColoring } from "@/lib/statusHelpers";
import { useOrderEvents } from "@/hooks/useOrderEvents";
import { queryClient } from "@/lib/queryClient";
import { ORDER_STATUS_DISPLAY, getPaymentStatusDisplay } from "@/types";
import { Button } from "@/components/ui/button";
import { ImageCard } from "./ImageCard";

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

  const generateAllColoringMutation = useMutation({
    mutationFn: () => generateOrderColoring(orderNumber!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
    },
  });

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

  // Aggregate image status checks across all line items
  const allImages = order.line_items.flatMap((li) => li.images);
  const downloadedImages = allImages.filter((img) => img.url);

  const hasAnyCompletedColoring = allImages.some((img) =>
    hasCompletedColoring(img.versions.coloring)
  );

  const isColoringGenerating = allImages.some((img) => isColoringProcessing(img.versions.coloring));

  const allImagesHaveColoringOrProcessing =
    downloadedImages.length > 0 &&
    downloadedImages.every((img) => {
      const hasCompleted = hasCompletedColoring(img.versions.coloring);
      const processing = isColoringProcessing(img.versions.coloring);
      return hasCompleted || processing;
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

      {/* Status Messages */}
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

      {/* Action Buttons */}
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

      {/* Order Info */}
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

      {/* Line Items */}
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
