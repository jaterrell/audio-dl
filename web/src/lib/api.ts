import { discoverCsrfToken } from "./csrf";
import type { Format, VersionInfo } from "./types";

/**
 * A non-2xx HTTP response from the backend. Carries the status code and the
 * FastAPI `{"detail": ...}` message so call sites can surface it verbatim
 * instead of a generic string. A rejected `fetch` (server unreachable) throws
 * a `TypeError`, NOT an `ApiError` — that distinction drives the copy in
 * `describeError`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Build an {@link ApiError} from a failed response. Reads the body once as
 * text, then tries to pull FastAPI's JSON `detail`; falls back to the raw
 * text (or empty) so a non-JSON error page never masks the status.
 */
async function toApiError(r: Response): Promise<ApiError> {
  const text = await r.text().catch(() => "");
  let detail = "";
  if (text) {
    try {
      const data = JSON.parse(text) as { detail?: unknown };
      // Only trust a string `detail`; a JSON body without one carries no
      // user-facing message (don't surface raw "{}").
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      // Non-JSON body (HTML error page, plain text) — use it verbatim.
      detail = text;
    }
  }
  return new ApiError(r.status, detail);
}

export interface FailureCopy {
  title: string;
  description?: string;
}

/**
 * Map a queue/cancel/reveal failure to user-facing toast copy.
 *
 * - 403 with a CSRF `detail` → actionable "session expired" copy.
 * - Any other {@link ApiError} → the server's `detail` verbatim.
 * - A rejected `fetch` (server gone) → "Can't reach audio-dl".
 * - Anything else → the caller's generic fallback title.
 */
export function describeError(err: unknown, fallbackTitle: string): FailureCopy {
  if (err instanceof ApiError) {
    if (err.status === 403 && /csrf/i.test(err.detail)) {
      return {
        title: "Session expired",
        description: "Relaunch audio-dl, or reopen it from the tab it opens.",
      };
    }
    return { title: fallbackTitle, description: err.detail || undefined };
  }
  // `fetch` rejects with a TypeError when it can't reach the server.
  if (err instanceof TypeError) {
    return { title: "Can't reach audio-dl — is it running?" };
  }
  return { title: fallbackTitle };
}

async function csrfHeaders(): Promise<HeadersInit> {
  const token = await discoverCsrfToken();
  return token
    ? { "X-Audio-DL-Token": token, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

export async function getVersion(): Promise<VersionInfo> {
  const r = await fetch("/api/version");
  if (!r.ok) throw new Error(`/api/version ${r.status}`);
  return r.json();
}

export async function getDefaults(): Promise<{
  output_dir: string;
  max_parallel: number;
  available_formats: Format[];
}> {
  const r = await fetch("/api/settings/defaults");
  if (!r.ok) throw new Error(`/api/settings/defaults ${r.status}`);
  return r.json();
}

export interface PostJobsRequest {
  url: string;
  format: Format;
}

export async function postJobs(urls: PostJobsRequest[]): Promise<{ job_id: string }> {
  const r = await fetch("/jobs", {
    method: "POST",
    headers: await csrfHeaders(),
    body: JSON.stringify({ urls }),
  });
  if (!r.ok) throw await toApiError(r);
  return r.json();
}

export async function cancelJob(jobId: string): Promise<{ cancelled: boolean }> {
  const r = await fetch(`/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: await csrfHeaders(),
  });
  if (!r.ok) throw await toApiError(r);
  return r.json();
}

export async function reveal(path: string): Promise<{ ok: boolean }> {
  const r = await fetch("/reveal", {
    method: "POST",
    headers: await csrfHeaders(),
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw await toApiError(r);
  return r.json();
}
