import { describe, it, expect } from "vitest";
import { groupByDay } from "./group-by-day";
import type { HistoryItem } from "./types";

function item(added_at: number): HistoryItem {
  return {
    url: `https://${added_at}`, title: null, artist: null,
    media_format: "m4a", paths: [], thumb_id: null, added_at,
  };
}

describe("groupByDay", () => {
  it("groups items by calendar day", () => {
    const now = new Date("2026-06-03T15:00:00Z").getTime();
    const yesterday = now - 24 * 60 * 60 * 1000;
    const groups = groupByDay([item(now), item(yesterday), item(yesterday - 10000)], now);
    expect(groups).toHaveLength(2);
    expect(groups[0].label).toBe("Today");
    expect(groups[1].label).toBe("Yesterday");
    expect(groups[0].items).toHaveLength(1);
    expect(groups[1].items).toHaveLength(2);
  });

  it("uses absolute date label for older items", () => {
    const now = new Date("2026-06-03T15:00:00Z").getTime();
    const aWeekAgo = now - 7 * 24 * 60 * 60 * 1000;
    const groups = groupByDay([item(aWeekAgo)], now);
    expect(groups[0].label).toMatch(/May 2[67]/);
  });
});
