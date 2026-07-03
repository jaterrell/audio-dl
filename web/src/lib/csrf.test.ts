import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { discoverCsrfToken, resetCsrfCache } from "./csrf";

describe("discoverCsrfToken", () => {
  const originalLocation = window.location;

  function setLocation(search: string) {
    Object.defineProperty(window, "location", {
      writable: true,
      value: new URL(`http://localhost:5173/${search}`),
    });
  }

  function setMetaToken(token: string) {
    const meta = document.createElement("meta");
    meta.setAttribute("name", "csrf-token");
    meta.setAttribute("content", token);
    document.head.appendChild(meta);
  }

  beforeEach(() => {
    setLocation("");
    resetCsrfCache();
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { writable: true, value: originalLocation });
    for (const el of document.querySelectorAll('meta[name="csrf-token"]')) el.remove();
  });

  it("prefers the injected <meta name=csrf-token> over the URL param", async () => {
    setMetaToken("from-meta");
    setLocation("?token=from-url");
    expect(await discoverCsrfToken()).toBe("from-meta");
  });

  it("falls back to ?token= when no meta tag is injected", async () => {
    setLocation("?token=from-url");
    expect(await discoverCsrfToken()).toBe("from-url");
  });

  it("returns token from URL ?token= when present", async () => {
    setLocation("?token=abc123");
    expect(await discoverCsrfToken()).toBe("abc123");
  });

  it("falls back to /api/csrf in dev mode", async () => {
    server.use(http.get("/api/csrf", () => HttpResponse.json({ token: "from-server" })));
    expect(await discoverCsrfToken()).toBe("from-server");
  });

  it("returns empty string if neither source has a token", async () => {
    server.use(http.get("/api/csrf", () => HttpResponse.json({}, { status: 404 })));
    expect(await discoverCsrfToken()).toBe("");
  });
});
