import { useSyncExternalStore } from "react";

export type ToastVariant = "info" | "success" | "error" | "loading";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastData {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
  action?: ToastAction;
  duration: number; // ms; Number.POSITIVE_INFINITY = sticky
}

export interface ToastOptions {
  description?: string;
  action?: ToastAction;
  duration?: number;
  id?: string; // stable id => update existing toast in place
}

const DEFAULT_DURATION: Record<ToastVariant, number> = {
  info: 4000,
  success: 4000,
  error: Number.POSITIVE_INFINITY,
  loading: Number.POSITIVE_INFINITY,
};

let toasts: ToastData[] = [];
let maxToasts = 4;
let seq = 0;
const listeners = new Set<() => void>();

function notify() {
  for (const cb of listeners) cb();
}
function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/** Current snapshot — stable reference between mutations (for tests + the hook). */
export function getToasts(): ToastData[] {
  return toasts;
}

function upsert(data: ToastData) {
  const idx = toasts.findIndex((t) => t.id === data.id);
  if (idx >= 0) {
    const next = toasts.slice();
    next[idx] = data;
    toasts = next;
  } else {
    toasts = [data, ...toasts].slice(0, maxToasts);
  }
  notify();
}

function make(variant: ToastVariant, title: string, opts: ToastOptions = {}): string {
  const id = opts.id ?? `toast-${++seq}`;
  upsert({
    id,
    variant,
    title,
    description: opts.description,
    action: opts.action,
    duration: opts.duration ?? DEFAULT_DURATION[variant],
  });
  return id;
}

function update(id: string, patch: Partial<Omit<ToastData, "id">>) {
  const idx = toasts.findIndex((t) => t.id === id);
  if (idx < 0) return;
  const next = toasts.slice();
  next[idx] = { ...next[idx], ...patch };
  toasts = next;
  notify();
}

function dismiss(id?: string) {
  toasts = id ? toasts.filter((t) => t.id !== id) : [];
  notify();
}

type Msg<T> = string | ((value: T) => string);
// A throwing message formatter must never strand the loading toast — the
// promise DID settle, so the toast must too (fall back to a generic title).
function resolveMsg<T>(m: Msg<T>, v: T, fallback: string): string {
  if (typeof m !== "function") return m;
  try {
    return (m as (v: T) => string)(v);
  } catch {
    return fallback;
  }
}

export const toast = {
  info: (title: string, opts?: ToastOptions) => make("info", title, opts),
  success: (title: string, opts?: ToastOptions) => make("success", title, opts),
  error: (title: string, opts?: ToastOptions) => make("error", title, opts),
  loading: (title: string, opts?: ToastOptions) => make("loading", title, opts),
  custom: (variant: ToastVariant, title: string, opts?: ToastOptions) => make(variant, title, opts),
  dismiss,
  promise<T>(p: Promise<T>, m: { loading: string; success: Msg<T>; error: Msg<unknown> }): string {
    const id = make("loading", m.loading);
    p.then(
      (v) =>
        update(id, {
          variant: "success",
          title: resolveMsg(m.success, v, "Done"),
          duration: DEFAULT_DURATION.success,
        }),
      (e) =>
        update(id, {
          variant: "error",
          title: resolveMsg(m.error, e, "Something went wrong"),
          duration: DEFAULT_DURATION.error,
        }),
    );
    return id;
  },
};

export function setMaxToasts(n: number) {
  maxToasts = n;
}

/** Test-only: reset module singleton state between tests. */
export function resetToastStore() {
  toasts = [];
  seq = 0;
  maxToasts = 4;
  notify();
}

export function useToasts(): ToastData[] {
  return useSyncExternalStore(subscribe, getToasts, getToasts);
}
