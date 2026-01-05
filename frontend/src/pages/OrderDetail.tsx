import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { fetchOrder, syncOrder, getImageUrl, getShopifyOrderUrl } from "@/lib/api";
import { useOrderEvents } from "@/hooks/useOrderEvents";
import { queryClient } from "@/lib/queryClient";
import { ORDER_STATUS_DISPLAY, getPaymentStatusDisplay } from "@/types";
import { Button } from "@/components/ui/button";

export default function OrderDetail() {
  const { orderNumber } = useParams<{ orderNumber: string }>();
  const [dismissedSuccess, setDismissedSuccess] = useState(false);
  const [dismissedError, setDismissedError] = useState(false);

  // Subscribe to real-time updates for this specific order
  // Using order number as the identifier
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
      // Reset dismissed states when starting a new mutation
      setDismissedSuccess(false);
      setDismissedError(false);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
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

      <div className="flex gap-4 mb-8">
        <Button
          variant="outline"
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending || isProcessing}
        >
          {syncMutation.isPending ? "Spouštím..." : "Stáhnout ze Shopify"}
        </Button>
        <Button variant="outline" disabled={isProcessing}>
          Vygenerovat jednotlivé omalovánky
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
                <Button variant="outline" size="sm">
                  Vygenerovat omalovánky
                </Button>
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
                    <div key={image.id} className="space-y-3">
                      {/* Image container with fixed height, image preserves aspect ratio */}
                      <div className="h-[32rem] bg-muted rounded overflow-hidden relative flex items-center justify-center">
                        {image.local_path ? (
                          <img
                            src={getImageUrl(image.id)}
                            alt={`Fotka ${image.position}`}
                            className="max-w-full max-h-full object-contain"
                            onError={(e) => {
                              // Fallback to placeholder if image fails to load
                              e.currentTarget.style.display = "none";
                              const placeholder = e.currentTarget.parentElement?.querySelector(
                                ".placeholder"
                              ) as HTMLElement;
                              if (placeholder) placeholder.style.display = "flex";
                            }}
                          />
                        ) : null}
                        <div
                          className="placeholder absolute inset-0 items-center justify-center text-muted-foreground text-sm"
                          style={{ display: image.local_path ? "none" : "flex" }}
                        >
                          {image.local_path
                            ? `Fotka ${image.position}`
                            : image.downloaded_at
                              ? "Staženo"
                              : "Čeká na stažení"}
                        </div>
                      </div>
                      {/* Coloring book placeholder with fixed height */}
                      <div className="h-[32rem] bg-muted rounded flex items-center justify-center text-muted-foreground text-sm">
                        Omalovánka {image.position}
                      </div>
                      <div className="flex gap-2 text-xs">
                        <Button variant="outline" size="sm">
                          Upravit
                        </Button>
                        <Button variant="outline" size="sm">
                          Schválit
                        </Button>
                      </div>
                    </div>
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
