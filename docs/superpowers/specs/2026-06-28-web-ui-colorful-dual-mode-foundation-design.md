# audio-dl Web UI — Colorful, Dual-Mode Foundation (design spec)

**Status:** draft
**Date:** 2026-06-28
**Owner:** Joe Terrell
**Target release:** v2.2.0

## Purpose

Make the `audio-dl` web UI feel polished, modern, and genuinely colorful,
working in **both light and dark mode**, while fixing the album-art color
system that is currently the app's signature feature *and* currently broken.

This is **Spec #1 of a four-part program** (see [Roadmap](#roadmap)). It
combines two workstreams that are too coupled to ship separately:

1. **Theme foundation** — light / dark / system, with a token architecture
   and a no-flash boot path.
2. **"Now Playing" v2** — the hybrid colorful identity: a designed
   indigo/violet base that the current track's album-art color layers on
   top of, fixed and made contrast-safe in both modes.

## Background — why combine them

The "colorful" pillar of the goal is not a from-scratch ask: the
album-art-driven theming already exists. An audit (2026-06-28) found it
**broken in four compounding ways at once**:

1. **Colors freeze after the first track.** `useVibrant`'s effect depends on
   `[ref]` (stable object identity), so extraction runs **once per mount** —
   every track after the first wears the first track's palette.
   ([use-vibrant.ts:36](../../../web/src/hooks/use-vibrant.ts))
2. **Hard color cut.** `setProperty` is synchronous with no transition, so the
   whole UI strobes on every (working) track change.
3. **Stale palette bleed.** Vars are never reset, so no-art tracks and the
   idle stage inherit the previous track's colors.
4. **No contrast guard.** `--accent` is `palette.Vibrant.hex` verbatim; a dark
   or pale cover yields illegible button text — a real WCAG failure, since
   `button.tsx` hardcodes `text-white` on `bg-[var(--accent)]`.

You cannot do "colorful in light *and* dark" without dual-mode tokens and a
shared contrast token, and you cannot fix the four bugs without rewriting the
extraction path — so theme + color are one spec.

### Measured bundle baseline (production build, this branch)

| Chunk | gzipped | Note |
|---|---|---|
| `node-vibrant` chunk (`assets/node-*.js`) | **136 KB** | loaded the moment a download starts, to extract one color |
| main entry (`assets/index-*.js`) | 156 KB | React 19 + TanStack Router/Query + Radix + app |
| CSS | 7 KB | fine |

Because this spec rewrites the extraction path anyway, it **replaces
`node-vibrant` with a ~2 KB in-house extractor**, deleting the single fattest
chunk in the app. The "colorful" and "blazingly fast" goals are served by the
same edit.

## Decisions (locked with owner, 2026-06-28)

- **Colorful philosophy: Hybrid.** A designed brand base drives chrome, empty,
  idle, and no-art states; the playing track's album-art color layers on top.
  Always colorful; extra-magical when there's art.
- **Brand base palette: Indigo · Violet** (`#818cf8` / `#c084fc` in dark,
  `#6366f1` / `#9333ea` in light) — keeps today's identity, lowest-risk.
- **node-vibrant: replace** with an in-house canvas extractor.
- **First spec scope:** theme foundation + Now Playing v2 together (this doc).

## Goals

- Light / dark / **system** theme, user-toggleable, persisted, with **no
  flash of the wrong theme** on load.
- A dual-mode token architecture: every surface, text, and border token has a
  correct value in both modes.
- The hybrid color engine: brand base by default, album-art accent when a
  track plays, **contrast-clamped** so text stays legible in both modes.
- All four color bugs fixed as a unit (re-extract, crossfade, reset, clamp).
- `node-vibrant` removed; net bundle reduction.
- Existing test suite stays green; new logic is unit-tested.

## Non-goals (deferred to later specs)

- Route-level code splitting / main-entry trimming → **Spec #4 (perf)**.
- Inter font subsetting / load strategy → **Spec #4**.
- Motion polish beyond the color crossfade — stage/route/menu/dialog/album
  transitions → **Spec #3 (polish & motion)**.
- Responsive / phone-layout fixes (library grid, input bar, safe-area) →
  **Spec #3**.
- The broader keyboard-focus cluster → **Spec #3** (this spec only touches the
  `button` focus-ring color, since it edits `button.tsx` anyway).
