import { useCallback, useSyncExternalStore } from "react";
import type { HistoryItem } from "@/lib/types";

const KEY = "audio_dl_history";
const CAP = 100;

interface Envelope { v: 1; items: HistoryItem[] }

function read(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Partial<Envelope>;
    if (parsed.v !== 1 || !Array.isArray(parsed.items)) return [];
    return parsed.items;
  } catch {
    return [];
  }
}

function write(items: HistoryItem[]) {
  const envelope: Envelope = { v: 1, items };
  localStorage.setItem(KEY, JSON.stringify(envelope));
}

const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => { listeners.add(cb); return () => listeners.delete(cb); };
const notify = () => { for (const cb of listeners) cb(); };

// React-19-stable snapshot (lazy init to avoid module-load localStorage access)
let cached: HistoryItem[] | null = null;
function getSnapshot() {
  if (cached === null) cached = read();
  return cached;
}
function refresh() { cached = read(); }

export function useHistory() {
  const history = useSyncExternalStore(subscribe, getSnapshot, () => []);

  const addItem = useCallback((item: HistoryItem) => {
    const next = [item, ...read().filter((h) => h.url !== item.url)].slice(0, CAP);
    write(next);
    refresh();
    notify();
  }, []);

  const removeItem = useCallback((url: string) => {
    write(read().filter((h) => h.url !== url));
    refresh();
    notify();
  }, []);

  return { history, addItem, removeItem };
}
