import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { server } from "@/test-utils/server";
import { http, HttpResponse } from "msw";
import { UrlInput } from "./url-input";
import { screen } from "@testing-library/react";
import { resetToastStore } from "@/lib/toast-store";
import { renderWithToaster } from "@/test-utils/render";
import * as trackedJobs from "@/lib/tracked-jobs";

beforeEach(() => {
  localStorage.clear();
  trackedJobs.resetTrackedJobs();
});

describe("UrlInput", () => {
  it("submits a single URL with the current default format and tracks the job", async () => {
    const user = userEvent.setup();
    const trackSpy = vi.spyOn(trackedJobs, "trackJob");
    let captured: { url: string; format: string }[] = [];
    server.use(
      http.post("/jobs", async ({ request }) => {
        captured = ((await request.json()) as { urls: { url: string; format: string }[] }).urls;
        return HttpResponse.json({ job_id: "job-x" });
      })
    );
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput />);
    const input = getByPlaceholderText(/paste a url/i);
    await user.type(input, "https://youtu.be/abc");
    await user.click(getByRole("button", { name: /add/i }));
    expect(captured).toEqual([{ url: "https://youtu.be/abc", format: "m4a" }]);
    await vi.waitFor(() => expect(trackSpy).toHaveBeenCalledWith("job-x"));
    trackSpy.mockRestore();
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
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput />);
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
    const { getByPlaceholderText, getByRole } = renderUI(<UrlInput />);
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
    renderWithToaster(<UrlInput />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/couldn't queue/i)).toBeInTheDocument();
  });

  it("shows a success toast after queueing", async () => {
    // Backend-accurate shape: post_jobs returns {"job_id"} ONLY (audio_dl_ui/__init__.py).
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "j" })));
    const user = userEvent.setup();
    renderWithToaster(<UrlInput />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/queued 1 download/i)).toBeInTheDocument();
  });

  it("shows actionable session-expired copy on a 403 CSRF rejection", async () => {
    server.use(
      http.post("/jobs", () =>
        HttpResponse.json({ detail: "Invalid CSRF token." }, { status: 403 }),
      ),
    );
    const user = userEvent.setup();
    renderWithToaster(<UrlInput />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/session expired/i)).toBeInTheDocument();
    expect(screen.getByText(/relaunch audio-dl/i)).toBeInTheDocument();
  });

  it("surfaces the server detail on a 400 rejection", async () => {
    server.use(
      http.post("/jobs", () =>
        HttpResponse.json({ detail: "Unknown format: xyz." }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithToaster(<UrlInput />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/couldn't queue download/i)).toBeInTheDocument();
    expect(screen.getByText(/unknown format: xyz\./i)).toBeInTheDocument();
  });

  it("shows distinct copy when the server is unreachable", async () => {
    server.use(http.post("/jobs", () => HttpResponse.error()));
    const user = userEvent.setup();
    renderWithToaster(<UrlInput />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/can't reach audio-dl/i)).toBeInTheDocument();
  });

  it("falls back to generic copy for an unrecognized failure (no detail)", async () => {
    server.use(http.post("/jobs", () => new HttpResponse("boom", { status: 500 })));
    const user = userEvent.setup();
    renderWithToaster(<UrlInput />);
    await user.type(screen.getByPlaceholderText(/paste a url/i), "https://x.test/a");
    await user.click(screen.getByRole("button", { name: /add/i }));
    expect(await screen.findByText(/couldn't queue download/i)).toBeInTheDocument();
  });
});
