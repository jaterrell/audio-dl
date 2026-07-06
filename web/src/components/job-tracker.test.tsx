import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor, renderHook } from "@testing-library/react";
import { renderWithToaster } from "@/test-utils/render";
import { resetToastStore } from "@/lib/toast-store";
import { resetTrackedJobs } from "@/lib/tracked-jobs";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { JobTracker } from "./job-tracker";
import { server } from "@/test-utils/server";
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
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  resetToastStore();
  resetTrackedJobs();
  localStorage.clear();
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;
});
afterEach(() => {
  delete (globalThis as unknown as { EventSource?: typeof MockEventSource }).EventSource;
});

function completed(): JobSnapshot {
  return {
    job_id: "job-1",
    state: "completed",
    started_at: 1,
    urls: [
      {
        url: "https://a",
        media_format: "m4a",
        state: "completed",
        progress_percent: 100,
        speed: null,
        eta: null,
        paths: ["/tmp/a.m4a"],
        error: null,
        thumb_id: null,
        title: "Awake",
        uploader: "Tycho",
      },
    ],
  };
}

function failed(): JobSnapshot {
  return {
    job_id: "job-2",
    state: "failed",
    started_at: 1,
    urls: [
      {
        url: "https://b",
        media_format: "m4a",
        state: "failed",
        progress_percent: 0,
        speed: null,
        eta: null,
        paths: [],
        error: "HTTP Error 403: Forbidden",
        thumb_id: null,
        title: "Kerala",
        uploader: "Bonobo",
      },
    ],
  };
}

describe("JobTracker toasts", () => {
  it("fires a success toast with the track title when a job completes", async () => {
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], completed());
    });
    expect(await screen.findByText(/added to library/i)).toBeInTheDocument();
    expect(screen.getByText("Awake")).toBeInTheDocument();
  });

  it("fires an error toast with the error message when a job fails", async () => {
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-2" />);
    act(() => {
      queryClient.setQueryData(["job", "job-2"], failed());
    });
    expect(await screen.findByText(/download failed/i)).toBeInTheDocument();
    expect(screen.getByText(/forbidden/i)).toBeInTheDocument();
  });

  it("fires the toast only once even if the snapshot object changes again", async () => {
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], completed());
    });
    await screen.findByText(/added to library/i);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], { ...completed() });
    });
    await waitFor(() => expect(screen.getAllByText(/added to library/i)).toHaveLength(1));
  });

  it("acknowledges a retry click with a re-downloading toast", async () => {
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "job-x", urls: [] })));
    const user = userEvent.setup();
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-2" />);
    act(() => {
      queryClient.setQueryData(["job", "job-2"], failed());
    });
    await user.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByText(/re-downloading/i)).toBeInTheDocument();
  });

  it("calls onJobCreated with the new job id when retry succeeds", async () => {
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "job-x", urls: [] })));
    const onJobCreated = vi.fn();
    const user = userEvent.setup();
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-2" onJobCreated={onJobCreated} />);
    act(() => {
      queryClient.setQueryData(["job", "job-2"], failed());
    });
    await user.click(await screen.findByRole("button", { name: /retry/i }));
    await waitFor(() => expect(onJobCreated).toHaveBeenCalledWith("job-x"));
  });
});

const RELATED = [{
  id: "n1", title: "Song", artist: "Artist", platform: "youtube" as const,
  webpage_url: "https://www.youtube.com/watch?v=n1", duration: 60, thumb_id: null,
}];

describe("JobTracker related persistence", () => {
  it("copies a completed URL's related items onto its history record", async () => {
    // This is also the tracker-side half of the back-to-back race fix
    // (Codex P2 on spec PR #52): when url_completed + url_related apply
    // synchronously BEFORE React flushes this effect, the snapshot the
    // effect reads is already patched — exactly what this test feeds it.
    // (The other half — a late url_related AFTER the history write —
    // is covered by the use-history updateItem and use-job-events
    // missing-record upsert tests.)
    const snap = completed();
    snap.urls[0].related_status = "ready";
    snap.urls[0].related = RELATED;
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], snap);
    });
    await screen.findByText(/added to library/i);
    const stored = JSON.parse(localStorage.getItem("audio_dl_history")!);
    expect(stored.items[0].url).toBe("https://a");
    expect(stored.items[0].related).toEqual(RELATED);
  });

  it("defers untrackJob to 10s when a completed URL is still pending, removeQueries still at 1.5s", async () => {
    vi.useFakeTimers();
    try {
      const snap = completed();
      snap.urls[0].related_status = "pending";
      const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
      act(() => {
        queryClient.setQueryData(["job", "job-1"], snap);
      });
      // Let the effect run.
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      const { useTrackedJobs, trackJob } = await import("@/lib/tracked-jobs");
      trackJob("job-1");
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      // Query record gone at 1.5s…
      expect(queryClient.getQueryData(["job", "job-1"])).toBeUndefined();
      // …but the job is still tracked (EventSource hook still mounted).
      const { result } = renderHook(() => useTrackedJobs());
      expect(result.current).toContain("job-1");
      await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
      expect(result.current).not.toContain("job-1");
    } finally {
      vi.useRealTimers();
    }
  });

  it("untracks at 1.5s when nothing is pending (unchanged behavior)", async () => {
    vi.useFakeTimers();
    try {
      const { trackJob, useTrackedJobs } = await import("@/lib/tracked-jobs");
      trackJob("job-1");
      const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
      act(() => {
        queryClient.setQueryData(["job", "job-1"], completed());
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      const { result } = renderHook(() => useTrackedJobs());
      expect(result.current).not.toContain("job-1");
    } finally {
      vi.useRealTimers();
    }
  });
});
