import { discoverCsrfToken, refreshCsrfTokenFromRoot } from "./csrf";
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

/** Build the JSON + CSRF headers carrying the given token. */
function csrfHeaders(token: string): HeadersInit {
  return token
    ? { "X-Audio-DL-Token": token, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

/**
 * Send a guarded request, recovering once from a stale CSRF token.
 *
 * A tab open across an app relaunch (no reload) carries the previous launch's
 * token and 403s against the new server. On a 403 we force-refresh the token
 * from a fresh `GET /` (the loopback server injects the current one) and, if
 * that yields a token different from the one THIS request actually sent, retry
 * exactly once. Bounded to a single retry — if the refreshed token is still
 * rejected the second 403 is returned to the caller, so there is no retry loop.
 *
 * The retry decision compares against `sentToken` — the value captured for this
 * request — not a re-read of the shared cache. Two guarded requests can leave a
 * stale tab concurrently; the first 403 handler refreshes the module cache, so
 * a re-read would make the second request see an already-fresh token, conclude
 * "unchanged", and skip the retry it still needs. Capturing the sent token per
 * request lets every concurrent stale request recover.
 */
async function csrfFetch(input: string, init: RequestInit): Promise<Response> {
  let sentToken = "";
  const send = async () => {
    sentToken = await discoverCsrfToken();
    return fetch(input, { ...init, headers: csrfHeaders(sentToken) });
  };
  const r = await send();
  if (r.status !== 403) return r;
  const fresh = await refreshCsrfTokenFromRoot();
  if (fresh && fresh !== sentToken) return send();
  return r;
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
  const r = await csrfFetch("/jobs", {
    method: "POST",
    body: JSON.stringify({ urls }),
  });
  if (!r.ok) throw await toApiError(r);
  return r.json();
}

export async function cancelJob(jobId: string): Promise<{ cancelled: boolean }> {
  const r = await csrfFetch(`/jobs/${jobId}/cancel`, {
    method: "POST",
  });
  if (!r.ok) throw await toApiError(r);
  return r.json();
}

export async function reveal(path: string): Promise<{ ok: boolean }> {
  const r = await csrfFetch("/reveal", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw await toApiError(r);
  return r.json();
}
