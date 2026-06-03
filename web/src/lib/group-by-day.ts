import type { HistoryItem } from "./types";

export interface DayGroup {
  label: string;
  items: HistoryItem[];
}

function startOfDay(ts: number): number {
  const d = new Date(ts);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function label(itemDay: number, todayDay: number): string {
  const dayMs = 24 * 60 * 60 * 1000;
  if (itemDay === todayDay) return "Today";
  if (itemDay === todayDay - dayMs) return "Yesterday";
  return new Date(itemDay).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

export function groupByDay(items: HistoryItem[], now: number = Date.now()): DayGroup[] {
  const today = startOfDay(now);
  const map = new Map<number, HistoryItem[]>();
  for (const item of items) {
    const day = startOfDay(item.added_at);
    if (!map.has(day)) map.set(day, []);
    map.get(day)!.push(item);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => b - a)
    .map(([day, items]) => ({ label: label(day, today), items }));
}
