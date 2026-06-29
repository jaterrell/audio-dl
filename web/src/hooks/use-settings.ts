import { useCallback, useSyncExternalStore } from "react";
import type { Format } from "@/lib/types";
import type { ThemePref } from "@/lib/theme";

const KEY = "audio_dl_settings";

interface StoredSettings {
  default_format: Format;
  theme: ThemePref;
}

const DEFAULTS: StoredSettings = { default_format: "m4a", theme: "system" };

function read(): StoredSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw);
    return {
      default_format: parsed.default_format ?? DEFAULTS.default_format,
      theme: parsed.theme ?? DEFAULTS.theme,
    };
  } catch {
    return DEFAULTS;
  }
}

const listeners = new Set<() => void>();
function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function notify() {
  for (const cb of listeners) cb();
}

// Stable-snapshot wrapper to satisfy React 19 useSyncExternalStore contract:
let cached: StoredSettings | null = null;
function getSnapshot() {
  if (cached === null) cached = read();
  return cached;
}
function refresh() {
  cached = read();
}

function write(patch: Partial<StoredSettings>) {
  const next = { ...read(), ...patch };
  localStorage.setItem(KEY, JSON.stringify(next));
  refresh();
  notify();
}

export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, () => DEFAULTS);

  const setDefaultFormat = useCallback((fmt: Format) => write({ default_format: fmt }), []);
  const setTheme = useCallback((theme: ThemePref) => write({ theme }), []);

  return { settings, setDefaultFormat, setTheme };
}