- Unhappy-path correctness (silent SSE drop, swallowed cancel errors,
  fire-and-forget library re-downloads, batch-URL rendering) → **correctness
  track**, run in parallel.
- More than the two locked palettes; no per-user custom brand color.

---

## Architecture

### 1 · Token model (light / dark / system)

`web/src/styles/tokens.css` is restructured from one dark `:root` into:

- `:root` — **structural, mode-invariant** tokens: radii, font, `@property`
  registrations, and the **brand** duo + status colors *with* light overrides
  below.
- `:root, [data-theme="dark"]` — dark surface/text/border values (today's
  values) + dark brand duo + dark status colors.
- `[data-theme="light"]` — light surface/text/border values + light brand duo
  + light status colors.

`data-theme` on `<html>` is always a concrete `"light"` or `"dark"` after
boot. `"system"` is a stored *preference* that resolves to one of those via
`matchMedia('(prefers-color-scheme: dark)')` and re-resolves live on OS change.

Proposed light values (tuned in implementation):

| Token | Dark (current) | Light |
|---|---|---|
| `--bg` | `#08080a` | `#fbfbfd` |
| `--surface` | `rgb(255 255 255 / .04)` | `rgb(0 0 0 / .04)` |
| `--surface-strong` | `rgb(255 255 255 / .08)` | `rgb(0 0 0 / .07)` |
| `--border` | `rgb(255 255 255 / .07)` | `rgb(0 0 0 / .10)` |
| `--text` | `#f5f5f7` | `#18181b` |
| `--text-2` | `#a1a1aa` | `#52525b` |
| `--text-3` | `#71717a` | `#71717a` |
| `--brand` / `--brand-2` | `#818cf8` / `#c084fc` | `#6366f1` / `#9333ea` |

Status colors (`--ok/--err/--warn/--info` + `-bg`) get light-mode foreground
overrides (e.g. `--ok: #059669` in light) so the existing tints stay legible
on a near-white surface.

`color-scheme: light dark` is set so native controls, scrollbars, and form
widgets match the active theme.

### 2 · Brand base + accent tokens

The accent is no longer a hardcoded default — it **defaults to the brand
duo** and is overridden by the extractor when a track plays:

```css
:root, [data-theme="dark"] { --brand: #818cf8; --brand-2: #c084fc; }
[data-theme="light"]       { --brand: #6366f1; --brand-2: #9333ea; }

/* accent defaults to brand; extractor overrides via inline style on :root */
--accent:   var(--brand);
--accent-2: var(--brand-2);
--ambient:  /* derived from brand, per mode */;
--on-accent: #fff;  /* recomputed by extractor per luminance */
```

**Reset to base** (idle / no-art / route change) = **remove** the inline
accent overrides from `:root`. The extractor writes `--accent` etc. as inline
styles on `documentElement`; removing them reveals the stylesheet rule
`--accent: var(--brand)`, which is mode-correct. (The `@property` initial value
is only a last resort when no declaration exists anywhere — here the stylesheet
always declares the brand fallback, so `removeProperty` is the simplest correct
reset.) The `@property` transition still interpolates from the extracted color
back to the brand value.

### 3 · Crossfade via typed custom properties

Register the accent vars as typed `<color>` properties so CSS can interpolate
them:

```css
@property --accent   { syntax: '<color>'; inherits: true; initial-value: #818cf8; }
@property --accent-2 { syntax: '<color>'; inherits: true; initial-value: #c084fc; }
@property --ambient  { syntax: '<color>'; inherits: true; initial-value: rgb(129 140 248 / 0.18); }

:root { transition: --accent 480ms ease, --accent-2 480ms ease, --ambient 480ms ease; }
```

Writing the inline property on `document.documentElement` now animates. The
reduced-motion guard is **broadened** beyond toasts:

```css
@media (prefers-reduced-motion: reduce) {
  :root { transition: none !important; }
  /* existing toast guard stays */
}
```

