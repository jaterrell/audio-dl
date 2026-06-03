import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { Queue } from "./queue";
import type { JobSnapshot } from "@/lib/types";

function snap(id: string): JobSnapshot {
  return {
    job_id: id,
    state: "queued",
    started_at: 0,
    urls: [{
      url: `https://${id}`, media_format: "m4a", state: "queued",
      progress_percent: 0, speed: null, eta: null,
      paths: [], error: null, thumb_id: null, title: null, uploader: null,
    }],
  };
}

describe("Queue", () => {
  it("renders nothing when empty", () => {
    const { container } = renderUI(<Queue jobs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows N queued count", () => {
    const { getByText } = renderUI(<Queue jobs={[snap("a"), snap("b"), snap("c")]} />);
    expect(getByText(/3 queued/)).toBeInTheDocument();
  });

  it("renders one row per queued job", () => {
    const { getAllByTestId } = renderUI(<Queue jobs={[snap("a"), snap("b")]} />);
    expect(getAllByTestId("queue-row")).toHaveLength(2);
  });
});
