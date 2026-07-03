import { describe, it, expect, beforeEach } from "vitest";
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
