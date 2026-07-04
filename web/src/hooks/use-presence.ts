import { useEffect } from "react";
import { discoverCsrfToken, refreshCsrfTokenFromRoot } from "@/lib/csrf";

const RECONNECT_DELAY_MS = 3000;

/**
 * Holds one persistent SSE connection to GET /presence for the lifetime of
 * the app shell. The connection itself is the signal: the backend counts
 * open presence streams and shuts itself down once every browser window has
 * been closed for a grace period (and downloads have finished). Without
 * this, closing the browser left the server running in the background
 * forever.
 *
 * Transient drops leave EventSource in CONNECTING and it retries by itself,
 * which the backend's grace period absorbs. A CLOSED stream is fatal — most
 * likely a 403 from a stale CSRF token in a tab that survived an app
 * relaunch (its DOM still carries the old <meta>). Recover the way the API
 * layer does: pull the current token from a fresh GET / and reopen, so a
 * surviving tab keeps counting toward presence instead of letting the
 * watchdog shut the server down under a live window. In dev (Vite on :5173)
 * the request proxies to the backend, where auto-shutdown is disabled anyway.
 */
export function usePresence() {
  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const open = (token: string) => {
      if (cancelled) return;
      const url = token
        ? `/presence?token=${encodeURIComponent(token)}`
        : "/presence";
      es = new EventSource(url);
      es.onerror = () => {
        if (es?.readyState !== EventSource.CLOSED) return;
        es.close();
        es = null;
        timer = setTimeout(async () => {
          const fresh =
            (await refreshCsrfTokenFromRoot()) ?? (await discoverCsrfToken());
          open(fresh);
        }, RECONNECT_DELAY_MS);
      };
    };

    (async () => {
      const token = await discoverCsrfToken();
      if (!cancelled) open(token);
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, []);
}
