import { useSyncExternalStore } from "react";

// App-wide set of job ids with a live JobTracker. Mounted once in the app shell
// (not per route), so tracking — SSE progress, completion toasts, history adds —
// survives route changes and works for jobs started anywhere (URL bar, retry,
// library re-download).

let ids: string[] = [];
const listeners = new Set<() => void>();

function notify() {
  for (const cb of listeners) cb();
}

export function trackJob(id: string): void {
  if (ids.includes(id)) return;
  ids = [...ids, id];
  notify();
}

export function untrackJob(id: string): void {
  if (!ids.includes(id)) return;
  ids = ids.filter((x) => x !== id);
  notify();
}

function getSnapshot(): string[] {
  return ids;
}

export function useTrackedJobs(): string[] {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    getSnapshot,
    getSnapshot,
  );
}

/** Test-only: reset the singleton between tests. */
export function resetTrackedJobs(): void {
  ids = [];
  notify();
}
