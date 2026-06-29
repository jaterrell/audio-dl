# Colorful, Dual-Mode Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the audio-dl web UI light/dark/system theming and a fixed, contrast-safe hybrid album-art color identity, and delete the 136 KB `node-vibrant` dependency.

**Architecture:** A dual token set in `tokens.css` driven by `data-theme` on `<html>`, set pre-paint by an inline boot script and managed by a `useTheme` hook over the existing `useSettings` store. A new pure `lib/color.ts` extracts and contrast-clamps the dominant album-art color onto registered `@property` accent vars (which crossfade); a brand indigo/violet base shows when nothing is playing.

**Tech Stack:** React 19, TanStack Router/Query, Tailwind v4, Radix, Vitest + Testing Library, Vite.

**Spec:** [docs/superpowers/specs/2026-06-28-web-ui-colorful-dual-mode-foundation-design.md](../specs/2026-06-28-web-ui-colorful-dual-mode-foundation-design.md)

**Conventions for every task**
- Work inside `web/`. Run tests with `npx vitest run <path>` (or `npm test` for the full suite). Build with `npm run build`.
- TDD: write the failing test, watch it fail, implement minimally, watch it pass, commit.
- Commit messages: `feat(web): …` / `refactor(web): …` / `test(web): …`.
- Don't chase pre-existing Biome lint errors (CI gates `npm test` + `npm run build`, not Biome).

---

## File map

| File | Responsibility |
|---|---|
| `web/src/lib/color.ts` | **new** — pure color math + dominant-color extraction + contrast clamp |
| `web/src/lib/theme.ts` | **new** — pure theme types + `resolveTheme` + `applyTheme` |
| `web/src/hooks/use-settings.ts` | add `theme` field + `setTheme` |
| `web/src/hooks/use-theme.ts` | **new** — `useTheme` (apply + matchMedia) + `useResolvedTheme` (read data-theme) |
| `web/src/hooks/use-album-color.ts` | **new** — replaces `use-vibrant.ts`; extract on src change, reset on no-art |
| `web/src/hooks/use-vibrant.ts` | **deleted** |
| `web/src/components/theme-toggle.tsx` | **new** — 3-way segmented control |
| `web/src/styles/tokens.css` | dual token sets, brand duo, `@property` regs, `--on-accent`, light status |
| `web/src/styles/globals.css` | `:root` accent transition, broadened reduced-motion guard, `color-scheme` |
| `web/index.html` | no-flash boot script + `color-scheme` meta |
| `web/src/routes/__root.tsx` | mount `ThemeToggle`, call `useTheme` |
| `web/src/components/stage.tsx` | use `useAlbumColor`; `color-mix` glow; drop hidden extraction img |
| `web/src/components/album-art.tsx` | fallback uses brand duo |
| `web/src/components/ui/button.tsx` | `--on-accent` text + visible focus ring |
| `web/package.json` | remove `node-vibrant` |

---

## Task 1: Color math primitives (`lib/color.ts`)

**Files:**
- Create: `web/src/lib/color.ts`
- Test: `web/src/lib/color.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { hexToRgb, rgbToHex, rgbToHsl, hslToRgb, relativeLuminance, onAccent } from "./color";

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
  it("onAccent picks black on light colors, white on dark colors", () => {
    expect(onAccent("#ffffff")).toBe("#000000");
    expect(onAccent("#10182a")).toBe("#ffffff");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/color.test.ts`
Expected: FAIL — `Failed to resolve import "./color"`.

- [ ] **Step 3: Write minimal implementation**

```ts
export type Mode = "light" | "dark";

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
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  let h = 0, s = 0;
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
  const hue = ((h % 360) + 360) % 360 / 360;
  if (s === 0) { const v = l * 255; return [v, v, v]; }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const ch = (t: number) => {
    t = (t % 1 + 1) % 1;
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
  return relativeLuminance(hex) > 0.4 ? "#000000" : "#ffffff";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/color.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/color.ts web/src/lib/color.test.ts
git commit -m "feat(web): color math primitives for theming"
```

---

## Task 2: Contrast clamp (`clampForMode`)

**Files:**
- Modify: `web/src/lib/color.ts`
- Test: `web/src/lib/color.test.ts`

