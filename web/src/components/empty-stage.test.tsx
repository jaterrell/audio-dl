import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { EmptyStage } from "./empty-stage";
import type { HistoryItem } from "@/lib/types";

const latest: HistoryItem = {
  url: "https://a", title: "Self Care", artist: "Mac Miller", media_format: "m4a",
  paths: ["/tmp/a.m4a"], thumb_id: "abc", added_at: 0,
};

describe("EmptyStage", () => {
  it("shows 'Last added' eyebrow when history is present", () => {
    const { getByText } = renderUI(<EmptyStage latest={latest} />);
    expect(getByText(/last added/i)).toBeInTheDocument();
    expect(getByText(/self care/i)).toBeInTheDocument();
  });

  it("shows quiet wordmark when no history", () => {
    const { getByText } = renderUI(<EmptyStage latest={null} />);
    expect(getByText(/paste a url to get started/i)).toBeInTheDocument();
  });
});
