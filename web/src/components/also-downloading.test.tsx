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
});
