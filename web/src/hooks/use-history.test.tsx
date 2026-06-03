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
});
