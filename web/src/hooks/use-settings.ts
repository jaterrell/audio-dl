import { useCallback, useSyncExternalStore } from "react";
import type { Format } from "@/lib/types";

const KEY = "audio_dl_settings";

interface StoredSettings {
  default_format: Format;
}

const DEFAULTS: StoredSettings = { default_format: "m4a" };

function read(): StoredSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw);
    return { default_format: parsed.default_format ?? DEFAULTS.default_format };
  } catch {
    return DEFAULTS;
  }
}

const listeners = new Set<() => void>();
function subscribe(cb: () => void) { listeners.add(cb); return () => listeners.delete(cb); }
function notify() { for (const cb of listeners) cb(); }

// Stable-snapshot wrapper to satisfy React 19 useSyncExternalStore contract:
let cached: StoredSettings | null = null;
function getSnapshot() {
  if (cached === null) cached = read();
  return cached;
}
function refresh() {
  cached = read();
}

export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, () => DEFAULTS);

  const setDefaultFormat = useCallback((fmt: Format) => {
    const next = { ...read(), default_format: fmt };
    localStorage.setItem(KEY, JSON.stringify(next));
    refresh();
    notify();
  }, []);

  return { settings, setDefaultFormat };
}
