import type { Mode } from "./theme";

export interface Palette {
  accent: string;
  accent2: string;
  ambient: string;
  onAccent: string;
}

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const int = parseInt(n, 16);
  return [(int >> 16) & 255, (int >> 8) & 255, int & 255];
}

export function rgbToHex(r: number, g: number, b: number): string {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

export function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  let h = 0;
  let s = 0;
  if (d !== 0) {
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return [h, s, l];
}

export function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const hue = (((h % 360) + 360) % 360) / 360;
  if (s === 0) {
    const v = l * 255;
    return [v, v, v];
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const ch = (t: number) => {
    t = ((t % 1) + 1) % 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [ch(hue + 1 / 3) * 255, ch(hue) * 255, ch(hue - 1 / 3) * 255];
}

export function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function onAccent(hex: string): "#000000" | "#ffffff" {
  // WCAG crossover: black and white give equal contrast at L = sqrt(0.0525) - 0.05
  // ≈ 0.179. Above it, black is the more legible (higher-ratio) text color.
  return relativeLuminance(hex) > 0.179 ? "#000000" : "#ffffff";
}

export function clampForMode(hex: string, mode: Mode): string {
  const [h, s0, l0] = rgbToHsl(...hexToRgb(hex));
  let s = s0;
  let l = l0;
  if (mode === "dark") {
    l = Math.min(Math.max(l, 0.58), 0.82);
    if (s < 0.35) s = 0.5;
  } else {
    l = Math.min(Math.max(l, 0.3), 0.48);
    if (s < 0.45) s = 0.6;
  }
  return rgbToHex(...hslToRgb(h, s, l));
}

export function quantizeDominant(
  pixels: Uint8ClampedArray,
): { accent: string; accent2: string } | null {
  const buckets = new Map<number, { w: number; r: number; g: number; b: number }>();
  let vivid = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    if (pixels[i + 3] < 128) continue;
    const r = pixels[i];
    const g = pixels[i + 1];
    const b = pixels[i + 2];
    const s = rgbToHsl(r, g, b)[1];
    if (s < 0.15) continue;
    vivid += s;
    const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
    const e = buckets.get(key);
    if (e) {
      e.w += s;
      e.r += r * s;
      e.g += g * s;
      e.b += b * s;
    } else {
      buckets.set(key, { w: s, r: r * s, g: g * s, b: b * s });
    }
  }
  if (vivid < 1 || buckets.size === 0) return null;
  const sorted = [...buckets.values()].sort((x, y) => y.w - x.w);
  const avg = (e: { w: number; r: number; g: number; b: number }) =>
    rgbToHex(e.r / e.w, e.g / e.w, e.b / e.w);
  const accent = avg(sorted[0]);
  const accentH = rgbToHsl(...hexToRgb(accent))[0];
  const second = sorted.find((e) => {
    // circular hue distance on the 360° wheel (so 350° vs 10° reads as 20°, not 340°)
    const diff = Math.abs(rgbToHsl(...hexToRgb(avg(e)))[0] - accentH);
    return Math.min(diff, 360 - diff) > 40;
  });
  return { accent, accent2: second ? avg(second) : accent };
}

export function buildPalette(rawAccent: string, rawAccent2: string, mode: Mode): Palette {
  const accent = clampForMode(rawAccent, mode);
  const accent2 = clampForMode(rawAccent2, mode);
  const [r, g, b] = hexToRgb(accent);
  return { accent, accent2, ambient: `rgb(${r} ${g} ${b} / 0.18)`, onAccent: onAccent(accent) };
}

export function extractPalette(img: HTMLImageElement, mode: Mode): Palette | null {
  const size = 32;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  try {
    ctx.drawImage(img, 0, 0, size, size);
    const q = quantizeDominant(ctx.getImageData(0, 0, size, size).data);
    return q ? buildPalette(q.accent, q.accent2, mode) : null;
  } catch {
    return null;
  }
}
