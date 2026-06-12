import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test-utils/server";
import { resetToastStore } from "@/lib/toast-store";
import { renderWithToaster } from "@/test-utils/render";
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

describe("LibraryTileMenu toasts", () => {
  beforeEach(() => resetToastStore());

  it("shows a success toast after starting a re-download", async () => {
    server.use(http.post("/jobs", () => HttpResponse.json({ job_id: "j", urls: [] })));
    const user = userEvent.setup();
    renderWithToaster(
      <LibraryTileMenu item={item} onRemove={() => {}}>
        <button>tile</button>
      </LibraryTileMenu>,
    );
    await user.pointer({ keys: "[MouseRight]", target: screen.getByText("tile") });
    await user.click(await screen.findByText(/re-download/i));
    expect(await screen.findByText(/re-downloading/i)).toBeInTheDocument();
  });

  it("shows an error toast when reveal fails", async () => {
    server.use(http.post("/reveal", () => HttpResponse.json({}, { status: 500 })));
    const user = userEvent.setup();
    renderWithToaster(
      <LibraryTileMenu item={item} onRemove={() => {}}>
        <button>tile</button>
      </LibraryTileMenu>,
    );
    await user.pointer({ keys: "[MouseRight]", target: screen.getByText("tile") });
    await user.click(await screen.findByText(/reveal in finder/i));
    expect(await screen.findByText(/couldn't reveal/i)).toBeInTheDocument();
  });
});
