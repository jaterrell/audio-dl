import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderUI, renderWithToaster } from "@/test-utils/render";
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

  it("renders a related strip when the latest history item carries one", () => {
    renderWithToaster(
      <EmptyStage
        latest={{
          url: "https://a", title: "T", artist: "U", media_format: "m4a",
          paths: [], thumb_id: null, added_at: 1,
          related: [{
            id: "n1", title: "Song", artist: "Artist",
            platform: "youtube", webpage_url: "https://w",
            duration: 60, thumb_id: null,
          }],
        }}
      />
    );
    expect(screen.getByText(/more like this/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("related-tile")).toHaveLength(1);
  });

  it("renders no strip for pre-feature history records", () => {
    renderWithToaster(
      <EmptyStage
        latest={{
          url: "https://a", title: "T", artist: "U", media_format: "m4a",
          paths: [], thumb_id: null, added_at: 1,
        }}
      />
    );
    expect(screen.queryByText(/more like this/i)).toBeNull();
  });
});
