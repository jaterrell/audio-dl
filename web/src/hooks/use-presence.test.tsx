import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { usePresence } from "./use-presence";
import { resetCsrfCache } from "@/lib/csrf";

class MockEventSource {
  static instances: MockEventSource[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  url: string;
  readyState = MockEventSource.CONNECTING;
  closed = false;
  onerror: ((e: Event) => void) | null = null;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = MockEventSource.CLOSED;
  }
}

let meta: HTMLMetaElement;

beforeEach(() => {
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource =
    MockEventSource;
  resetCsrfCache();
  meta = document.createElement("meta");
  meta.name = "csrf-token";
  meta.content = "test-token";
  document.head.appendChild(meta);
});

afterEach(() => {
  delete (globalThis as unknown as { EventSource?: typeof MockEventSource })
    .EventSource;
  meta.remove();
  resetCsrfCache();
});

describe("usePresence", () => {
  it("opens a presence stream carrying the CSRF token", async () => {
    renderHook(() => usePresence());
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    expect(MockEventSource.instances[0].url).toBe("/presence?token=test-token");
  });

  it("closes the stream on unmount so a closed window disconnects promptly", async () => {
    const { unmount } = renderHook(() => usePresence());
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    unmount();
    expect(MockEventSource.instances[0].closed).toBe(true);
  });

  it("recovers from a stale token: fatal stream error → refresh from GET / → reopen", async () => {
    // A tab that survived an app relaunch: its DOM meta token ("test-token")
    // is stale, the presence stream dies with a fatal 403 (readyState
    // CLOSED), and the hook must re-pull the live token from GET / and
    // reconnect — otherwise the watchdog can't see this open window.
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        '<html><head><meta name="csrf-token" content="fresh-token"></head><body></body></html>',
        { status: 200, headers: { "Content-Type": "text/html" } },
      ),
    );
    try {
      renderHook(() => usePresence());
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      expect(MockEventSource.instances[0].url).toBe("/presence?token=test-token");

      vi.useFakeTimers();
      const first = MockEventSource.instances[0];
      first.readyState = MockEventSource.CLOSED;
      first.onerror?.(new Event("error"));
      expect(first.closed).toBe(true);
      await vi.advanceTimersByTimeAsync(3100);
      vi.useRealTimers();

      await waitFor(() => expect(MockEventSource.instances).toHaveLength(2));
      expect(MockEventSource.instances[1].url).toBe("/presence?token=fresh-token");
    } finally {
      vi.useRealTimers();
      fetchSpy.mockRestore();
    }
  });

  it("ignores transient errors — EventSource retries those itself", async () => {
    renderHook(() => usePresence());
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const first = MockEventSource.instances[0];
    first.readyState = MockEventSource.CONNECTING;
    first.onerror?.(new Event("error"));
    expect(first.closed).toBe(false);
    expect(MockEventSource.instances).toHaveLength(1);
  });
});
