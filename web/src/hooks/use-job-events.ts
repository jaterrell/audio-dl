import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { JobSnapshot, UrlState, UrlStateName, Format } from "@/lib/types";
import { discoverCsrfToken } from "@/lib/csrf";

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
  | JobCompletedEvent
  | { type: string };

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
    (async () => {
      const token = await discoverCsrfToken();
      if (cancelled) return;
      const url = token
        ? `/jobs/${jobId}/events?token=${encodeURIComponent(token)}`
        : `/jobs/${jobId}/events`;
      es = new EventSource(url);
      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as AnyEvent;
          applyEvent(queryClient, jobId, event);
        } catch {
          /* ignore malformed */
        }
      };
    })();
    return () => {
      cancelled = true;
      es?.close();
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

  if (!prev) return; // need a baseline snapshot first

  if (
    ev.type === "progress" ||
    ev.type === "url_started" ||
    ev.type === "url_completed" ||
    ev.type === "url_failed"
  ) {
    const e = ev as ProgressEvent | UrlStartedEvent | UrlCompletedEvent | UrlFailedEvent;
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
