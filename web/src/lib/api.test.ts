import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import {
  ApiError,
  describeError,
  getVersion,
  getDefaults,
  postJobs,
  cancelJob,
  reveal,
} from "./api";
import { resetCsrfCache } from "./csrf";

beforeEach(() => {
  resetCsrfCache();
  Object.defineProperty(window, "location", {
    writable: true,
    value: new URL("http://localhost:5173/?token=test-csrf"),
  });
});

afterEach(() => {
  for (const el of document.querySelectorAll('meta[name="csrf-token"]')) el.remove();
});

describe("api.getVersion", () => {
  it("returns version info", async () => {
    const data = await getVersion();
    expect(data.version).toBe("2.0.0-test");
  });
});

describe("api.getDefaults", () => {
  it("returns launch defaults", async () => {
    const data = await getDefaults();
    expect(data.max_parallel).toBe(4);
    expect(data.available_formats).toContain("mp3");
  });
});

describe("api.postJobs", () => {
  it("posts urls with CSRF header and returns job_id", async () => {
    server.use(
      http.post("/jobs", async ({ request }) => {
        expect(request.headers.get("X-Audio-DL-Token")).toBe("test-csrf");
        const body = (await request.json()) as { urls: { url: string; format: string }[] };
        expect(body.urls).toHaveLength(2);
        return HttpResponse.json({ job_id: "job-1", urls: body.urls });
      })
    );
    const r = await postJobs([
      { url: "https://a", format: "mp3" },
      { url: "https://b", format: "m4a" },
    ]);
    expect(r.job_id).toBe("job-1");
  });
});

describe("api.cancelJob", () => {
  it("posts cancel with CSRF and parses ok", async () => {
    server.use(
      http.post("/jobs/job-1/cancel", () => HttpResponse.json({ cancelled: true }))
    );
    await expect(cancelJob("job-1")).resolves.toEqual({ cancelled: true });
  });
});

describe("api.reveal", () => {
  it("posts a path", async () => {
    server.use(http.post("/reveal", () => HttpResponse.json({ ok: true })));
    await expect(reveal("/tmp/file.mp3")).resolves.toEqual({ ok: true });
  });
});

