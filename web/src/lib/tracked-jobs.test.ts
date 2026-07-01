import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { trackJob, untrackJob, useTrackedJobs, resetTrackedJobs } from "./tracked-jobs";

beforeEach(() => resetTrackedJobs());

describe("tracked-jobs", () => {
  it("tracks job ids and de-duplicates", () => {
    const { result } = renderHook(() => useTrackedJobs());
    act(() => {
      trackJob("a");
      trackJob("a");
      trackJob("b");
    });
    expect(result.current).toEqual(["a", "b"]);
  });

  it("untracks a job id", () => {
    const { result } = renderHook(() => useTrackedJobs());
    act(() => {
      trackJob("a");
      trackJob("b");
    });
    act(() => untrackJob("a"));
    expect(result.current).toEqual(["b"]);
  });
});
