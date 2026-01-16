import { useEffect, useRef } from "react";
import { MERCURE_URL } from "@/lib/config";

// Track all active EventSource instances to close them on page unload
const activeConnections = new Set<EventSource>();
let isPageUnloading = false;

// Set up unload detection once - close all connections before browser interrupts them
if (typeof window !== "undefined") {
  window.addEventListener(
    "beforeunload",
    () => {
      isPageUnloading = true;
      // Close all connections immediately to prevent "interrupted" messages
      activeConnections.forEach((es) => es.close());
      activeConnections.clear();
    },
    { capture: true }
  );
  // Reset on pageshow (e.g., back/forward cache)
  window.addEventListener("pageshow", () => {
    isPageUnloading = false;
  });
}

/**
 * Low-level hook for subscribing to Mercure SSE topics.
 *
 * Handles EventSource lifecycle including:
 * - Connection management
 * - Clean disconnection without spurious errors (Firefox CORS noise)
 * - Automatic reconnection (built into EventSource)
 * - Waits for document ready to avoid "connection interrupted" during page load
 * - Proactively closes connections on page unload to prevent browser warnings
 *
 * @param topic - The Mercure topic to subscribe to (e.g., "orders", "orders/1270")
 * @param onMessage - Callback when a message is received
 * @param enabled - Whether the subscription is active (default: true)
 */
export function useMercure(
  topic: string,
  onMessage: (data: unknown) => void,
  enabled = true
): void {
  const onMessageRef = useRef(onMessage);

  // Keep callback ref updated without triggering reconnection
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!enabled || !topic) {
      return;
    }

    // Local flag to track cleanup state (scoped to this effect instance)
    let isClosing = false;
    let eventSource: EventSource | null = null;

    const connect = () => {
      if (isClosing || isPageUnloading) return;

      // Build Mercure subscription URL
      const url = new URL(MERCURE_URL);
      url.searchParams.append("topic", topic);

      // Create EventSource connection
      eventSource = new EventSource(url.toString());
      activeConnections.add(eventSource);

      eventSource.onmessage = (event: MessageEvent) => {
        if (isClosing || isPageUnloading) return;
        try {
          const data: unknown = JSON.parse(event.data);
          onMessageRef.current(data);
        } catch (error) {
          console.error("[Mercure] Failed to parse event:", error);
        }
      };

      eventSource.onerror = () => {
        // Ignore errors when intentionally closing or page unloading
        if (isClosing || isPageUnloading) return;
        // EventSource will automatically try to reconnect
      };

      eventSource.onopen = () => {
        if (isClosing || isPageUnloading) return;
        console.log(`[Mercure] Connected to ${topic}`);
      };
    };

    const cleanup = () => {
      isClosing = true;
      if (eventSource) {
        activeConnections.delete(eventSource);
        eventSource.close();
      }
    };

    // Wait for document to be ready to avoid "connection interrupted during page load"
    if (document.readyState === "complete") {
      // Document already loaded, connect on next tick (for React Strict Mode)
      const frameId = requestAnimationFrame(connect);
      return () => {
        cancelAnimationFrame(frameId);
        cleanup();
      };
    } else {
      // Wait for document to finish loading
      const handleLoad = () => connect();
      window.addEventListener("load", handleLoad);
      return () => {
        window.removeEventListener("load", handleLoad);
        cleanup();
      };
    }
  }, [topic, enabled]);
}