describe("api error propagation", () => {
  it("postJobs throws a typed ApiError carrying status + FastAPI detail", async () => {
    server.use(
      http.post("/jobs", () =>
        HttpResponse.json({ detail: "Duplicate URL" }, { status: 400 }),
      ),
    );
    await expect(postJobs([{ url: "https://a", format: "mp3" }])).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      detail: "Duplicate URL",
    });
  });

  it("cancelJob throws an ApiError on CSRF rejection", async () => {
    server.use(
      http.post("/jobs/job-1/cancel", () =>
        HttpResponse.json({ detail: "Missing CSRF token." }, { status: 403 }),
      ),
    );
    await expect(cancelJob("job-1")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("api CSRF refresh on 403", () => {
  function rootHtml(token: string): string {
    return `<!doctype html><html><head><meta name="csrf-token" content="${token}"></head><body></body></html>`;
  }

  it("refreshes the token from / on a 403 and retries the request once", async () => {
    let posts = 0;
    let rootFetches = 0;
    server.use(
      http.get("/", () => {
        rootFetches++;
        return new HttpResponse(rootHtml("fresh-token"), {
          headers: { "Content-Type": "text/html" },
        });
      }),
      http.post("/jobs", ({ request }) => {
        posts++;
        // Stale token (the tab's pre-relaunch value) is rejected; the
        // refreshed token from / is accepted.
        if (request.headers.get("X-Audio-DL-Token") !== "fresh-token") {
          return HttpResponse.json({ detail: "Invalid CSRF token." }, { status: 403 });
        }
        return HttpResponse.json({ job_id: "job-after-refresh" });
      }),
    );

    const r = await postJobs([{ url: "https://a", format: "mp3" }]);
    expect(r.job_id).toBe("job-after-refresh");
    expect(posts).toBe(2); // initial (stale) + one retry (fresh)
    expect(rootFetches).toBe(1); // exactly one refresh
  });

  it("surfaces the 403 without looping when the refreshed token is still rejected", async () => {
    let posts = 0;
    let rootFetches = 0;
    server.use(
      http.get("/", () => {
        rootFetches++;
        return new HttpResponse(rootHtml("still-bad"), {
          headers: { "Content-Type": "text/html" },
        });
      }),
      http.post("/jobs", () => {
        posts++;
        return HttpResponse.json({ detail: "Invalid CSRF token." }, { status: 403 });
      }),
    );

    await expect(postJobs([{ url: "https://a", format: "mp3" }])).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
    });
    expect(posts).toBe(2); // bounded to a single retry — no loop
    expect(rootFetches).toBe(1);
  });

  it("retries against the token IT sent, not a cache a concurrent 403 already refreshed", async () => {
    // Two guarded requests leave a stale tab at once after an app relaunch.
    // The first 403 handler refreshes the shared module cache to the fresh
    // token before the second request evaluates its own retry. A retry
    // decision that re-reads the cache would see fresh === "current" and skip
    // the retry — even though this request actually sent the stale token.
    // Simulate that raced refresh by swapping the cache to the fresh token the
    // moment the stale POST is rejected.
    let posts = 0;
    server.use(
      http.get("/", () => {
        return new HttpResponse(rootHtml("fresh-token"), {
          headers: { "Content-Type": "text/html" },
        });
      }),
      http.post("/jobs", ({ request }) => {
        posts++;
        if (request.headers.get("X-Audio-DL-Token") !== "fresh-token") {
          // Emulate a concurrent handler having already refreshed the cache.
          const meta = document.createElement("meta");
          meta.setAttribute("name", "csrf-token");
          meta.setAttribute("content", "fresh-token");
          document.head.appendChild(meta);
          resetCsrfCache();
          return HttpResponse.json({ detail: "Invalid CSRF token." }, { status: 403 });
        }
        return HttpResponse.json({ job_id: "job-recovered" });
      }),
    );

    // sentToken is captured as the stale "test-csrf" at send time, so the
    // refreshed "fresh-token" is correctly seen as different and the retry fires.
    const r = await postJobs([{ url: "https://a", format: "mp3" }]);
    expect(r.job_id).toBe("job-recovered");
    expect(posts).toBe(2);
  });

  it("does not refresh on a successful request (fresh-load behavior unchanged)", async () => {
    let rootFetches = 0;
    server.use(
      http.get("/", () => {
        rootFetches++;
        return new HttpResponse(rootHtml("unused"), {
          headers: { "Content-Type": "text/html" },
        });
      }),
      http.post("/jobs", ({ request }) => {
        expect(request.headers.get("X-Audio-DL-Token")).toBe("test-csrf");
        return HttpResponse.json({ job_id: "job-ok" });
      }),
    );

    const r = await postJobs([{ url: "https://a", format: "mp3" }]);
    expect(r.job_id).toBe("job-ok");
    expect(rootFetches).toBe(0); // no 403, so no token refresh
  });
});

describe("describeError", () => {
  it("maps a 403 CSRF failure to actionable session-expired copy", () => {
    const copy = describeError(new ApiError(403, "Invalid CSRF token."), "fallback");
    expect(copy.title).toMatch(/session expired/i);
    expect(copy.description).toMatch(/relaunch audio-dl/i);
  });

  it("surfaces the server detail for a 400", () => {
    const copy = describeError(new ApiError(400, "output_dir not writable"), "Couldn't queue");
    expect(copy.title).toBe("Couldn't queue");
    expect(copy.description).toBe("output_dir not writable");
  });

  it("keeps a non-CSRF 403 detail rather than the session-expired copy", () => {
    const copy = describeError(
      new ApiError(403, "Path is not inside an allowed output directory."),
      "Couldn't reveal file",
    );
    expect(copy.title).toBe("Couldn't reveal file");
    expect(copy.description).toMatch(/not inside an allowed/i);
  });

  it("distinguishes a network-level failure (fetch rejects with TypeError)", () => {
    const copy = describeError(new TypeError("Failed to fetch"), "fallback");
    expect(copy.title).toMatch(/can't reach audio-dl/i);
  });

  it("falls back to the generic title for an unknown error", () => {
    const copy = describeError(new Error("boom"), "Couldn't queue download");
    expect(copy).toEqual({ title: "Couldn't queue download" });
  });
});
