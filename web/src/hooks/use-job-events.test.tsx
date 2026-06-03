import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { useJobEvents } from "./use-job-events";
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
});
