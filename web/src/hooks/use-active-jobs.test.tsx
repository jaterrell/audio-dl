import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { JobSnapshot } from "@/lib/types";
import { useActiveJobs } from "./use-active-jobs";

function snapshot(id: string, state: JobSnapshot["state"], startedAt: number): JobSnapshot {
  return { job_id: id, state, started_at: startedAt, urls: [] };
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useActiveJobs", () => {
  it("returns only non-terminal jobs, latest-started first", () => {
    const client = new QueryClient();
    client.setQueryData(["job", "a"], snapshot("a", "running", 100));
    client.setQueryData(["job", "b"], snapshot("b", "completed", 200));
    client.setQueryData(["job", "c"], snapshot("c", "running", 300));
    const { result } = renderHook(() => useActiveJobs(), { wrapper: wrapper(client) });
    expect(result.current.map((j) => j.job_id)).toEqual(["c", "a"]);
  });

  it("returns empty list when nothing is running", () => {
    const client = new QueryClient();
    client.setQueryData(["job", "a"], snapshot("a", "completed", 100));
    const { result } = renderHook(() => useActiveJobs(), { wrapper: wrapper(client) });
    expect(result.current).toEqual([]);
  });
});
