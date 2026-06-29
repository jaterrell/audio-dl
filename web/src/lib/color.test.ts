import { describe, it, expect, vi } from "vitest";
import {
  hexToRgb,
  rgbToHex,
  rgbToHsl,
  hslToRgb,
  relativeLuminance,
  onAccent,
  clampForMode,
  quantizeDominant,
  buildPalette,
  extractPalette,
} from "./color";

describe("color math", () => {
  it("hex <-> rgb round-trips", () => {
    expect(hexToRgb("#ff00ff")).toEqual([255, 0, 255]);
    expect(rgbToHex(255, 0, 255)).toBe("#ff00ff");
    expect(hexToRgb("#f0f")).toEqual([255, 0, 255]);
  });
  it("rgb -> hsl for pure red", () => {
    const [h, s, l] = rgbToHsl(255, 0, 0);
    expect(Math.round(h)).toBe(0);
    expect(s).toBeCloseTo(1, 2);
    expect(l).toBeCloseTo(0.5, 2);
  });
  it("hsl -> rgb for pure red", () => {
    const [r, g, b] = hslToRgb(0, 1, 0.5);
    expect([Math.round(r), Math.round(g), Math.round(b)]).toEqual([255, 0, 0]);
  });
  it("relative luminance of black is 0 and white is 1", () => {
    expect(relativeLuminance("#000000")).toBeCloseTo(0, 3);
    expect(relativeLuminance("#ffffff")).toBeCloseTo(1, 3);
  });
  it("onAccent picks the WCAG-more-legible text color", () => {
    expect(onAccent("#ffffff")).toBe("#000000");
    expect(onAccent("#10182a")).toBe("#ffffff");
    // mid-luminance indigo (L≈0.30) — black (7:1) beats white (3:1)
    expect(onAccent("#818cf8")).toBe("#000000");
  });
});

describe("clampForMode", () => {
  it("raises lightness of a dark color in dark mode", () => {
    const [, , l] = rgbToHsl(...hexToRgb(clampForMode("#10182a", "dark")));
    expect(l).toBeGreaterThanOrEqual(0.55);
  });
  it("lowers lightness of a pale color in light mode", () => {
    const [, , l] = rgbToHsl(...hexToRgb(clampForMode("#fde8ff", "light")));
    expect(l).toBeLessThanOrEqual(0.52);
  });
});

function fill(rgb: [number, number, number], count: number): Uint8ClampedArray {
  const px = new Uint8ClampedArray(count * 4);
  for (let i = 0; i < count; i++) {
    px[i * 4] = rgb[0];
    px[i * 4 + 1] = rgb[1];
    px[i * 4 + 2] = rgb[2];
    px[i * 4 + 3] = 255;
  }
  return px;
}

describe("quantizeDominant", () => {
  it("returns the dominant vivid color", () => {
    const q = quantizeDominant(fill([255, 0, 255], 64));
    expect(q).not.toBeNull();
    const [h] = rgbToHsl(...hexToRgb(q!.accent));
    expect(Math.round(h)).toBe(300);
  });
  it("returns null for an all-gray image", () => {
    expect(quantizeDominant(fill([128, 128, 128], 64))).toBeNull();
  });
});

describe("buildPalette", () => {
  it("clamps, derives ambient, and chooses on-accent", () => {
    const p = buildPalette("#10182a", "#203050", "dark");
    expect(p.accent).toMatch(/^#/);
    expect(p.ambient).toMatch(/^rgb\(/);
    // #10182a clamps up to a medium blue (L≈0.22) in dark mode → black is more legible
    expect(p.onAccent).toBe("#000000");
  });
});

describe("extractPalette", () => {
  it("returns null when 2d context is unavailable", () => {
    const img = document.createElement("img");
    const spy = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null as never);
    expect(extractPalette(img, "dark")).toBeNull();
    spy.mockRestore();
  });
  it("builds a palette from canvas pixels", () => {
    const img = document.createElement("img");
    const data = fill([255, 0, 255], 32 * 32);
    const fakeCtx = { drawImage: vi.fn(), getImageData: () => ({ data }) } as unknown as CanvasRenderingContext2D;
    const spy = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(fakeCtx as never);
    const p = extractPalette(img, "dark");
    expect(p).not.toBeNull();
    expect(p!.onAccent).toMatch(/^#(000000|ffffff)$/);
    spy.mockRestore();
  });
});
