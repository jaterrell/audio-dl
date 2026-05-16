# Spec — Per-theme card structural variations (v1.7)

**Status:** Design approved 2026-05-16
**Target file:** `audio_dl_ui.py` (web UI, no CLI changes)
**Predecessor:** v1.6 rich job cards ([2026-05-16-rich-job-cards-design.md](2026-05-16-rich-job-cards-design.md))
**Target release:** v1.7

## Goal

Extend the existing v1.6 per-theme override system to `.card` selectors. Today, cards inherit theme colors and typography but render structurally identical across all 10 themes. This release adds **three cluster-scoped card treatments** (vintage / editorial / modern) layered on top of the shared card CSS, giving each cluster a distinct structural identity to match the existing per-theme treatments already shipped for the frame, panel, panes, and status-bar.

Phosphor remains the reference default — its cards stay byte-identical to v1.6.

## Non-goals

- Per-theme structural overrides outside the card subsystem (already shipped in v1.6).
- New CSS custom properties — all variation expressed via selector specificity, reusing existing `var(--bg|fg|frame|accent|ok|err|warn|dim|bar)` vars.
- JS branching by theme or cluster — card-rendering JS stays cluster-agnostic.
- New SSE events, backend changes, or `UrlState` fields. Backend is untouched.
- Adding themes or moving themes between clusters. Cluster membership is fixed at the v1.6 boundary.
- Mobile / narrow-viewport refinement of per-cluster cards (re-deferred to v1.8+).
- Expandable log tail, aggregate stats, reveal-affordance tightening (re-deferred to v1.8+).

## Cluster membership

Locked at v1.6 — this spec only extends the override pattern.

| Cluster | Themes | Identity established in v1.6 |
|---|---|---|
| **default** | `phosphor` | TUI reference — no override |
| **vintage** | `amber`, `solarized`, `gruvbox` | dotted borders, letter-spacing, CRT vibe |
| **editorial** | `rose`, `moon`, `dawn` | softer panels, prose feel; dawn is light-mode |
| **modern** | `tokyo`, `atom`, `claude` | rounded, product-card framing, sans allowed |

## Per-cluster card treatments

Each cluster's CSS lives in a single block appended to `_INDEX_CSS_THEMES`, scoped with grouped selectors:

```css
[data-theme="amber"] .card,
[data-theme="solarized"] .card,
[data-theme="gruvbox"] .card { /* vintage rules */ }
```

### Default (phosphor) — no override

The shared `.card` rules in `_INDEX_CSS_BASE` are the phosphor card. No `[data-theme="phosphor"] .card { ... }` selectors. This preserves v1.6 behavior byte-identically when phosphor is active.

### Vintage cluster

| Element | Treatment | CSS approach |
|---|---|---|
| `.card` | dotted border, 0.04em letter-spacing | `border-style: dotted; letter-spacing: 0.04em;` |
| `.card-title`, `.card-meta` | uppercase | `text-transform: uppercase;` |
| `.card-thumb` | dotted border, grayscale + contrast filter on inner `img` | `.card-thumb { border-style: dotted; } .card-thumb img { filter: grayscale(0.7) contrast(1.2); }` |
| `.card-bar` | chunked/segmented bar appearance | `background-image: repeating-linear-gradient(90deg, var(--dim) 0 4px, transparent 4px 6px);` on `.card-bar > span` so the fill reads as character-cell blocks |
| `.card-log-line` | terminal `>` prefix | `.card-log-line::before { content: "> "; color: var(--dim); }` |

