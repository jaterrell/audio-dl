import { describe, it, expect } from "vitest";
import { renderUI } from "@/test-utils/render";
import { LibraryGrid } from "./library-grid";
import type { HistoryItem } from "@/lib/types";

const items: HistoryItem[] = [
  { url: "https://a", title: "Self Care", artist: "Mac Miller", media_format: "m4a", paths: [], thumb_id: "abc", added_at: Date.now() },
  { url: "https://b", title: "Let It Happen", artist: "Tame Impala", media_format: "flac", paths: [], thumb_id: "def", added_at: Date.now() - 24*60*60*1000 },
];

describe("LibraryGrid", () => {
  it("shows tiles for each item", () => {
    const { getAllByTestId } = renderUI(<LibraryGrid items={items} onRemove={() => {}} />);
    expect(getAllByTestId("library-tile")).toHaveLength(2);
  });

  it("shows day group headers", () => {
    const { getByText } = renderUI(<LibraryGrid items={items} onRemove={() => {}} />);
    expect(getByText("Today")).toBeInTheDocument();
    expect(getByText("Yesterday")).toBeInTheDocument();
  });

  it("renders quiet empty state when items is empty", () => {
    const { getByText } = renderUI(<LibraryGrid items={[]} onRemove={() => {}} />);
    expect(getByText(/nothing yet/i)).toBeInTheDocument();
  });

  it("distinguishes 'no results' from 'nothing yet' when filtering", () => {
    const { getByText, queryByText } = renderUI(
      <LibraryGrid items={[]} onRemove={() => {}} isFiltered />
    );
    expect(getByText(/no results/i)).toBeInTheDocument();
    expect(queryByText(/nothing yet/i)).toBeNull();
  });
});
