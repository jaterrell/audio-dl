import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useSyncExternalStore } from "react";
import type { JobSnapshot } from "@/lib/types";

const TERMINAL: JobSnapshot["state"][] = ["completed", "failed", "cancelled"];

export function useActiveJobs(): JobSnapshot[] {
  const queryClient = useQueryClient();
  const cacheRef = useRef<JobSnapshot[]>([]);

  const subscribe = useCallback(
    (onChange: () => void) => queryClient.getQueryCache().subscribe(onChange),
    [queryClient],
  );

  const getSnapshot = useCallback(() => {
    const all = queryClient.getQueriesData<JobSnapshot>({ queryKey: ["job"] });
    const next = all
      .map(([, s]) => s)
      .filter((s): s is JobSnapshot => !!s && !TERMINAL.includes(s.state))
      .sort((a, b) => b.started_at - a.started_at);
    const prev = cacheRef.current;
    if (prev.length === next.length && prev.every((j, i) => j === next[i])) {
      return prev;
    }
    cacheRef.current = next;
    return next;
  }, [queryClient]);

  return useSyncExternalStore(subscribe, getSnapshot);
}
