import { describe, it, expect, vi } from "vitest";
import { renderUI } from "@/test-utils/render";
import userEvent from "@testing-library/user-event";
import { LibraryTileMenu } from "./library-tile-menu";
import type { HistoryItem } from "@/lib/types";

const item: HistoryItem = {
  url: "https://a",
  title: "X",
  artist: null,
  media_format: "m4a",
  paths: ["/tmp/x.m4a"],
  thumb_id: null,
  added_at: 0,
};

describe("LibraryTileMenu", () => {
  it("wraps children and exposes a trigger", () => {
    const { getByText } = renderUI(
      <LibraryTileMenu item={item} onRemove={() => {}}>
        <div>tile contents</div>
      </LibraryTileMenu>
    );
    expect(getByText("tile contents")).toBeInTheDocument();
  });

  it("calls onRemove from menu", async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();
    const { getByText, findByText } = renderUI(
      <LibraryTileMenu item={item} onRemove={onRemove}>
        <button>tile</button>
      </LibraryTileMenu>
    );
    // Right-click the trigger.
    await user.pointer({ keys: "[MouseRight]", target: getByText("tile") });
    await user.click(await findByText(/dismiss/i));
    expect(onRemove).toHaveBeenCalledWith("https://a");
  });
});
