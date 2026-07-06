import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { JobSnapshot, UrlState, UrlStateName, Format, RelatedItem } from "@/lib/types";
import { updateItem as updateHistoryItem } from "@/hooks/use-history";
import { discoverCsrfToken } from "@/lib/csrf";
import { toast } from "@/lib/toast-store";

type BackendUrlStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

interface BackendUrl {
  url: string;
  media_format: Format;
  status: BackendUrlStatus;
  percent: number;
  speed: string | null;
  eta: string | null;
  paths: string[];
  error: string | null;
  thumb_id: string | null;
  title: string | null;
  uploader: string | null;
  related_status?: string | null;
  related_items?: RelatedItem[];
}

interface UrlMetadataEvent {
  type: "url_metadata";
  job_id: string;
  url: string;
  title?: string | null;
  uploader?: string | null;
  duration?: number | null;
  thumbnail_ready?: boolean;
  related_status?: string | null;
}

interface JobSnapshotEvent {
  type: "job_snapshot";
  job_id: string;
  complete: boolean;
  default_format: Format;
  urls: BackendUrl[];
}

interface ProgressEvent {
  type: "progress";
  job_id: string;
  url: string;
  percent?: number;
  speed?: string | null;
  eta?: string | null;
}

interface UrlStartedEvent {
  type: "url_started";
  job_id: string;
  url: string;
}

interface UrlCompletedEvent {
  type: "url_completed";
  job_id: string;
  url: string;
  paths?: string[];
  thumb_id?: string | null;
}

interface UrlFailedEvent {
  type: "url_failed";
  job_id: string;
  url: string;
  error?: string;
}

interface UrlRelatedEvent {
  type: "url_related";
  job_id: string;
  url: string;
  status: "ready" | "none" | "error";
  items: RelatedItem[];
}

interface JobCompletedEvent {
  type: "job_completed";
  job_id: string;
}

type AnyEvent =
  | JobSnapshotEvent
  | ProgressEvent
  | UrlStartedEvent
  | UrlCompletedEvent
  | UrlFailedEvent
  | UrlMetadataEvent
  | UrlRelatedEvent
  | JobCompletedEvent
  | { type: string };

const TERMINAL: UrlStateName[] = ["completed", "failed", "cancelled"];

function mapUrlState(b: BackendUrl): UrlState {
  return {
    url: b.url,
    media_format: b.media_format,
    state: b.status as UrlStateName,
    progress_percent: b.percent ?? 0,
    speed: b.speed ?? null,
    eta: b.eta ?? null,
    paths: b.paths ?? [],
    error: b.error ?? null,
    thumb_id: b.thumb_id ?? null,
    title: b.title ?? null,
    uploader: b.uploader ?? null,
    related_status: b.related_status ?? null,
    related: b.related_items ?? [],
  };
}

function deriveJobState(urls: UrlState[]): UrlStateName {
  if (urls.length === 0) return "queued";
  if (urls.every((u) => u.state === "completed")) return "completed";
  if (urls.every((u) => u.state === "cancelled")) return "cancelled";
  if (urls.every((u) => u.state === "queued")) return "queued";
  if (urls.some((u) => u.state === "running")) return "running";
  if (
    urls.every(
      (u) =>
        u.state === "failed" || u.state === "cancelled" || u.state === "completed"
    )
  ) {
    return urls.some((u) => u.state === "failed") ? "failed" : "completed";
  }
  return "running";
}

export function useJobEvents(jobId: string) {
  const queryClient = useQueryClient();
  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let disconnected = false;
    let sawTerminal = false;
    let lingerTimer: number | null = null;
    const pendingRelated = new Set<string>();
    const sseToastId = `sse-${jobId}`;

    // Client-initiated close is silent: no onerror, no reconnect.
    const closeNow = () => {
      if (lingerTimer !== null) {
        clearTimeout(lingerTimer);
        lingerTimer = null;
      }
      es?.close();
      es = null;
    };

    (async () => {
      const token = await discoverCsrfToken();
      if (cancelled) return;
      const url = token
        ? `/jobs/${jobId}/events?token=${encodeURIComponent(token)}`
        : `/jobs/${jobId}/events`;
      es = new EventSource(url);
      es.onmessage = (e) => {
        // A successful message means the stream is healthy again — clear any
        // "lost connection" toast a prior onerror may have raised.
        if (disconnected) {
          disconnected = false;
          toast.dismiss(sseToastId);
        }
        try {
          const event = JSON.parse(e.data) as AnyEvent;
          applyEvent(queryClient, jobId, event);

          // Track which URLs still have discovery in flight, from the events
          // themselves (the query record dies ~1.5s after terminal, so it
          // can't be the source of truth — spec "Late results").
          if (event.type === "url_metadata") {
            const m = event as UrlMetadataEvent;
            if (m.related_status === "pending") pendingRelated.add(m.url);
            else if (m.related_status !== undefined) pendingRelated.delete(m.url);
          }
          if (event.type === "job_snapshot") {
            const s = event as JobSnapshotEvent;
            for (const u of s.urls) {
              if (u.related_status === "pending") pendingRelated.add(u.url);
              else pendingRelated.delete(u.url);
            }
          }
          if (event.type === "url_related") {
            pendingRelated.delete((event as UrlRelatedEvent).url);
          }

          // Terminal handling — the close-on-terminal RELOCATED here from the
          // old unconditional close: while any COMPLETED URL's discovery is
          // pending, keep the socket open (the backend lingers ≤10s to forward
          // the late url_related), bounded by our own 10s cap. Without a close
          // on terminal, EventSource auto-reconnects and we replay the same
          // terminal snapshot in an infinite loop.
          const snapshot = queryClient.getQueryData<JobSnapshot>(["job", jobId]);
          if (snapshot && TERMINAL.includes(snapshot.state)) {
            sawTerminal = true;
            for (const u of snapshot.urls) {
              // Failed/cancelled downloads never surface a strip — their
              // results are suppressed server-side. Don't wait on them.
              if (u.state !== "completed") pendingRelated.delete(u.url);
            }
            if (pendingRelated.size === 0) {
              closeNow();
            } else if (lingerTimer === null) {
              lingerTimer = window.setTimeout(closeNow, 10_000);
            }
          }
        } catch {
          /* ignore malformed */
        }
      };
      es.onerror = () => {
        // After terminal, any error (typically the server closing the lingered
        // stream) is a clean end: close silently, never toast. sawTerminal is
        // deliberately independent of the query record, which JobTracker
        // removes ~1.5s after completion.
        const snapshot = queryClient.getQueryData<JobSnapshot>(["job", jobId]);
        if (sawTerminal || (snapshot && TERMINAL.includes(snapshot.state))) {
          closeNow();
          return;
        }
        // Non-terminal: the stream dropped mid-download. EventSource will retry
        // on its own, but the UI would otherwise freeze silently — surface it.
        if (!disconnected) {
          disconnected = true;
          toast.error("Lost connection — reconnecting…", {
            id: sseToastId,
            description: "Trying to reconnect to the download.",
          });
        }
      };
    })();
    return () => {
      cancelled = true;
      closeNow();
      toast.dismiss(sseToastId);
    };
  }, [jobId, queryClient]);
}

