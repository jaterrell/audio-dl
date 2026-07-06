import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useHistory } from "./use-history";
import type { HistoryItem } from "@/lib/types";

beforeEach(() => localStorage.clear());

function mk(url: string, added_at: number): HistoryItem {
  return {
    url, title: null, artist: null, media_format: "m4a",
    paths: [], thumb_id: null, added_at,
  };
}

describe("useHistory", () => {
  it("returns empty when nothing stored", () => {
    const { result } = renderHook(() => useHistory());
    expect(result.current.history).toEqual([]);
  });

  it("prepends items via addItem", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.addItem(mk("https://b", 2)));
    expect(result.current.history.map((h) => h.url)).toEqual(["https://b", "https://a"]);
  });

  it("caps at 100 entries with FIFO drop", () => {
    const { result } = renderHook(() => useHistory());
    act(() => {
      for (let i = 0; i < 105; i++) result.current.addItem(mk(`https://${i}`, i));
    });
    expect(result.current.history).toHaveLength(100);
    expect(result.current.history[99].url).toBe("https://5");
  });

  it("removes an item by url", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.addItem(mk("https://b", 2)));
    act(() => result.current.removeItem("https://a"));
    expect(result.current.history.map((h) => h.url)).toEqual(["https://b"]);
  });

  it("updateItem patches the newest record matching the url", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.addItem(mk("https://b", 2)));
    const related = [{
      id: "n1", title: "Song", artist: "Artist", platform: "youtube" as const,
      webpage_url: "https://www.youtube.com/watch?v=n1",
      duration: 60, thumb_id: null,
    }];
    act(() => result.current.updateItem("https://a", { related }));
    const a = result.current.history.find((h) => h.url === "https://a")!;
    expect(a.related).toEqual(related);
    // Other records untouched.
    expect(result.current.history.find((h) => h.url === "https://b")!.related)
      .toBeUndefined();
  });

  it("updateItem no-ops when no record matches", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.updateItem("https://zzz", { title: "X" }));
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0].title).toBeNull();
  });

  it("module-level updateItem notifies mounted subscribers", async () => {
    const { updateItem } = await import("./use-history");
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => updateItem("https://a", { title: "Patched" }));
    expect(result.current.history[0].title).toBe("Patched");
  });
});
