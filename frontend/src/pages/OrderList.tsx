import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchOrders, fetchFromShopify } from "@/lib/api";
import { useOrderListEvents } from "@/hooks/useOrderListEvents";
import { ORDER_STATUS_DISPLAY } from "@/types";
import { Button } from "@/components/ui/button";

export default function OrderList() {
  const queryClient = useQueryClient();

  // Subscribe to real-time updates
  useOrderListEvents();

  const { data, isLoading, error } = useQuery({
    queryKey: ["orders"],
    queryFn: () => fetchOrders(),
  });

  const fetchMutation = useMutation({
    mutationFn: () => fetchFromShopify(20),
    onSuccess: (result) => {
      // Invalidate and refetch orders list
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      console.log(`Imported ${result.imported} orders, skipped ${result.skipped} (already exist)`);
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

      {fetchMutation.isSuccess && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-800 text-sm">
          Načteno {fetchMutation.data.imported} nových objednávek
          {fetchMutation.data.skipped > 0 && (
            <span className="text-green-600"> ({fetchMutation.data.skipped} již existovalo)</span>
          )}
        </div>
      )}

      {fetchMutation.isError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          Chyba při načítání z Shopify
        </div>
      )}

      <div className="border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted">
            <tr>
              <th className="text-left p-3 font-medium">Číslo</th>
              <th className="text-left p-3 font-medium">Datum</th>
              <th className="text-left p-3 font-medium">Zákazník</th>
              <th className="text-left p-3 font-medium">Položky</th>
              <th className="text-left p-3 font-medium">Stav</th>
            </tr>
          </thead>
          <tbody>
            {data?.orders.map((order) => {
              const status = ORDER_STATUS_DISPLAY[order.status] || {
                label: order.status,
                color: "bg-gray-100",
              };
              return (
                <tr key={order.id} className="border-t hover:bg-muted/50">
                  <td className="p-3">
                    <Link
                      to={`/orders/${order.id}`}
                      className="text-primary underline hover:no-underline"
                    >
                      {order.shopify_order_number}
                    </Link>
                  </td>
                  <td className="p-3 text-muted-foreground">{/* TODO: Add created_at field */}—</td>
                  <td className="p-3">{order.customer_email || "—"}</td>
                  <td className="p-3">{order.item_count} omalovánky</td>
                  <td className="p-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${status.color}`}>
                      {status.label}
                    </span>
                  </td>
                </tr>
              );
            })}
            {data?.orders.length === 0 && (
              <tr>
                <td colSpan={5} className="p-8 text-center text-muted-foreground">
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
