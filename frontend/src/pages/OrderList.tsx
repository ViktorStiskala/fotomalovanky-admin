import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchOrders, fetchFromShopify, extractOrderNumber, getShopifyOrderUrl } from "@/lib/api";
import { useOrderListEvents } from "@/hooks/useOrderListEvents";
import { ORDER_STATUS_DISPLAY, getPaymentStatusDisplay } from "@/types";
import { Button } from "@/components/ui/button";

export default function OrderList() {
  const queryClient = useQueryClient();
  const [dismissedSuccess, setDismissedSuccess] = useState(false);
  const [dismissedError, setDismissedError] = useState(false);

  // Subscribe to real-time updates
  useOrderListEvents();

  const { data, isLoading, error } = useQuery({
    queryKey: ["orders"],
    queryFn: () => fetchOrders(),
  });

  const fetchMutation = useMutation({
    mutationFn: () => fetchFromShopify(20),
    onMutate: () => {
      // Reset dismissed states when starting a new mutation
      setDismissedSuccess(false);
      setDismissedError(false);
    },
    onSuccess: () => {
      // Invalidate and refetch orders list
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      console.log("Shopify fetch task queued");
    },
  });

  if (isLoading) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-bold mb-6">Objednávky</h1>
        <p className="text-muted-foreground">Načítání...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-bold mb-6">Objednávky</h1>
        <p className="text-destructive">Chyba při načítání objednávek</p>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Objednávky</h1>
        <Button
          variant="outline"
          onClick={() => fetchMutation.mutate()}
          disabled={fetchMutation.isPending}
        >
          {fetchMutation.isPending ? "Načítání..." : "Načíst z Shopify"}
        </Button>
      </div>

      {fetchMutation.isSuccess && !dismissedSuccess && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-800 text-sm flex justify-between items-center">
          <span>Stahování objednávek ze Shopify...</span>
          <button
            onClick={() => setDismissedSuccess(true)}
            className="text-green-600 hover:text-green-800 ml-4"
            aria-label="Zavřít"
          >
            ✕
          </button>
        </div>
      )}

      {fetchMutation.isError && !dismissedError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm flex justify-between items-center">
          <span>Chyba při načítání z Shopify</span>
          <button
            onClick={() => setDismissedError(true)}
            className="text-red-600 hover:text-red-800 ml-4"
            aria-label="Zavřít"
          >
            ✕
          </button>
        </div>
      )}

      <div className="border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted">
            <tr>
              <th className="text-left p-3 font-medium">Číslo</th>
              <th className="text-left p-3 font-medium">Datum</th>
              <th className="text-left p-3 font-medium">Zákazník</th>
              <th className="text-left p-3 font-medium">E-mail</th>
              <th className="text-left p-3 font-medium">Položky</th>
              <th className="text-left p-3 font-medium">Stav platby</th>
              <th className="text-left p-3 font-medium">Stav</th>
              <th className="text-left p-3 font-medium">Shopify</th>
            </tr>
          </thead>
          <tbody>
            {data?.orders.map((order) => {
              const status = ORDER_STATUS_DISPLAY[order.status] || {
                label: order.status,
                color: "bg-gray-100",
              };
              const paymentStatus = getPaymentStatusDisplay(order.payment_status);
              const date = new Date(order.created_at);
              const formattedDate = date.toLocaleDateString("cs-CZ", {
                day: "numeric",
                month: "numeric",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              });
              return (
                <tr key={order.id} className="border-t hover:bg-muted/50">
                  <td className="p-3">
                    <Link
                      to={`/orders/${extractOrderNumber(order.shopify_order_number)}`}
                      className="text-primary underline hover:no-underline"
                    >
                      {order.shopify_order_number}
                    </Link>
                  </td>
                  <td className="p-3 text-muted-foreground">{formattedDate}</td>
                  <td className="p-3">{order.customer_name || "—"}</td>
                  <td className="p-3">{order.customer_email || "—"}</td>
                  <td className="p-3">{order.item_count} omalovánky</td>
                  <td className="p-3">
                    {paymentStatus.color ? (
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${paymentStatus.color}`}
                      >
                        {paymentStatus.label}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">{paymentStatus.label}</span>
                    )}
                  </td>
                  <td className="p-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${status.color}`}>
                      {status.label}
                    </span>
                  </td>
                  <td className="p-3">
                    <Button variant="outline" size="sm" asChild>
                      <a
                        href={getShopifyOrderUrl(order.shopify_id)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Otevřít ve Shopify
                      </a>
                    </Button>
                  </td>
                </tr>
              );
            })}
            {data?.orders.length === 0 && (
              <tr>
                <td colSpan={8} className="p-8 text-center text-muted-foreground">
                  Žádné objednávky
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