- [ ] **Step 1: Write the failing test** (append to `color.test.ts`)

```ts
import { clampForMode } from "./color";

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/color.test.ts`
Expected: FAIL — `clampForMode is not a function`.

- [ ] **Step 3: Write minimal implementation** (append to `color.ts`)

```ts
export function clampForMode(hex: string, mode: Mode): string {
  let [h, s, l] = rgbToHsl(...hexToRgb(hex));
  if (mode === "dark") {
    l = Math.min(Math.max(l, 0.58), 0.82);
    if (s < 0.35) s = 0.5;
  } else {
    l = Math.min(Math.max(l, 0.3), 0.48);
    if (s < 0.45) s = 0.6;
  }
  return rgbToHex(...hslToRgb(h, s, l));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/color.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/color.ts web/src/lib/color.test.ts
git commit -m "feat(web): per-mode contrast clamp for accent colors"
```

---

## Task 3: Dominant-color quantizer + palette builder

**Files:**
- Modify: `web/src/lib/color.ts`
- Test: `web/src/lib/color.test.ts`

- [ ] **Step 1: Write the failing test** (append)

```ts
import { quantizeDominant, buildPalette } from "./color";

function fill(rgb: [number, number, number], count: number): Uint8ClampedArray {
  const px = new Uint8ClampedArray(count * 4);
  for (let i = 0; i < count; i++) {
    px[i * 4] = rgb[0]; px[i * 4 + 1] = rgb[1]; px[i * 4 + 2] = rgb[2]; px[i * 4 + 3] = 255;
  }
  return px;
}

describe("quantizeDominant", () => {
  it("returns the dominant vivid color", () => {
    const q = quantizeDominant(fill([255, 0, 255], 64));
    expect(q).not.toBeNull();
    const [h] = rgbToHsl(...hexToRgb(q!.accent));
    expect(Math.round(h)).toBe(300); // magenta
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
    expect(p.onAccent).toBe("#ffffff");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/color.test.ts`
Expected: FAIL — `quantizeDominant is not a function`.

- [ ] **Step 3: Write minimal implementation** (append)

```ts
export interface Palette { accent: string; accent2: string; ambient: string; onAccent: string; }

export function quantizeDominant(pixels: Uint8ClampedArray): { accent: string; accent2: string } | null {
  const buckets = new Map<number, { w: number; r: number; g: number; b: number }>();
  let vivid = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    if (pixels[i + 3] < 128) continue;
    const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2];
    const s = rgbToHsl(r, g, b)[1];
    if (s < 0.15) continue;
    vivid += s;
    const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
    const e = buckets.get(key);
    if (e) { e.w += s; e.r += r * s; e.g += g * s; e.b += b * s; }
    else buckets.set(key, { w: s, r: r * s, g: g * s, b: b * s });
  }
  if (vivid < 1 || buckets.size === 0) return null;
  const sorted = [...buckets.values()].sort((x, y) => y.w - x.w);
  const avg = (e: { w: number; r: number; g: number; b: number }) => rgbToHex(e.r / e.w, e.g / e.w, e.b / e.w);
  const accent = avg(sorted[0]);
  const accentH = rgbToHsl(...hexToRgb(accent))[0];
  const second = sorted.find((e) => Math.abs(rgbToHsl(...hexToRgb(avg(e)))[0] - accentH) > 40);
  return { accent, accent2: second ? avg(second) : accent };
}

export function buildPalette(rawAccent: string, rawAccent2: string, mode: Mode): Palette {
  const accent = clampForMode(rawAccent, mode);
  const accent2 = clampForMode(rawAccent2, mode);
  const [r, g, b] = hexToRgb(accent);
  return { accent, accent2, ambient: `rgb(${r} ${g} ${b} / 0.18)`, onAccent: onAccent(accent) };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/color.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/color.ts web/src/lib/color.test.ts
git commit -m "feat(web): dominant-color quantizer and palette builder"
```

---

## Task 4: Canvas extraction (`extractPalette`)

**Files:**
- Modify: `web/src/lib/color.ts`
- Test: `web/src/lib/color.test.ts`

- [ ] **Step 1: Write the failing test** (append)

```ts
import { extractPalette } from "./color";

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
```

