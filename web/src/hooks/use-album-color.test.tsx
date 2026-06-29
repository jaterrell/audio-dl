import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@/lib/color", () => ({
  extractPalette: vi.fn(() => ({
    accent: "#112233",
    accent2: "#445566",
    ambient: "rgb(17 34 51 / 0.18)",
    onAccent: "#ffffff",
  })),
}));

import { useAlbumColor } from "./use-album-color";

class FakeImage {
  onload: (() => void) | null = null;
  crossOrigin = "";
  referrerPolicy = "";
  complete = false;
  naturalWidth = 0;
  set src(_v: string) {
    this.complete = true;
    this.naturalWidth = 10;
    queueMicrotask(() => this.onload?.());
  }
}

beforeEach(() => {
  vi.stubGlobal("Image", FakeImage);
  document.documentElement.removeAttribute("style");
});
afterEach(() => vi.unstubAllGlobals());

describe("useAlbumColor", () => {
  it("writes accent vars when an image loads", async () => {
    renderHook(() => useAlbumColor("/thumbs/x.jpg", "dark"));
    await new Promise((r) => setTimeout(r, 0));
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#112233");
    expect(document.documentElement.style.getPropertyValue("--on-accent")).toBe("#ffffff");
  });
  it("resets to brand by removing inline vars when src is null", () => {
    document.documentElement.style.setProperty("--accent", "#999999");
    renderHook(() => useAlbumColor(null, "dark"));
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("");
  });
});
