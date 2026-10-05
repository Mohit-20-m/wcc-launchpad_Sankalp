import { useEffect, useRef, useState } from "react";
import { useAuthStore } from "../store/auth";

/**
 * Live refresh signals over a WebSocket. The server only ever says
 * "these topics changed"; we respond by refetching through the normal
 * REST API, which enforces every permission. So nothing sensitive can
 * arrive over the socket. Reconnects with backoff; if the socket can't
 * connect, callers' slower polling keeps the page fresh anyway.
 */
export function useLive(eventId: string | null | undefined, onRefresh: (topics: string[]) => void): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onRefresh);
  handler.current = onRefresh;
  const token = useAuthStore((s) => s.token);

  useEffect(() => {
    if (!eventId || typeof WebSocket === "undefined") return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 1000;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const q = token ? `?token=${encodeURIComponent(token)}` : "";
      ws = new WebSocket(`${proto}://${window.location.host}/ws/live/${eventId}${q}`);
      ws.onopen = () => {
        retry = 1000;
        setConnected(true);
      };
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg?.type === "refresh" && Array.isArray(msg.topics)) handler.current(msg.topics as string[]);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          timer = setTimeout(connect, retry);
          retry = Math.min(retry * 2, 15000);
        }
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [eventId, token]);

  return connected;
}
