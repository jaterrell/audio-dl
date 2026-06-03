import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { HeroStage } from "./stage";
import type { JobSnapshot } from "@/lib/types";

function snapshot(overrides: Partial<JobSnapshot["urls"][0]> = {}): JobSnapshot {
  return {
    job_id: "job-1",
    state: "running",
    started_at: Date.now(),
    urls: [{
      url: "https://a",
      media_format: "m4a",
      state: "running",
      progress_percent: 62,
      speed: "3.4 MB/s",
      eta: "18s",
      paths: [],
      error: null,
      thumb_id: "abc123",
      ...overrides,
    }],
  };
}

describe("HeroStage", () => {
  it("renders the URL as the title when no parsed title is available", () => {
    const { container } = renderUI(<HeroStage snapshot={snapshot()} activeCount={1} />);
    expect(container.textContent).toMatch(/https:\/\/a/);
  });

  it("renders 'Downloading · 1 of N' eyebrow", () => {
    const { getByText } = renderUI(<HeroStage snapshot={snapshot()} activeCount={3} />);
    expect(getByText(/downloading · 1 of 3/i)).toBeInTheDocument();
  });

  it("renders speed and eta", () => {
    const { container } = renderUI(<HeroStage snapshot={snapshot()} activeCount={1} />);
    expect(container.textContent).toMatch(/3\.4 MB\/s/);
    expect(container.textContent).toMatch(/18s/);
  });
});
