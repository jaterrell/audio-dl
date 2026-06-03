import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSettings } from "./use-settings";

beforeEach(() => localStorage.clear());

describe("useSettings", () => {
  it("returns m4a as default format when nothing stored", () => {
    const { result } = renderHook(() => useSettings());
    expect(result.current.settings.default_format).toBe("m4a");
  });

  it("persists changes to localStorage", () => {
    const { result } = renderHook(() => useSettings());
    act(() => result.current.setDefaultFormat("flac"));
    expect(JSON.parse(localStorage.getItem("audio_dl_settings")!).default_format).toBe("flac");
  });

  it("re-reads value after setting", () => {
    const { result } = renderHook(() => useSettings());
    act(() => result.current.setDefaultFormat("opus"));
    expect(result.current.settings.default_format).toBe("opus");
  });
});