**Graceful degradation:** if a browser lacks `@property` support, the swap is
instant (today's behavior) — still correct, just not animated. Acceptable for
a locally-launched evergreen-browser app.

### 4 · The in-house color extractor

New pure module `web/src/lib/color.ts` (fully unit-testable, no DOM beyond an
optional canvas):

1. **Downsample** the loaded `<img>` onto a small offscreen canvas
   (~32×32) via `drawImage`.
2. **Quantize** `getImageData` pixels into buckets (e.g. 4 bits/channel),
   skipping near-transparent and near-gray pixels; weight each bucket by
   `count × saturation` to prefer vibrant colors.
3. **Pick** the top bucket → accent; a distinct secondary bucket → accent-2.
   If the image is monochrome / too little data → **fall back to brand**.
4. **Contrast-clamp** each accent for the active mode:
   - Convert to HSL.
   - **Dark mode:** raise lightness to a floor (~`L ≥ 0.55`) so the accent
     reads on near-black `--bg` and as a fill.
   - **Light mode:** lower lightness to a ceiling (~`L ≤ 0.50`) and keep
     saturation up so it reads on near-white `--bg`.
   - Thresholds tuned during implementation.
5. **Compute `--on-accent`** = `#000` or `#fff` by the clamped accent's
   relative luminance (WCAG), so on-accent text always passes.

Same-origin note: thumbnails are served via the app's own `/thumbs/<id>.jpg`
proxy, so the canvas is **not tainted** and `getImageData` succeeds.
`crossOrigin="anonymous"` stays for safety.

### 5 · Color hook rewrite

`use-vibrant.ts` → rewritten (renamed `use-album-color.ts`) with signature
`useAlbumColor(src: string | null)`:

- Effect deps `[src, resolvedTheme]` → **re-extracts on track change** (bug 1)
  and re-clamps when the theme flips.
- On a real `src`: load → extract → clamp → write accent / accent-2 / ambient /
  on-accent inline on `:root` (animated by the `@property` transition; bug 2).
- On `null`/empty `src` or unmount: **reset to brand** (bug 3).
- All contrast handled by the clamp (bug 4).

### 6 · Theme application

New `web/src/hooks/use-theme.ts`:

- Reads `settings.theme` (`'system' | 'light' | 'dark'`).
- Resolves to a concrete theme (system → `matchMedia`).
- Applies `data-theme` to `<html>` in an effect; subscribes to `matchMedia`
  change while `theme === 'system'`.
- Returns `{ theme, resolved, setTheme }`.

`useSettings` (`use-settings.ts`) gains a `theme` field
(default `'system'`) in the existing `audio_dl_settings` localStorage key and a
`setTheme` setter, following its current `read/refresh/notify` pattern.

New `web/src/components/theme-toggle.tsx`: a compact 3-way segmented control
(**System / Light / Dark**) mounted in the `__root` header next to the nav.

### 7 · No-flash boot

`web/index.html` gains an **inline, render-blocking** script before the module
script, plus a tiny critical inline style, so the correct background paints
before any CSS or JS module loads:

```html
<script>
  (function () {
    try {
      var s = JSON.parse(localStorage.getItem('audio_dl_settings') || '{}');
      var t = s.theme || 'system';
      if (t === 'system') t = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', t);
    } catch (e) { document.documentElement.setAttribute('data-theme', 'dark'); }
  })();
</script>
```

**Contract:** the `audio_dl_settings` shape and its `theme` field are shared
between this inline script and `useSettings`. Both are documented in
`use-settings.ts`. `<meta name="color-scheme" content="light dark">` is added.

### 8 · Accent-consuming surfaces made safe

- `ui/button.tsx`: default variant `text-[var(--on-accent)]` instead of
  hardcoded `text-white`; give the existing `focus-visible:ring-2` a color
  (`ring-[var(--accent)]`) so the ring is visible (the one focus fix in scope).
- `stage.tsx`: progress-bar glow via `color-mix(in srgb, var(--accent) 50%,
  transparent)` for consistent weight across palettes; pass `src` to
  `useAlbumColor`.
- `album-art.tsx`: fallback gradient uses **brand** duo
  (`from-[var(--brand)]/30 to-[var(--brand-2)]/30`), not the (possibly stale)
  accent.

---

## File change map

| File | Change |
|---|---|
| `web/index.html` | no-flash script, `color-scheme` meta, critical bg style |
| `web/src/styles/tokens.css` | dual token sets, brand tokens, `@property` regs, `--on-accent`, light status |
| `web/src/styles/globals.css` | `:root` accent transition, broadened reduced-motion guard, `color-scheme` |
| `web/src/lib/color.ts` | **new** — extractor + HSL/luminance/clamp utilities (pure) |
| `web/src/hooks/use-theme.ts` | **new** — resolve + apply + matchMedia |
| `web/src/hooks/use-settings.ts` | add `theme` field + `setTheme` |
| `web/src/hooks/use-album-color.ts` | **new** (replaces `use-vibrant.ts`) — rewritten extraction |
| `web/src/hooks/use-vibrant.ts` | **deleted** |
| `web/src/components/theme-toggle.tsx` | **new** — 3-way segmented control |
| `web/src/routes/__root.tsx` | mount `ThemeToggle`; call `useTheme` |
| `web/src/components/stage.tsx` | pass `src` to `useAlbumColor`; glow via `color-mix` |
| `web/src/components/ui/button.tsx` | `--on-accent` text + visible focus ring |
| `web/src/components/album-art.tsx` | fallback uses brand duo |
| `web/package.json` | remove `node-vibrant` |
| `CLAUDE.md` | dep-boundary note: `node-vibrant` removed |

## Data flow

**Theme:** boot script sets `data-theme` → React mounts → `useTheme` reads
persisted pref, re-applies `data-theme`, subscribes to `matchMedia` → toggle
calls `setTheme` → `useSettings` persists + notifies → `useTheme` re-applies.

**Color:** `HeroStage` renders the track → `useAlbumColor(src)` → on load,
`color.ts` downsamples + quantizes + clamps (using `resolvedTheme`) → writes
`--accent/--accent-2/--ambient/--on-accent` on `:root` → `@property`
transition crossfades → progress bar, button, ambient glow, fallback art all
update. No `src` → reset to brand.

## Edge cases & error handling

- **No thumbnail / empty src** → reset to brand (no stale bleed).
- **Tainted/failed canvas read** → catch → fall back to brand; never throw into
  render.
- **Monochrome / low-data cover** → brand fallback.
- **Theme flip mid-download** → `resolvedTheme` in deps re-clamps the current
  accent for the new mode.
- **`@property` unsupported** → instant swap, still correct.
- **Reduced motion** → no accent transition; theme switch is instant anyway.

## Testing

Vitest (jsdom), all network/canvas mocked:

- `color.ts`: HSL round-trip; luminance; clamp raises L in dark / lowers in
  light; `on-accent` flips black/white at the luminance boundary; quantizer
  picks the dominant vibrant bucket; monochrome → brand fallback.
- `use-theme.ts`: system resolves via mocked `matchMedia`; live OS change
  updates `data-theme`; explicit light/dark override; persistence round-trip.
- No-flash script logic (extract to a tiny pure fn imported by both the inline
  script build and the test, or test the equivalent resolver).
- `use-album-color.ts`: re-extracts when `src` changes; resets to brand on
  `null`; writes the four vars.
- `button.tsx`: default variant renders `--on-accent` text and a colored ring.
- Existing suite (all `*.test.tsx`) stays green; update tests referencing
  `useVibrant`.

## Performance impact

- **−136 KB gzip** on the download-start path (node-vibrant removed),
  **+~2 KB** extractor + theme code → large net reduction.
- No-flash script removes the wrong-theme paint and the white flash.
- Main entry untouched here (route-splitting/font work is Spec #4).

## Risks & assumptions

- **Extractor quality** is simpler than node-vibrant's; the clamp makes output
  reliable even when the dominant color is imperfect. Acceptable trade for
  −136 KB and inline contrast control.
- **`@property`** is evergreen (Chrome 85+, Safari 16.4+, Firefox 128+);
  app is launched in the user's default browser. Degrades gracefully.
- **Same-origin thumbs** keep the canvas untainted — confirmed by the
  `/thumbs/<id>.jpg` proxy.

## Roadmap (the wider program)

| # | Spec | Status |
|---|---|---|
| **1** | **Colorful, dual-mode foundation** (this doc) | draft |
| 2 | *folded into #1* (Now Playing v2) | — |
| 3 | Polish & motion — transitions, focus cluster, responsive, token-drift | future |
| 4 | Blazingly fast — route splitting, font strategy, measured budget | future |
| — | Correctness track — SSE drop, cancel errors, library re-download, batch URLs | parallel |

## Open questions

None blocking. Light-mode token values and clamp thresholds are tuned during
implementation against real album art.