Add `import { vi } from "vitest";` to the top of the test file if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/color.test.ts`
Expected: FAIL — `extractPalette is not a function`.

- [ ] **Step 3: Write minimal implementation** (append)

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/color.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/color.ts web/src/lib/color.test.ts
git commit -m "feat(web): canvas-based palette extraction"
```

---

## Task 5: Theme resolver (`lib/theme.ts`)

**Files:**
- Create: `web/src/lib/theme.ts`
- Test: `web/src/lib/theme.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, afterEach } from "vitest";
import { resolveTheme, applyTheme } from "./theme";

afterEach(() => document.documentElement.removeAttribute("data-theme"));

describe("resolveTheme", () => {
  it("maps system to dark/light by prefersDark", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
  it("returns explicit preferences unchanged", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("applyTheme", () => {
  it("sets data-theme on the root element", () => {
    applyTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/theme.test.ts`
Expected: FAIL — `Failed to resolve import "./theme"`.

- [ ] **Step 3: Write minimal implementation**

```ts
export type Mode = "light" | "dark";
export type ThemePref = "system" | "light" | "dark";

export function resolveTheme(pref: ThemePref, prefersDark: boolean): Mode {
  if (pref === "system") return prefersDark ? "dark" : "light";
  return pref;
}

export function applyTheme(mode: Mode): void {
  document.documentElement.setAttribute("data-theme", mode);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/theme.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/theme.ts web/src/lib/theme.test.ts
git commit -m "feat(web): pure theme resolver"
```

---

## Task 6: `useSettings` gains `theme`

**Files:**
- Modify: `web/src/hooks/use-settings.ts`
- Test: `web/src/hooks/use-settings.test.tsx`

- [ ] **Step 1: Write the failing test** (append to `use-settings.test.tsx`)

```ts
import { act } from "@testing-library/react";

describe("useSettings theme", () => {
  it("defaults theme to system", () => {
    const { result } = renderHook(() => useSettings());
    expect(result.current.settings.theme).toBe("system");
  });
  it("persists and re-reads theme", () => {
    const { result } = renderHook(() => useSettings());
    act(() => result.current.setTheme("light"));
    expect(result.current.settings.theme).toBe("light");
    expect(JSON.parse(localStorage.getItem("audio_dl_settings")!).theme).toBe("light");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/hooks/use-settings.test.tsx`
Expected: FAIL — `result.current.setTheme is not a function`.

- [ ] **Step 3: Write minimal implementation**

Edit `use-settings.ts`:

```ts
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
function subscribe(cb: () => void) { listeners.add(cb); return () => listeners.delete(cb); }
function notify() { for (const cb of listeners) cb(); }

let cached: StoredSettings | null = null;
function getSnapshot() {
  if (cached === null) cached = read();
  return cached;
}
function refresh() { cached = read(); }

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/hooks/use-settings.test.tsx`
Expected: PASS (all 5 — 3 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/use-settings.ts web/src/hooks/use-settings.test.tsx
git commit -m "feat(web): persist theme preference in useSettings"
```

---

## Task 7: `useTheme` + `useResolvedTheme` hooks

**Files:**
- Create: `web/src/hooks/use-theme.ts`
- Test: `web/src/hooks/use-theme.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTheme, useResolvedTheme } from "./use-theme";

