import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { useJobEvents } from "./use-job-events";
import { resetToastStore, getToasts } from "@/lib/toast-store";
import type { JobSnapshot } from "@/lib/types";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
  close() { this.closed = true; }
  emit(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  resetToastStore();
  (globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;
});

afterEach(() => {
  delete (globalThis as unknown as { EventSource?: typeof MockEventSource }).EventSource;
});

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

/** Backend wire shape for a job_snapshot event. */
function makeSnapshotEvent(overrides?: object) {
  return {
    type: "job_snapshot",
    job_id: "job-1",
    complete: false,
    default_format: "mp3",
    urls: [
      {
        url: "https://a",
        media_format: "mp3",
        status: "running",
        percent: 42,
        speed: "1.0 MB/s",
        eta: "10s",
        paths: [],
        error: null,
        thumb_id: null,
        title: null,
        uploader: null,
      },
    ],
    ...overrides,
  };
}

describe("useJobEvents", () => {
  it("opens EventSource with job_id in URL", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    expect(es.url).toContain("/jobs/job-1/events");
  });

  it("normalizes job_snapshot event into frontend JobSnapshot shape", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(makeSnapshotEvent());

    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"]);
      expect(snap).toBeDefined();
    });

    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    // Job-level state derived from URL statuses
    expect(snap.job_id).toBe("job-1");
    expect(snap.state).toBe("running");
    expect(typeof snap.started_at).toBe("number");
    // URL fields remapped: status → state, percent → progress_percent
    expect(snap.urls).toHaveLength(1);
    expect(snap.urls[0].state).toBe("running");
    expect(snap.urls[0].progress_percent).toBe(42);
    expect(snap.urls[0].speed).toBe("1.0 MB/s");
    expect(snap.urls[0].eta).toBe("10s");
    expect(snap.urls[0].url).toBe("https://a");
    expect(snap.urls[0].media_format).toBe("mp3");
  });

  it("preserves started_at across subsequent job_snapshot events", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );
    const firstStartedAt = client.getQueryData<JobSnapshot>(["job", "job-1"])!.started_at;

    // Second snapshot: same job, should preserve started_at
    es.emit(makeSnapshotEvent({ complete: false }));
    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.started_at).toBe(firstStartedAt);
    });
  });

  it("applies progress event to update progress_percent, speed, eta", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    // First establish a snapshot
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );

    // Then send a progress event
    es.emit({
      type: "progress",
      job_id: "job-1",
      url: "https://a",
      percent: 75,
      speed: "2.5 MB/s",
      eta: "5s",
    });

    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].progress_percent).toBe(75);
    });

    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].speed).toBe("2.5 MB/s");
    expect(snap.urls[0].eta).toBe("5s");
    // Job state still running
    expect(snap.state).toBe("running");
  });

  it("applies url_completed event: state='completed', paths and thumb_id set", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );

    es.emit({
      type: "url_completed",
      job_id: "job-1",
      url: "https://a",
      paths: ["/home/user/Music/track.mp3"],
      thumb_id: "thumb-abc",
    });

    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].state).toBe("completed");
    });

    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].paths).toEqual(["/home/user/Music/track.mp3"]);
    expect(snap.urls[0].thumb_id).toBe("thumb-abc");
    // Job state derived: all URLs completed → job completed
    expect(snap.state).toBe("completed");
  });

  it("applies url_failed event: state='failed', error set", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );

    es.emit({
      type: "url_failed",
      job_id: "job-1",
      url: "https://a",
      error: "HTTP Error 429: Too Many Requests",
    });

    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].state).toBe("failed");
    });

    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].error).toBe("HTTP Error 429: Too Many Requests");
    expect(snap.state).toBe("failed");
  });

  it("ignores unknown event types without throwing", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    // Establish snapshot first
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );

    // Unknown event type — should not throw or corrupt state
    es.emit({ type: "some_future_event", job_id: "job-1", data: "irrelevant" });

    // State unchanged
    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].state).toBe("running");
  });

  it("closes the EventSource on unmount", async () => {
    const client = new QueryClient();
    const { unmount } = renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    unmount();
    expect(es.closed).toBe(true);
  });

  it("closes the EventSource when a job_snapshot reports terminal state", async () => {
    // Regression test for the v2.0.0 SSE reconnect loop: the backend closes
    // the stream after a terminal snapshot, EventSource auto-reconnects, and
    // the hook used to re-process the same terminal snapshot forever.
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(
      makeSnapshotEvent({
        complete: true,
        urls: [
          {
            url: "https://a",
            media_format: "mp3",
            status: "completed",
            percent: 100,
            speed: null,
            eta: null,
            paths: ["/tmp/a.mp3"],
            error: null,
            thumb_id: null,
            title: null,
            uploader: null,
          },
        ],
      })
    );

    await waitFor(() => expect(es.closed).toBe(true));
  });

  it("merges url_metadata title and uploader into the existing snapshot", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );

    es.emit({
      type: "url_metadata",
      job_id: "job-1",
      url: "https://a",
      title: "Me at the zoo",
      uploader: "jawed",
      duration: 19,
      thumbnail_ready: false,
    });

    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].title).toBe("Me at the zoo");
    });
    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].uploader).toBe("jawed");
    // Other URL fields unchanged
    expect(snap.urls[0].progress_percent).toBe(42);
    expect(snap.urls[0].state).toBe("running");
  });

  it("normalizes title and uploader from a job_snapshot event", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(
      makeSnapshotEvent({
        urls: [
          {
            url: "https://a",
            media_format: "mp3",
            status: "running",
            percent: 42,
            speed: null,
            eta: null,
            paths: [],
            error: null,
            thumb_id: null,
            title: "Track Title",
            uploader: "Artist Name",
          },
        ],
      })
    );

    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])?.urls[0].title).toBe(
        "Track Title"
      )
    );
    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].uploader).toBe("Artist Name");
  });

  it("surfaces a 'lost connection' toast when the stream drops mid-download, and clears it on reconnect", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    // establish a running (non-terminal) snapshot
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );

    // stream drops while still running → user-visible toast, stream NOT closed
    es.onerror?.(new Event("error"));
    await waitFor(() =>
      expect(getToasts().some((t) => /lost connection/i.test(t.title))).toBe(true)
    );
    expect(es.closed).toBe(false);

    // reconnect: the next message clears the toast
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(getToasts().some((t) => /lost connection/i.test(t.title))).toBe(false)
    );
  });

  it("does not toast on the terminal-state error (clean stream close)", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];

    es.emit(
      makeSnapshotEvent({
        complete: true,
        urls: [
          {
            url: "https://a",
            media_format: "mp3",
            status: "completed",
            percent: 100,
            speed: null,
            eta: null,
            paths: ["/tmp/a.mp3"],
            error: null,
            thumb_id: null,
            title: null,
            uploader: null,
          },
        ],
      })
    );
    await waitFor(() => expect(es.closed).toBe(true));
    es.onerror?.(new Event("error"));
    expect(getToasts().some((t) => /lost connection/i.test(t.title))).toBe(false);
  });

  const RELATED_ITEM = {
    id: "n1", title: "Girls Just Want To Have Fun", artist: "Cyndi Lauper",
    platform: "youtube", webpage_url: "https://www.youtube.com/watch?v=PIb6AZdTr-A",
    duration: 267, thumb_id: "a".repeat(40),
  };

  it("url_related patches the matching URL's related fields", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].related_status).toBe("ready");
    });
    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].related).toEqual([RELATED_ITEM]);
  });

  it("url_metadata patches related_status", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );
    es.emit({ type: "url_metadata", job_id: "job-1", url: "https://a",
              title: "T", uploader: "U", duration: 1,
              thumbnail_ready: false, related_status: "pending" });
    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].related_status).toBe("pending");
    });
  });

  it("snapshot round-trips related fields", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    const urls = makeSnapshotEvent().urls.map((u: object) => ({
      ...u, related_status: "ready", related_items: [RELATED_ITEM],
    }));
    es.emit(makeSnapshotEvent({ urls }));
    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].related).toEqual([RELATED_ITEM]);
      expect(snap.urls[0].related_status).toBe("ready");
    });
  });

  it("late url_related with NO cached record upserts into history", async () => {
    localStorage.setItem("audio_dl_history", JSON.stringify({
      v: 1,
      items: [{ url: "https://a", title: "T", artist: "U", media_format: "m4a",
                paths: [], thumb_id: null, added_at: 1 }],
    }));
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    // NO snapshot emitted: the query record does not exist (post-teardown).
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    const stored = JSON.parse(localStorage.getItem("audio_dl_history")!);
    expect(stored.items[0].related).toEqual([RELATED_ITEM]);
  });

  it("url_related on a terminal record patches cache AND upserts history", async () => {
    // The Codex-P2 ordering race: url_completed then url_related arrive
    // back-to-back before JobTracker's effect writes the history row. The
    // cache patch must land so the pending history write carries the items.
    localStorage.setItem("audio_dl_history", JSON.stringify({ v: 1, items: [] }));
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );
    es.emit({ type: "url_completed", job_id: "job-1", url: "https://a",
              paths: ["/tmp/a.mp3"], thumb_id: null });
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.state).toBe("completed");
    expect(snap.urls[0].related).toEqual([RELATED_ITEM]); // cache patched
    // History had no matching row yet → module updateItem no-oped, harmless.
  });

  function terminalSnapshotWithPending(related_status: string | null) {
    return makeSnapshotEvent({
      complete: true,
      urls: [{
        url: "https://a", media_format: "mp3", status: "completed",
        percent: 100, speed: null, eta: null, paths: ["/tmp/a.mp3"],
        error: null, thumb_id: null, title: null, uploader: null,
        related_status, related_items: [],
      }],
    });
  }

  it("terminal with nothing pending closes immediately (unchanged behavior)", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(terminalSnapshotWithPending(null));
    await waitFor(() => expect(es.closed).toBe(true));
  });

  it("terminal with a pending completed URL keeps the socket open, then a late url_related closes it silently", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(terminalSnapshotWithPending("pending"));
    // Deliberately NOT closed: the linger window is open.
    expect(es.closed).toBe(false);
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    await waitFor(() => expect(es.closed).toBe(true));
    expect(getToasts().some((t) => /lost connection/i.test(t.title))).toBe(false);
  });

  it("hook's own 10s cap closes the lingering socket", async () => {
    vi.useFakeTimers();
    try {
      const client = new QueryClient();
      renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
      await vi.waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
      const es = MockEventSource.instances[0];
      es.emit(terminalSnapshotWithPending("pending"));
      expect(es.closed).toBe(false);
      await vi.advanceTimersByTimeAsync(10_000);
      expect(es.closed).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("server close after terminal is silent — no Lost-connection toast even with the query record deleted", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(terminalSnapshotWithPending("pending"));
    // Simulate JobTracker's 1.5s removeQueries firing before the server closes.
    client.removeQueries({ queryKey: ["job", "job-1"] });
    es.onerror?.(new Event("error"));
    expect(es.closed).toBe(true);
    expect(getToasts().some((t) => /lost connection/i.test(t.title))).toBe(false);
  });

  it("failed URLs are dropped from the pending set at terminal", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent({
      complete: true,
      urls: [{
        url: "https://a", media_format: "mp3", status: "failed",
        percent: 0, speed: null, eta: null, paths: [],
        error: "boom", thumb_id: null, title: null, uploader: null,
        related_status: "pending", related_items: [],
      }],
    }));
    // Failed URL's pending discovery is suppressed server-side — no wait.
    await waitFor(() => expect(es.closed).toBe(true));
  });
});
