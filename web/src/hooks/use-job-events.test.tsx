import { describe, it, expect, beforeEach, afterEach } from "vitest";
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
});