function mockMatchMedia(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((q: string) => ({
    matches, media: q, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  }));
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("useTheme", () => {
  it("applies dark when system + prefers dark", () => {
    mockMatchMedia(true);
    renderHook(() => useTheme());
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
  it("applies the chosen theme after setTheme", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("light"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});

describe("useResolvedTheme", () => {
  it("reflects the current data-theme attribute", () => {
    document.documentElement.setAttribute("data-theme", "light");
    const { result } = renderHook(() => useResolvedTheme());
    expect(result.current).toBe("light");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/hooks/use-theme.test.tsx`
Expected: FAIL — `Failed to resolve import "./use-theme"`.

- [ ] **Step 3: Write minimal implementation**

```ts
import { useEffect, useSyncExternalStore } from "react";
import { useSettings } from "./use-settings";
import { resolveTheme, applyTheme, type Mode } from "@/lib/theme";

export function useTheme() {
  const { settings, setTheme } = useSettings();
  const pref = settings.theme;
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(resolveTheme(pref, mq.matches));
    update();
    if (pref === "system") {
      mq.addEventListener("change", update);
      return () => mq.removeEventListener("change", update);
    }
  }, [pref]);
  return { theme: pref, setTheme };
}

function getResolved(): Mode {
  return (document.documentElement.getAttribute("data-theme") as Mode) || "dark";
}

export function useResolvedTheme(): Mode {
  return useSyncExternalStore(
    (cb) => {
      const obs = new MutationObserver(cb);
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      return () => obs.disconnect();
    },
    getResolved,
    () => "dark",
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/hooks/use-theme.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/use-theme.ts web/src/hooks/use-theme.test.tsx
git commit -m "feat(web): useTheme + useResolvedTheme hooks"
```

---

## Task 8: `ThemeToggle` component

**Files:**
- Create: `web/src/components/theme-toggle.tsx`
- Test: `web/src/components/theme-toggle.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeToggle } from "./theme-toggle";

beforeEach(() => localStorage.clear());

describe("ThemeToggle", () => {
  it("renders three options with system checked by default", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Light" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Dark" })).toBeInTheDocument();
  });
  it("selects Light on click and persists it", async () => {
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("radio", { name: "Light" }));
    expect(screen.getByRole("radio", { name: "Light" })).toHaveAttribute("aria-checked", "true");
    expect(JSON.parse(localStorage.getItem("audio_dl_settings")!).theme).toBe("light");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/theme-toggle.test.tsx`
Expected: FAIL — `Failed to resolve import "./theme-toggle"`.

- [ ] **Step 3: Write minimal implementation**

```tsx
import { useSettings } from "@/hooks/use-settings";
import type { ThemePref } from "@/lib/theme";
import { cn } from "@/lib/utils";

const OPTS: { value: ThemePref; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function ThemeToggle() {
  const { settings, setTheme } = useSettings();
  return (
    <div role="radiogroup" aria-label="Theme"
      className="inline-flex gap-0.5 rounded-[var(--radius-md)] border border-[var(--border)] p-0.5">
      {OPTS.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={settings.theme === o.value}
          onClick={() => setTheme(o.value)}
          className={cn(
            "rounded-[var(--radius-sm)] px-2.5 py-1 text-xs cursor-pointer transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
            settings.theme === o.value
              ? "bg-[var(--surface-strong)] text-[var(--text)]"
              : "text-[var(--text-2)] hover:text-[var(--text)]",
          )}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/theme-toggle.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/theme-toggle.tsx web/src/components/theme-toggle.test.tsx
git commit -m "feat(web): theme toggle segmented control"
```

---

## Task 9: Token restructure — dual sets + brand + `@property` (`tokens.css`)

**Files:**
- Modify: `web/src/styles/tokens.css`

This task is CSS-only; jsdom can't assert the cascade, so verification is **build success + full test suite green + a manual visual check**. No new unit test.

- [ ] **Step 1: Replace `web/src/styles/tokens.css` with:**

```css
:root {
  /* radii */
  --radius-lg: 14px;
  --radius-md: 10px;
  --radius-sm: 6px;

  /* registered so accent swaps can crossfade */
}

@property --accent   { syntax: "<color>"; inherits: true; initial-value: #818cf8; }
@property --accent-2 { syntax: "<color>"; inherits: true; initial-value: #c084fc; }
@property --ambient  { syntax: "<color>"; inherits: true; initial-value: rgb(129 140 248 / 0.18); }

:root,
[data-theme="dark"] {
  --bg: #08080a;
  --surface: rgb(255 255 255 / 0.04);
  --surface-strong: rgb(255 255 255 / 0.08);
  --border: rgb(255 255 255 / 0.07);
  --text: #f5f5f7;
  --text-2: #a1a1aa;
  --text-3: #71717a;

  --brand: #818cf8;
  --brand-2: #c084fc;

  /* accent defaults to brand; useAlbumColor overrides inline on :root while playing */
  --accent: var(--brand);
  --accent-2: var(--brand-2);
  --ambient: rgb(129 140 248 / 0.18);
  --on-accent: #ffffff;

  --ok: #34d399;   --ok-bg: rgb(52 211 153 / 0.14);
  --err: #f87171;  --err-bg: rgb(248 113 113 / 0.14);
  --warn: #fbbf24; --warn-bg: rgb(251 191 36 / 0.14);
  --info: #60a5fa; --info-bg: rgb(96 165 250 / 0.14);
}

[data-theme="light"] {
  --bg: #fbfbfd;
  --surface: rgb(0 0 0 / 0.04);
  --surface-strong: rgb(0 0 0 / 0.07);
  --border: rgb(0 0 0 / 0.10);
  --text: #18181b;
  --text-2: #52525b;
  --text-3: #71717a;

  --brand: #6366f1;
  --brand-2: #9333ea;

  --accent: var(--brand);
  --accent-2: var(--brand-2);
  --ambient: rgb(99 102 241 / 0.16);
  --on-accent: #ffffff;

  --ok: #059669;   --ok-bg: rgb(5 150 105 / 0.12);
  --err: #dc2626;  --err-bg: rgb(220 38 38 / 0.12);
  --warn: #d97706; --warn-bg: rgb(217 119 6 / 0.12);
  --info: #2563eb; --info-bg: rgb(37 99 235 / 0.12);
}
```

- [ ] **Step 2: Verify build + tests**

Run: `npm run build && npm test`
Expected: build succeeds; full suite green (no behavioral change yet — accent still defaults to indigo/violet).

- [ ] **Step 3: Manual visual check**

Run `npm run dev`, open the app, and in DevTools set `document.documentElement.setAttribute('data-theme','light')`. Confirm the background flips to near-white and text stays legible. Set back to `dark`.

- [ ] **Step 4: Commit**

```bash
git add web/src/styles/tokens.css
git commit -m "feat(web): dual light/dark token sets with brand base and registered accent vars"
```

---

## Task 10: Accent crossfade + reduced-motion + color-scheme (`globals.css`)

**Files:**
- Modify: `web/src/styles/globals.css`

CSS-only; verified by build + suite green + manual check.

- [ ] **Step 1: Add to `web/src/styles/globals.css`**

After the `html, body, #root { … }` block, add:

```css
:root {
  color-scheme: light dark;
  transition: --accent 480ms ease, --accent-2 480ms ease, --ambient 480ms ease;
}
```

And extend the existing reduced-motion block so it also disables the accent transition:

```css
@media (prefers-reduced-motion: reduce) {
  :root { transition: none !important; }
  .toast[data-state], .toast[data-swipe] { animation: none !important; transition: none !important; }
}
```

(Replace the existing `@media (prefers-reduced-motion: reduce)` block with the one above.)

- [ ] **Step 2: Verify build + tests**

Run: `npm run build && npm test`
Expected: build succeeds; suite green.

- [ ] **Step 3: Manual visual check**

In `npm run dev`, run in DevTools:
`document.documentElement.style.setProperty('--accent', '#22d3ee')`
Confirm accent-driven elements (the primary button, progress bar) **animate** to the new color over ~0.5s rather than snapping.

- [ ] **Step 4: Commit**

```bash
git add web/src/styles/globals.css
git commit -m "feat(web): crossfade accent vars and broaden reduced-motion guard"
```

---

## Task 11: No-flash boot script (`index.html`)

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: Replace `web/index.html` with:**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="light dark" />
    <title>audio-dl</title>
    <script>
      // Set data-theme before first paint so the correct background renders
      // with no flash. Shares the `audio_dl_settings` key + `theme` field with
      // web/src/hooks/use-settings.ts — keep both in sync.
      (function () {
        try {
          var s = JSON.parse(localStorage.getItem("audio_dl_settings") || "{}");
          var t = s.theme || "system";
          if (t === "system") {
            t = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
          }
          document.documentElement.setAttribute("data-theme", t);
        } catch (e) {
          document.documentElement.setAttribute("data-theme", "dark");
        }
      })();
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: Verify build + manual check**

Run: `npm run build` (expect success), then `npm run dev`. Set the toggle to Light, hard-refresh, and confirm there is **no dark flash** before the page renders light. Repeat for Dark.

- [ ] **Step 3: Commit**

```bash
git add web/index.html
git commit -m "feat(web): no-flash theme boot script"
```

---

## Task 12: Mount toggle + apply theme in `__root.tsx`

**Files:**
- Modify: `web/src/routes/__root.tsx`

- [ ] **Step 1: Replace the body of `__root.tsx` with:**

```tsx
import { createRootRoute, Outlet, Link } from "@tanstack/react-router";
import { Toaster } from "@/components/toaster";
import { ThemeToggle } from "@/components/theme-toggle";
import { useTheme } from "@/hooks/use-theme";

export const Route = createRootRoute({
  component: AppShell,
});

function AppShell() {
  useTheme();
  return (
    <div className="min-h-screen">
      <header className="flex justify-between items-center px-7 py-5">
        <div className="flex items-center gap-3 font-semibold">audio-dl</div>
        <div className="flex items-center gap-4">
          <nav className="flex gap-1">
            <Link
              to="/"
              className="px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
              activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
            >
              Now
            </Link>
            <Link
              to="/library"
              className="px-3 py-1.5 rounded-md text-sm text-[var(--text-2)]"
              activeProps={{ className: "bg-[var(--surface)] text-[var(--text)]" }}
            >
              Library
            </Link>
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main>
        <Outlet />
      </main>
      <Toaster />
    </div>
  );
}
```

- [ ] **Step 2: Verify build + tests**

Run: `npm run build && npm test`
Expected: build succeeds; suite green. (If any route/render test calls `window.matchMedia`, add the `mockMatchMedia` helper from Task 7 to that test's setup — `useTheme` now runs in the shell.)

- [ ] **Step 3: Manual check**

`npm run dev`: the toggle appears top-right; switching it flips the whole app between light and dark.

- [ ] **Step 4: Commit**

```bash
git add web/src/routes/__root.tsx
git commit -m "feat(web): mount theme toggle and apply theme in app shell"
```

---

## Task 13: `useAlbumColor` hook (replaces `useVibrant`)

**Files:**
- Create: `web/src/hooks/use-album-color.ts`
- Test: `web/src/hooks/use-album-color.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@/lib/color", () => ({
  extractPalette: vi.fn(() => ({
    accent: "#112233", accent2: "#445566",
    ambient: "rgb(17 34 51 / 0.18)", onAccent: "#ffffff",
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/hooks/use-album-color.test.tsx`
Expected: FAIL — `Failed to resolve import "./use-album-color"`.

- [ ] **Step 3: Write minimal implementation**

```ts
import { useEffect } from "react";
import { extractPalette } from "@/lib/color";
import type { Mode } from "@/lib/theme";

const VARS = ["--accent", "--accent-2", "--ambient", "--on-accent"] as const;

export function useAlbumColor(src: string | null, mode: Mode): void {
  useEffect(() => {
    const root = document.documentElement;
    const reset = () => { for (const v of VARS) root.style.removeProperty(v); };

    if (!src) { reset(); return; }

    let cancelled = false;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.referrerPolicy = "no-referrer";

    const apply = () => {
      if (cancelled) return;
      const p = extractPalette(img, mode);
      if (!p) { reset(); return; }
      root.style.setProperty("--accent", p.accent);
      root.style.setProperty("--accent-2", p.accent2);
      root.style.setProperty("--ambient", p.ambient);
      root.style.setProperty("--on-accent", p.onAccent);
    };

    img.onload = apply;
    img.src = src;
    if (img.complete && img.naturalWidth) apply();

    return () => { cancelled = true; img.onload = null; };
  }, [src, mode]);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/hooks/use-album-color.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/use-album-color.ts web/src/hooks/use-album-color.test.tsx
git commit -m "feat(web): useAlbumColor — per-track extraction with brand reset"
```

---

## Task 14: Wire `useAlbumColor` into `stage.tsx`

**Files:**
- Modify: `web/src/components/stage.tsx`
- Test: `web/src/components/stage.test.tsx` (update if it asserts the removed hidden img)

- [ ] **Step 1: Replace `stage.tsx` with:**

```tsx
import { AlbumArt } from "./album-art";
import { CancelDialog } from "./cancel-dialog";
import { useAlbumColor } from "@/hooks/use-album-color";
import { useResolvedTheme } from "@/hooks/use-theme";
import type { JobSnapshot } from "@/lib/types";

interface HeroStageProps {
  snapshot: JobSnapshot;
  activeCount: number;
}

export function HeroStage({ snapshot, activeCount }: HeroStageProps) {
  const u = snapshot.urls[0];
  const mode = useResolvedTheme();
  useAlbumColor(u?.thumb_id ? `/thumbs/${u.thumb_id}.jpg` : null, mode);

  if (!u) return null;
  const title = u.title ?? u.url;
  const artist = u.uploader ?? "";

  return (
    <div className="grid place-items-center px-8 pt-7 pb-4">
      <div className="relative group">
        <AlbumArt
          thumbId={u.thumb_id}
          size={240}
          className="!shadow-[0_24px_64px_rgba(0,0,0,0.55),0_0_100px_var(--ambient)]"
        />
        <div className="absolute top-2 right-2">
          <CancelDialog jobId={snapshot.job_id} />
        </div>
      </div>
      <div className="text-center mt-6">
        <div className="text-[11px] uppercase tracking-[0.06em] font-bold text-[var(--accent)] mb-2">
          Downloading · 1 of {activeCount}
        </div>
        <h2 className="text-[26px] font-bold tracking-[-0.025em] leading-tight mb-1">{title}</h2>
        {artist && <p className="text-[var(--text-2)] text-[15px] mb-6">{artist}</p>}
        <div className="w-full max-w-[460px] mx-auto">
          <div className="h-1 bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-[width] duration-200"
              style={{
                width: `${u.progress_percent}%`,
                background: "linear-gradient(90deg, var(--accent), var(--accent-2))",
                boxShadow: "0 0 10px color-mix(in srgb, var(--accent) 50%, transparent)",
              }}
            />
          </div>
          <div className="flex justify-between text-xs text-[var(--text-3)] mt-2">
            <span>{u.speed ?? ""}</span>
            <span>{u.eta ?? ""}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

Notes: the hook now owns its own extraction image, so the hidden `<img>`, `useRef`, and `useVibrant` import are removed.

- [ ] **Step 2: Run the existing stage test; update if needed**

Run: `npx vitest run src/components/stage.test.tsx`
If it fails because it queried the removed hidden extraction `<img>` (e.g. selecting a second image with empty `alt`), update that assertion to target the `AlbumArt` element instead. The real `useAlbumColor` runs here unmocked: in jsdom `canvas.getContext("2d")` returns `null`, so `extractPalette` returns `null` and the hook no-ops safely — no extra mocking required.
Expected after edits: PASS.

- [ ] **Step 3: Run build + suite**

Run: `npm run build && npm test`
Expected: build succeeds; suite green.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/stage.tsx web/src/components/stage.test.tsx
git commit -m "refactor(web): drive HeroStage color via useAlbumColor"
```

---

## Task 15: Brand-duo album-art fallback (`album-art.tsx`)

**Files:**
- Modify: `web/src/components/album-art.tsx`
- Test: `web/src/components/album-art.test.tsx` (update if it asserts the old accent classes)

- [ ] **Step 1: Edit the fallback `<div>` className**

In `album-art.tsx`, change the fallback gradient from accent to brand:

```tsx
className={cn(
  "rounded-[var(--radius-sm)] flex-shrink-0",
  "bg-gradient-to-br from-[var(--brand)]/30 to-[var(--brand-2)]/30",
  className
)}
```

- [ ] **Step 2: Run the album-art test; update if needed**

Run: `npx vitest run src/components/album-art.test.tsx`
If the test asserts `from-[var(--accent)]/30`, update it to `from-[var(--brand)]/30`. The fallback still renders for `thumbId == null` or on image `onError`.
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/album-art.tsx web/src/components/album-art.test.tsx
git commit -m "fix(web): album-art fallback uses brand duo, not stale accent"
```

---

## Task 16: Contrast-safe button (`ui/button.tsx`)

**Files:**
- Modify: `web/src/components/ui/button.tsx`
- Test: `web/src/components/ui/button.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { buttonVariants } from "./button";

describe("buttonVariants", () => {
  it("default variant uses on-accent text and a colored focus ring", () => {
    const cls = buttonVariants({ variant: "default" });
    expect(cls).toContain("text-[var(--on-accent)]");
    expect(cls).toContain("focus-visible:ring-[var(--accent)]");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/ui/button.test.tsx`
Expected: FAIL — assertion not met (`text-white`, no ring color).

- [ ] **Step 3: Edit `button.tsx`**

In the base string, add the ring color; in the `default` variant, swap `text-white` for `text-[var(--on-accent)]`:

```ts
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-md)] " +
    "text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 " +
    "focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] " +
    "disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-[var(--accent)] text-[var(--on-accent)] hover:opacity-90 shadow-[0_4px_16px_var(--ambient)]",
        ghost: "hover:bg-[var(--surface)] text-[var(--text-2)]",
        outline: "border border-[var(--border)] bg-transparent hover:bg-[var(--surface)] text-[var(--text)]",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-[var(--radius-sm)] px-3 text-xs",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/ui/button.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ui/button.tsx web/src/components/ui/button.test.tsx
git commit -m "fix(web): button uses on-accent text and a visible focus ring"
```

---

## Task 17: Remove `node-vibrant`

**Files:**
- Modify: `web/package.json`
- Delete: `web/src/hooks/use-vibrant.ts`, `web/src/hooks/use-vibrant.test.tsx`

- [ ] **Step 1: Confirm there are no remaining importers**

Run: `git grep -n "node-vibrant\|use-vibrant\|useVibrant" -- web/src`
Expected: only `use-vibrant.ts` and `use-vibrant.test.tsx` (both about to be deleted). If `stage.tsx` still appears, finish Task 14 first.

- [ ] **Step 2: Delete the old hook and its test**

```bash
git rm web/src/hooks/use-vibrant.ts web/src/hooks/use-vibrant.test.tsx
```

- [ ] **Step 3: Remove the dependency from `web/package.json`**

Delete the line `"node-vibrant": "^4.0.4",` from `dependencies`.

- [ ] **Step 4: Sync the lockfile and rebuild**

Run: `cd web && npm install && npm run build && npm test`
Expected: `package-lock.json` updates (node-vibrant gone); build succeeds; full suite green. Confirm the `assets/node-*.js` chunk no longer appears in `dist/assets/`.

- [ ] **Step 5: Commit**

```bash
git add web/package.json web/package-lock.json web/src/hooks/use-vibrant.ts web/src/hooks/use-vibrant.test.tsx
git commit -m "perf(web): replace node-vibrant (136 KB gz) with in-house extractor"
```

---

## Task 18: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite + build**

Run: `cd web && npm test && npm run build`
Expected: all tests green; build succeeds.

- [ ] **Step 2: Bundle check**

Run: `find web/dist/assets -name '*.js' -exec sh -c 'gzip -c "$1" | wc -c' _ {} \;`
Expected: no ~136 KB node-vibrant chunk; total shipped JS materially smaller than the 292 KB-gz baseline.

- [ ] **Step 3: Manual smoke (`npm run dev`)**

Verify, with a real download running:
- Toggle System/Light/Dark — whole app reflows; no flash on refresh.
- Start a download with album art — accent crossfades in from the cover; primary button text stays legible.
- A track with no thumbnail — accent resets to indigo/violet (no stale color).
- A dark/low-saturation cover — button text remains readable (clamp working).

- [ ] **Step 4: Done** — hand back to the finishing-a-development-branch flow.

---

## Self-review notes

- **Spec coverage:** theme system (Tasks 5–12), hybrid color engine + 4 bug fixes (re-extract T13, crossfade T10, reset T13, clamp T2/T4/T13), node-vibrant removal (T17), accent-surface safety (T14–T16). All spec sections map to tasks.
- **Refines spec §2/§5:** reset is done by **removing** the inline accent overrides (revealing the stylesheet's `--accent: var(--brand)`), not by re-assigning `var(--brand)` — simpler and equally mode-correct because the stylesheet, not the `@property` initial-value, is the fallback layer.
- **Type consistency:** `Mode` / `ThemePref` defined once in `lib/theme.ts` and imported everywhere; `Palette` defined once in `lib/color.ts`; hook signatures `useAlbumColor(src, mode)` and `useResolvedTheme(): Mode` are used consistently in `stage.tsx`.
- **Deferred (other specs):** route splitting, font strategy, broader motion/focus/responsive, correctness track — explicitly out of scope.