**Why no literal ASCII bar (`━━━░░░`):** authoring a character-rendered bar requires either JS markup branching (violates cluster-agnostic-JS principle) or CSS `content:` with `attr()` math (browsers can't compute width from a number attribute). The repeating-gradient approach gives the same visual "blocks of progress" signal without leaving CSS.

### Editorial cluster

| Element | Treatment | CSS approach |
|---|---|---|
| `.card` | border-bottom only, no full box; generous padding | `border: none; border-bottom: 1px solid var(--frame); padding: 16px 14px;` |
| `.card-title` | serif, larger | `font-family: Georgia, "Times New Roman", serif; font-size: 1.05em;` |
| `.card-meta` | italic | `font-style: italic;` |
| `.card-thumb` (dawn only) | hidden | `[data-theme="dawn"] .card { grid-template-columns: 1fr; } [data-theme="dawn"] .card-thumb { display: none; }` |
| `.card-thumb` (rose, moon) | kept at default size, softer rendering | inherit base |
| `.card-bar` | thin (3px), rounded ends | `height: 3px; border: none; border-radius: 2px; background: color-mix(in srgb, var(--frame) 60%, transparent);` |
| `.card-log-line` | italic, smaller, no truncation chevron | `font-style: italic; font-size: 0.85em;` |

**Why no prose metadata reformat ("by Geotic · 4 min 11 sec"):** the mockup showed prose. Real implementation keeps the v1.6 JS output (`"Geotic · 4:11"`) and italicizes it via CSS. Reformatting would push the format into JS with cluster awareness — drops the pure-CSS-cluster discipline for a small aesthetic gain. Italics retain the editorial signal at zero JS cost.

### Modern cluster

| Element | Treatment | CSS approach |
|---|---|---|
| `.card` | rounded 10px, vertical stack (thumb on top), wider gap | `border-radius: 10px; grid-template-columns: 1fr; grid-template-rows: auto auto; gap: 10px;` |
| `.card-thumb` | full-width on top, 100px tall, rounded 6px, position relative for overlay | `width: 100%; height: 100px; border-radius: 6px; position: relative;` |
| `.card-thumb::after` | duration overlay in top-right corner | `content: attr(data-duration); position: absolute; top: 6px; right: 6px; background: rgba(0,0,0,0.5); color: #fff; font: 600 0.7em var(--mono); padding: 2px 6px; border-radius: 3px;` — empty/hidden when `data-duration` is missing or `""` |
| `.card-meta` | uppercase small-caps label, displayed *above* title via CSS `order` | `.card-body { } .card-meta { order: -1; text-transform: uppercase; font-size: 0.7em; font-weight: 600; letter-spacing: 0.08em; color: var(--accent); }` — requires `.card-body` flex-column (already is) for `order` to apply |
| `.card-title` | inherit theme accent; consider lighter weight on tokyo/atom; sans allowed | `font-weight: 600;` (theme picks its sans via own `:root[data-theme]` font-family override if any) |
| `.card-bar` | thin (3px), rounded | `height: 3px; border: none; border-radius: 2px;` |
| `.card-stats` | percentage shown alongside speed/ETA | text content concatenation already in JS — no override needed; CSS keeps stats line right-aligned |

## DOM / JS changes (minimal)

The card template (`_INDEX_HTML_BODY` `<template id="card-template">`) is unchanged. Card-rendering JS in `_INDEX_JS` gains a single line in `renderCard` (around current line `audio_dl_ui.py:1874`, immediately after the existing `formatDuration(st.duration)` use that builds `.card-meta`):

```js
// In renderCard, after the existing st.duration handling:
el.querySelector('.card-thumb').setAttribute(
  'data-duration', st.duration ? formatDuration(st.duration) : ''
);
```

`formatDuration` already exists in `_INDEX_JS` and is the same helper that produces the `"4:11"` shown in `.card-meta`. The attribute is set on every render (including pre-metadata renders where it's `""`). The `[data-duration=""]::after { display: none }` rule prevents an empty overlay box from showing.

That's the entire JS delta. No cluster detection, no theme detection — modern's `::after` is conditional on the cluster CSS rule, not on JS state.

## Lifecycle state coverage

All 6 v1.6 lifecycle states (`queued`, `resolving`, `downloading`, `postprocessing`, `complete`, `failed`) must render correctly under each cluster. Verification approach per state:

| State | What must hold under every cluster |
|---|---|
| `queued` | progress + log hidden (per existing `.card[data-state="queued"] .card-progress, .card-log { display: none }` rule). Cluster CSS doesn't override `display: none`. Verified by base CSS specificity (state rule's selector has higher specificity than cluster's `.card-progress` selector). |
| `resolving` | as above + animated badge `::after`. Cluster CSS doesn't touch `.card-badge::after`. |
| `downloading` | full card visible. Mockup state. |
| `postprocessing` | progress bar continues to render; `.card-stats` shows "extracting audio" / similar text. Cluster CSS styles `.card-stats` color/font but not content. |
| `complete` | badge color → `var(--ok)`, reveal-in-Finder button visible. Editorial cluster's removed full border doesn't affect the badge or button. |
| `failed` | badge color → `var(--err)`, error log lines highlighted via `[data-level="error"]`. Cluster CSS log styling (italics/prefix) doesn't override the `--err` color rule. |

CSS specificity verification: the state rules use `.card[data-state="X"] .card-Y` (specificity 0,2,1) whereas cluster rules use `[data-theme="Z"] .card-Y` (specificity 0,2,1) — equal. Cluster CSS appears *after* state CSS in source order, so cluster wins on ties. For the rules where state must win (display hide), use `:where()` to drop cluster specificity to 0, or move state rules to after cluster rules. **Decision:** keep cluster rules from touching `display`, `--ok`, `--err`, and animation properties. Document this constraint at the top of the cluster CSS block.

## CSS implementation skeleton

```css
/* ===========================================================
   v1.7 — Per-theme card structural variations (cluster-scoped)
   Phosphor uses base .card rules unchanged.
   Do not override: display:none state rules, --ok/--err on
   .card-badge, animation properties on .card-badge::after.
   =========================================================== */

/* --- VINTAGE cluster ----------------------------------------- */
[data-theme="amber"] .card,
[data-theme="solarized"] .card,
[data-theme="gruvbox"] .card {
  border-style: dotted;
  letter-spacing: 0.04em;
}
/* …plus thumb, title, meta, bar, log overrides per the table */

/* --- EDITORIAL cluster --------------------------------------- */
[data-theme="rose"] .card,
[data-theme="moon"] .card,
[data-theme="dawn"] .card {
  border: none;
  border-bottom: 1px solid var(--frame);
  padding: 16px 14px;
}
/* …plus title, meta, bar, log overrides */
[data-theme="dawn"] .card {
  grid-template-columns: 1fr;
}
[data-theme="dawn"] .card-thumb {
  display: none;
}

/* --- MODERN cluster ------------------------------------------ */
[data-theme="tokyo"] .card,
[data-theme="atom"] .card,
[data-theme="claude"] .card {
  border-radius: 10px;
  grid-template-columns: 1fr;
  grid-template-rows: auto auto;
  gap: 10px;
}
[data-theme="tokyo"] .card-thumb,
[data-theme="atom"] .card-thumb,
[data-theme="claude"] .card-thumb {
  width: 100%;
  height: 100px;
  border-radius: 6px;
  position: relative;
}
[data-theme="tokyo"] .card-thumb::after,
[data-theme="atom"] .card-thumb::after,
[data-theme="claude"] .card-thumb::after {
  content: attr(data-duration);
  position: absolute;
  top: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  font: 600 0.7em var(--mono, ui-monospace);
  padding: 2px 6px;
  border-radius: 3px;
}
[data-theme="tokyo"] .card-thumb[data-duration=""]::after,
[data-theme="atom"] .card-thumb[data-duration=""]::after,
[data-theme="claude"] .card-thumb[data-duration=""]::after {
  display: none;
}
[data-theme="tokyo"] .card-meta,
[data-theme="atom"] .card-meta,
[data-theme="claude"] .card-meta {
  order: -1;
  text-transform: uppercase;
  font-size: 0.7em;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--accent);
}
/* …plus bar, title, log overrides */
```

Full block estimated at ~120 lines. Lives at the end of `_INDEX_CSS_THEMES`, after the existing per-theme frame/panel overrides.

## Pragmatic simplifications surfaced from mockup → implementation

The mockup screens during brainstorming showed three things that the spec deliberately reshapes for pure-CSS implementation. Calling them out so the spec review knows what was deferred / reshaped:

1. **Vintage ASCII progress bar (`━━━░░░`):** mockup showed literal box-drawing chars. Spec uses CSS `repeating-linear-gradient` for a chunked-block look. Same visual signal, no JS markup branching.
2. **Editorial prose metadata ("by Geotic · 4 min 11 sec"):** mockup showed reformatted prose. Spec keeps the v1.6 JS-rendered `"Geotic · 4:11"` and italicizes via CSS. Same signal, no per-cluster JS.
3. **Editorial collapsed log line:** mockup showed log condensed to a single sentence. Spec keeps the existing 3-line log structure but styles the lines italic/smaller. The 3 lines visually read as one paragraph at editorial sizing.

If any of these reshaping decisions are wrong, surface in spec review; ASCII bars and prose metadata would require JS changes that we'd then need to budget for.

## File changes

| File | Action | Notes |
|---|---|---|
| `audio_dl_ui.py` | Modify | Append ~120 lines of cluster card CSS to `_INDEX_CSS_THEMES`. One-line JS addition in `renderCard` for `data-duration` attribute. No template/HTML changes. |
| `test_audio_dl_ui.py` | Modify | Add `TestCardClusterOverrides` class: (1) each cluster's grouped selector block is present in rendered HTML; (2) phosphor has no `.card` override (sanity check that default cluster stays untouched); (3) `data-duration` attribute appears on `.card-thumb` in the template; (4) `[data-theme="dawn"] .card-thumb { display: none }` is present (the one full-hide rule). |
| `CHANGELOG.md` | Modify | Prepend `## v1.7 — Per-theme card structural variations`. |
| `audio_dl.py` | Modify | `__version__ = "1.7"`. |
| `pyproject.toml` | Modify | `version = "1.7"`. |
| `CLAUDE.md` | Modify | Append a Conventions bullet: "Per-theme card variations are cluster-scoped CSS only — JS card-rendering stays cluster-agnostic. Override pattern: `[data-theme=<slug>] .card-X` after the cascade blocks. Never override display/ok/err/animation properties at the cluster level — those belong to base state CSS." Link this spec. |
| `README.md` | No change | Screenshots could be refreshed; out of scope. |

No new files. No new dependencies. PyInstaller spec untouched.

## Testing

New `TestCardClusterOverrides` class in `test_audio_dl_ui.py`:

1. **All 3 cluster blocks present** — render HTML, assert each of these grouped selectors appears at least once:
   - `[data-theme="amber"] .card,\n  [data-theme="solarized"] .card,\n  [data-theme="gruvbox"] .card`
   - `[data-theme="rose"] .card,\n  [data-theme="moon"] .card,\n  [data-theme="dawn"] .card`
   - `[data-theme="tokyo"] .card,\n  [data-theme="atom"] .card,\n  [data-theme="claude"] .card`
   - Exact whitespace tolerant; use regex with `\s*` between selectors.
2. **Phosphor untouched** — assert `[data-theme="phosphor"] .card` does NOT appear in rendered HTML.
3. **Dawn thumb hidden** — assert `[data-theme="dawn"] .card-thumb { display: none` (or `display:none`) appears.
4. **`data-duration` set in JS** — assert rendered `_INDEX_JS` source contains a `setAttribute('data-duration'` call inside the `renderCard` function. (Duration is dynamic — set at metadata time, not at template instantiation — so the template should not carry it.)
5. **Forbidden-override sanity** — assert cluster CSS does NOT contain `display: none` *as a value of state-conflicting selectors*. Lightweight check: scan the cluster CSS region and assert no `.card-progress` or `.card-log` rules with `display:` in cluster scope (regex against the rendered HTML).
6. **Existing `TestThemeRendering` still passes** — additive change, all 10 `:root[data-theme]` blocks + JS THEMES registry unchanged.

Manual verification (not automated):
- All 10 themes rendered with a live job: cards visually reflect their cluster.
- Phosphor card pixel-diff against v1.6: zero diff.
- Dawn card with hidden thumb still aligns nicely; the grid collapse to `1fr` doesn't leave a phantom left margin.
- Modern duration overlay appears once metadata loads (test with a URL that has known duration).
- All 6 lifecycle states render correctly under each cluster (especially `complete` badge color and `resolving` animation).
- Pylint stays at 10.00/10 (existing `pylint: disable=line-too-long` covers the new lines).

## File-size impact

Current `audio_dl_ui.py`: ~2230 lines (post-v1.6).

Estimated additions:
- Cluster CSS block in `_INDEX_CSS_THEMES`: ~120 LOC
- Constant-region comment header: ~6 LOC
- JS `setAttribute('data-duration', ...)`: 1 LOC
- `renderCard` durationStr accessor (may already exist): 0-2 LOC

Total ~130 LOC → ~2360 lines. Comfortably within the "single sibling file" convention.

## Versioning

Per [CLAUDE.md](../../../CLAUDE.md) release flow:

- Bump `__version__` in `audio_dl.py` → `"1.7"`.
- Bump `version` in `pyproject.toml` → `"1.7"`.
- Prepend `## v1.7 — Per-theme card structural variations` section to `CHANGELOG.md`.
- Commit, tag `v1.7.0`, push to internal. Mirror workflow handles the rest (filter-strip → public push → release.yml → built `.app` → GitHub Release).

## Open follow-ups (out of scope — preserved for v1.8+)

- **Mobile / narrow-viewport responsive treatment** — per-cluster cards at widths < 480px. Likely collapses modern's top-thumb layout, hides amber's thumb dither, simplifies editorial padding.
- **Expandable log tail** — click a card to see all 50 lines, not just the last 3. Independent of cluster work.
- **Aggregate stats panel** — total speed, queue ETA, total bytes summary. Independent.
- **Reveal-in-Finder per-card affordance tightening** — current button is functional but could be a clearer call-to-action per cluster (icon vs text vs full-card-clickable).
- **Per-theme card variants within a cluster** — e.g. solarized differs from amber while both stay "vintage." This spec applies cluster-uniform treatment; deeper per-theme tuning is a separate spec.
- **JS-aware variation** — if a future cluster needs DOM-level reordering, this is the moment to revisit the cluster-agnostic-JS principle. Not in v1.7.

## Acceptance criteria

- [ ] All 3 cluster CSS blocks present in rendered HTML and detected by `TestCardClusterOverrides`.
- [ ] Phosphor card visually unchanged from v1.6 (no `.card` selector under `[data-theme="phosphor"]`).
- [ ] Dawn cards render without thumbnail and use the full row width.
- [ ] Modern cluster cards show duration overlay in thumb corner once metadata loads.
- [ ] All 6 lifecycle states render correctly under every theme.
- [ ] `card-badge` `--ok`/`--err` color rules survive cluster CSS (no override).
- [ ] `[..]` animation survives cluster CSS.
- [ ] All existing tests pass; new `TestCardClusterOverrides` tests pass.
- [ ] Pylint: 10.00/10.
- [ ] CLI behavior is byte-identical (no `audio_dl.py` changes apart from `__version__`).
- [ ] `audio-dl.app` rebuilds cleanly via `scripts/build-app.sh` and the v1.7 tag triggers the existing release pipeline green.
