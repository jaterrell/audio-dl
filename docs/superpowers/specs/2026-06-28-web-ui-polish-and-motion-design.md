# audio-dl Web UI — Polish & Motion (design spec)

**Status:** draft
**Date:** 2026-06-28
**Owner:** Joe Terrell
**Target release:** v2.3.0

## Purpose

Make the web UI feel polished and modern: add a coherent, restrained motion
layer, fix the keyboard-focus gaps that make the dark theme hard to navigate,
make the two routes usable on a phone, and clean up the token drift the audit
found. This is **Spec #3** of the UI program (see the roadmap in the
[colorful dual-mode spec](2026-06-28-web-ui-colorful-dual-mode-foundation-design.md)).
Spec #1 (theming + colorful "Now Playing" v2) is already shipped on this branch.

## Decision (locked with owner, 2026-06-28)

- **Direction: Polish & motion** chosen as the next workstream.
- **Motion character: subtle & refined.** Durations 150–260 ms, opacity + small
  translate (8–16 px), shared easing `cubic-bezier(0.16, 1, 0.3, 1)` (already
  used by the toast layer). No springs, no large movement. Every animation sits
  behind `prefers-reduced-motion: reduce`.

## Goals

- A consistent motion vocabulary applied to the high-drama moments: the
  hero/empty stage swap, album-art load-in, menu/dialog open-close, route
  change, and list-row enters.
- Visible `focus-visible` indicators on every interactive control (keyboard
  accessibility).
- Both routes usable from ~360 px wide up.
- Token-system consistency: no hardcoded overlay hexes, size-appropriate radii,
  consistent gutters.

## Non-goals

- Route-level code splitting / font strategy / perf budget → **Spec #4**.
- The correctness track (SSE drop, cancel errors, library re-download, batch
  URLs) → parallel track.
- New features or layout redesigns — this is polish on the existing structure.
- A motion library (Framer Motion etc.); CSS + Radix `data-state` is enough.

## Background

Audit (2026-06-28) findings grouped into four themes, all with file:line
references. The accent crossfade and the `button` focus ring already landed in
Spec #1; everything else below is in scope here.

---

## Architecture

No new dependencies. Motion is CSS keyframes keyed off Radix `data-state`
attributes (same technique as the existing toast animations in `globals.css`)
plus a small amount of Tailwind utility classes and one shared
`prefers-reduced-motion` guard. A `useReducedMotion` hook is added only where
JS needs to branch (the route-transition wrapper).

### A · Keyboard focus (objective; no taste)

Add `focus-visible` rings (color `--accent`, offset `--bg`) to controls that
currently suppress or omit them:

| Control | File | Fix |
|---|---|---|
| URL textarea | `components/url-input.tsx` | replace bare `outline-none` with a `focus-visible:ring-2 focus-visible:ring-[var(--accent)]` |
| Library search input | `components/library-filters.tsx` | same |
| Cancel ✕ trigger | `components/cancel-dialog.tsx` | it's `opacity-0` until hover — also reveal on `focus-visible` (`focus-visible:opacity-100`) and add a ring |
| Nav links | `routes/__root.tsx` | `focus-visible` ring on the `Link`s |
| Format picker trigger | `components/format-picker.tsx` | `focus-visible` ring |
| Dialog action buttons | `components/cancel-dialog.tsx` | ensure the AlertDialog buttons use the `Button` component (which now has a ring) or add one |

A shared utility class `focus-ring` is defined in `globals.css`
(`@utility focus-ring { … }` in Tailwind v4) to keep these DRY.

### B · Motion (subtle, reduced-motion-guarded)

| Moment | File | Treatment |
|---|---|---|
| Hero ⇄ Empty stage swap | `routes/index.tsx` | crossfade + 8 px translateY via a `data-visible` wrapper; key on `stageJob?.job_id` |
| Album-art load-in | `components/album-art.tsx` | fade from `opacity-0` to `opacity-100` on `img` `load` (200 ms) |
| Dropdown / context menu open-close | `components/ui/dropdown-menu.tsx`, `context-menu.tsx` | keyframes keyed on `[data-state="open"|"closed"]` (scale 0.96→1 + fade) |
| AlertDialog open-close | `components/ui/alert-dialog.tsx` | overlay fade; content scale 0.97→1 + fade |
| Route change (Now ⇄ Library) | `routes/__root.tsx` | wrap `<Outlet/>` so the active route fades+translates in on mount |
| Queue / also-downloading row enter | `components/queue.tsx`, `also-downloading.tsx` | row enter keyframe (fade + 6 px translateY) |

All keyframes live in `globals.css`. The existing
`@media (prefers-reduced-motion: reduce)` block is extended to disable them.

### C · Responsive

| Issue | File | Fix |
|---|---|---|
| Library grid `grid-cols-6` | `components/library-grid.tsx` | `grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))` (≈2 cols on phone, 6 on desktop) |
| Album art fixed 240 px | `components/album-art.tsx` / `stage.tsx` | hero art clamps to `min(240px, 72vw)` |
| URL input 3-col grid overflows | `components/url-input.tsx` | stack to a single column below `sm`, row layout at `sm+` |
| Also-downloading row no scroll cue | `components/also-downloading.tsx` | horizontal scroll container with `-webkit-overflow-scrolling` and edge fade |
| Safe-area insets | `components/toaster.tsx` / sticky els | add `env(safe-area-inset-*)` padding |

### D · Token-drift cleanup

| Issue | File | Fix |
|---|---|---|
| Hardcoded overlay hex (`#101013`, `#141417`) | `ui/toast.tsx`, `alert-dialog.tsx`, `dropdown-menu.tsx`, `context-menu.tsx` | introduce `--popover` / `--overlay` tokens in `tokens.css` (per mode) and use them |
| AlbumArt always `--radius-sm` | `components/album-art.tsx` | radius scales: `>=200px → --radius-lg`, `>=80px → --radius-md`, else `--radius-sm` |
| FormatPicker trigger `--surface` in `--surface` parent | `components/format-picker.tsx` | use `--surface-strong` so it reads against its container |
| Gutter drift (`mx-7` vs `px-8`) | `routes/index.tsx`, `components/url-input.tsx` | unify on one gutter token/value |

## Testing

- Focus rings: assert the relevant `focus-visible:ring-[var(--accent)]` class is
  present on each control (class-string assertions, like the `button` test).
- Motion: assert the animation-driving attribute/class is applied (e.g. the
  stage wrapper gets `data-visible`, album-art `img` toggles the fade class on
  load). Keyframe timing isn't unit-tested (jsdom has no layout); verified in
  the browser preview.
- Responsive: verified in the browser at 360 px and desktop widths (jsdom can't
  assert layout); grid class assertion where practical.
- Token tokens: `--popover`/`--overlay` resolve per mode — verified via the same
  `preview_eval` computed-style check used for Spec #1.
- Full existing suite stays green; `npm run build` clean.

## Risks

- New tokens (`--popover`, `--overlay`) must be defined in both light and dark
  blocks — easy to miss one; the preview computed-style check catches it.
- Route-transition wrapper must not break TanStack Router focus/scroll behavior;
  keep it a thin opacity/transform wrapper, not a remount.

## Implementation order

A (focus, objective) → B (motion) → C (responsive) → D (token drift). Each phase
is independently shippable and committed separately.