function applyEvent(
  qc: import("@tanstack/react-query").QueryClient,
  jobId: string,
  ev: AnyEvent
) {
  const key = ["job", jobId] as const;
  const prev = qc.getQueryData<JobSnapshot>(key);

  if (ev.type === "job_snapshot") {
    const e = ev as JobSnapshotEvent;
    const mappedUrls = e.urls.map(mapUrlState);
    const next: JobSnapshot = {
      job_id: e.job_id,
      state: deriveJobState(mappedUrls),
      started_at: prev?.started_at ?? Date.now(),
      urls: mappedUrls,
    };
    qc.setQueryData(key, next);
    return;
  }

  if (ev.type === "url_related") {
    const e = ev as UrlRelatedEvent;
    // Both actions, not either/or (spec "Late results"): patch the record
    // whenever it still exists (a pending history write reads it), and
    // ALSO upsert history when the record is missing or terminal (rows
    // already written). Both are idempotent.
    if (prev) {
      const urls = prev.urls.map((u): UrlState =>
        u.url === e.url
          ? { ...u, related_status: e.status, related: e.items ?? [] }
          : u
      );
      qc.setQueryData(key, { ...prev, urls });
    }
    if (
      (!prev || TERMINAL.includes(prev.state)) &&
      e.status === "ready" &&
      e.items?.length
    ) {
      updateHistoryItem(e.url, { related: e.items });
    }
    return;
  }

  if (!prev) return; // need a baseline snapshot first

  if (
    ev.type === "progress" ||
    ev.type === "url_started" ||
    ev.type === "url_completed" ||
    ev.type === "url_failed" ||
    ev.type === "url_metadata"
  ) {
    const e = ev as
      | ProgressEvent
      | UrlStartedEvent
      | UrlCompletedEvent
      | UrlFailedEvent
      | UrlMetadataEvent;
    const urls = prev.urls.map((u): UrlState => {
      if (u.url !== (e as { url: string }).url) return u;
      const next: UrlState = { ...u };
      if (ev.type === "url_started") {
        next.state = "running";
      }
      if (ev.type === "progress") {
        const p = e as ProgressEvent;
        if (typeof p.percent === "number") next.progress_percent = p.percent;
        if (p.speed !== undefined) next.speed = p.speed ?? null;
        if (p.eta !== undefined) next.eta = p.eta ?? null;
      }
      if (ev.type === "url_completed") {
        const c = e as UrlCompletedEvent;
        next.state = "completed";
        if (Array.isArray(c.paths)) next.paths = c.paths;
        if (c.thumb_id !== undefined) next.thumb_id = c.thumb_id ?? null;
      }
      if (ev.type === "url_failed") {
        const f = e as UrlFailedEvent;
        next.state = "failed";
        if (typeof f.error === "string") next.error = f.error;
      }
      if (ev.type === "url_metadata") {
        const m = e as UrlMetadataEvent;
        if (m.title !== undefined) next.title = m.title ?? null;
        if (m.uploader !== undefined) next.uploader = m.uploader ?? null;
        if (m.related_status !== undefined) next.related_status = m.related_status ?? null;
      }
      return next;
    });
    qc.setQueryData(key, { ...prev, urls, state: deriveJobState(urls) });
    return;
  }

  if (ev.type === "job_completed") {
    qc.setQueryData(key, { ...prev, state: deriveJobState(prev.urls) });
    return;
  }
  // Unknown / unhandled types: ignore.
}
