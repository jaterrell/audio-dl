import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { UrlInput } from "./url-input";
import { screen } from "@testing-library/react";
import { resetToastStore } from "@/lib/toast-store";
import { renderWithToaster } from "@/test-utils/render";

beforeEach(() => localStorage.clear());

describe("UrlInput", () => {
  it("submits a single URL with the current default format", async () => {
    const user = userEvent.setup();
    const onJobCreated = vi.fn();
    let captured: { url: string; format: string }[] = [];
    server.use(
      http.post("/jobs", async ({ request }) => {
        captured = ((await request.json()) as { urls: { url: string; format: string }[] }).urls;
        return HttpResponse.json({ job_id: "job-x" });
      })
    );
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput onJobCreated={onJobCreated} />);
    const input = getByPlaceholderText(/paste a url/i);
    await user.type(input, "https://youtu.be/abc");
    await user.click(getByRole("button", { name: /add/i }));
    expect(captured).toEqual([{ url: "https://youtu.be/abc", format: "m4a" }]);
    expect(onJobCreated).toHaveBeenCalledWith("job-x");
  });

  it("splits multi-line paste into N URL+format pairs", async () => {
    const user = userEvent.setup();
    let captured: { url: string; format: string }[] = [];
    server.use(
      http.post("/jobs", async ({ request }) => {
        captured = ((await request.json()) as { urls: { url: string; format: string }[] }).urls;
        return HttpResponse.json({ job_id: "job-y" });
      })
    );
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput onJobCreated={() => {}} />);
    const input = getByPlaceholderText(/paste a url/i);
    await user.click(input);
    await user.paste("https://a\nhttps://b\nhttps://c");
    await user.click(getByRole("button", { name: /add/i }));
    expect(captured).toEqual([
      { url: "https://a", format: "m4a" },
      { url: "https://b", format: "m4a" },
      { url: "https://c", format: "m4a" },
    ]);
  });

  it("clears the input on successful submit", async () => {
    const user = userEvent.setup();
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "job-z" })));
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput onJobCreated={() => {}} />);
    const input = getByPlaceholderText(/paste a url/i) as HTMLInputElement;
    await user.type(input, "https://x");
    await user.click(getByRole("button", { name: /add/i }));
    expect(input.value).toBe("");
  });
});

describe("UrlInput toasts", () => {
  beforeEach(() => resetToastStore());

  it("shows an error toast when the job request fails", async () => {
    server.use(http.post("/jobs", () => HttpResponse.json({ detail: "no" }, { status: 500 })));
    const user = userEvent.setup();
    renderWithToaster(<UrlInput onJobCreated={() => {}} />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/couldn't queue/i)).toBeInTheDocument();
  });

  it("shows a success toast after queueing", async () => {
    // Backend-accurate shape: post_jobs returns {"job_id"} ONLY (audio_dl_ui/__init__.py).
    // v2.1.0 shipped with mocks returning a fictional `urls` key; the success
    // formatter's r.urls.length then threw in production and the loading toast
    // never resolved.
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "j" })));
    const user = userEvent.setup();
    renderWithToaster(<UrlInput onJobCreated={() => {}} />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/queued 1 download/i)).toBeInTheDocument();
  });
});
