import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { AlsoDownloading } from "./also-downloading";
import type { JobSnapshot } from "@/lib/types";

function snap(id: string, percent: number): JobSnapshot {
  return {
    job_id: id,
    state: "running",
    started_at: 0,
    urls: [{
      url: `https://${id}`, media_format: "m4a", state: "running",
      progress_percent: percent, speed: null, eta: null,
      paths: [], error: null, thumb_id: null, title: null, uploader: null,
    }],
  };
}

describe("AlsoDownloading", () => {
  it("renders nothing when given empty list", () => {
    const { container } = renderUI(<AlsoDownloading jobs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders one card per job", () => {
    const { getAllByTestId } = renderUI(<AlsoDownloading jobs={[snap("a", 10), snap("b", 90)]} />);
    expect(getAllByTestId("also-card")).toHaveLength(2);
  });

  it("renders a card per URL with a single job-level cancel for multi-URL jobs", () => {
    const multi: JobSnapshot = {
      job_id: "batch",
      state: "running",
      started_at: 0,
      urls: ["https://1", "https://2", "https://3"].map((url, i) => ({
        url, media_format: "m4a", state: "running", progress_percent: i * 10,
        speed: null, eta: null, paths: [], error: null, thumb_id: null, title: null, uploader: null,
      })),
    };
    const { getAllByTestId, getAllByRole } = renderUI(<AlsoDownloading jobs={[multi]} />);
    expect(getAllByTestId("also-card")).toHaveLength(3);
    // cancel is job-level, so it appears once (on the first card), not per URL
    expect(getAllByRole("button", { name: /cancel/i })).toHaveLength(1);
  });

  it("suppresses cancel for the stage job when stageJobId is set", () => {
    // stageJob's extra URLs (urls[1:]) appear here; their cancel lives on HeroStage
    const stageExtra: JobSnapshot = {
      job_id: "stage",
      state: "running",
      started_at: 0,
      urls: ["https://2", "https://3"].map((url, i) => ({
        url, media_format: "m4a", state: "running", progress_percent: i * 50,
        speed: null, eta: null, paths: [], error: null, thumb_id: null, title: null, uploader: null,
      })),
    };
    const { getAllByTestId, queryAllByRole } = renderUI(
      <AlsoDownloading jobs={[stageExtra]} stageJobId="stage" />
    );
    expect(getAllByTestId("also-card")).toHaveLength(2);
    // no cancel here — it's already on HeroStage
    expect(queryAllByRole("button", { name: /cancel/i })).toHaveLength(0);
  });
});
