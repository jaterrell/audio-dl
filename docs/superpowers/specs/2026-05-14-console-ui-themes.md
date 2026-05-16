# Console UI + Theme System — design spec

**Status:** Approved (brainstorm 2026-05-14, terminal + visual companion at `.superpowers/brainstorm/56640-1778765771/`).
**Date:** 2026-05-14
**Owner:** Joe Terrell
**Target release:** v1.5

---

## Purpose

Replace the current "macOS-system-light" web UI with a TUI-in-browser direction (Console aesthetic) and add a runtime theme system with 10 themes. The current UI is functional but generic; this slice gives audio-dl a distinctive visual identity that aligns with its CLI/utility heritage and the audience (people who already live in a terminal).

## Audience

Same as today: a developer / power user running audio-dl on their own machine via `audio-dl-ui` or the bundled `.app`. The UI is dark-by-default, keyboard-driven, dense, and unapologetically TUI-styled. Light-mode users get **Rose Pine Dawn** auto-applied on first visit; their explicit choice always wins after that.

## Goals

- Visual: TUI-in-browser look, JetBrains Mono everywhere, real Unicode box-drawing frame chars (not CSS-styled-to-look-TUI), monospace progress bars, status-glyph conventions (`[OK]`, `[..]`, `[--]`, `[!!]`, `[xx]`).
- Themes: 10 themes selectable at runtime via a popover picker anchored to a `theme: <slug> ▾` button in the TUI header. Phosphor Green is the factory default. Selection persists to `localStorage["audio-dl-theme"]`.
- Interaction: keyboard-driven UX — `⌘↵` to submit, `esc` to cancel the active job, `⌘T` to cycle themes inline, `⌘K` to open the picker with search focused.
- Information density: per-URL status in the same format as `htop`/`btop` — bracketed glyphs + mono numerics + ASCII bars. Job-panel header replaces the vague "Current job" label with a live summary (`2 done · 1 active · 0 fail`).
- Pylint stays at 10.00/10. All existing tests pass; new tests cover theme rendering. No CLI behavior change.

## Non-goals (deferred or rejected)

- **Drag-and-drop URLs, clipboard paste detection, history, format presets, per-URL option overrides.** Bundled together as the "new features" bucket from the brainstorm; explicitly deferred to v1.6+ per scope decision.
- **Settings/preferences drawer.** Theme is the only configurable surface in v1.5; a dedicated settings panel would be premature.
- **Static-files extraction** (`audio_dl_ui_static/index.html` etc., served by `StaticFiles`). Considered, rejected — stays inline in `audio_dl_ui.py` to honor the CLAUDE.md sibling-file convention and avoid PyInstaller spec changes for the bundle.
- **JS test infrastructure.** No `jest`/`vitest`/Playwright in the project today; not adding one for this scope. Picker behavior is verified manually + by structural HTML tests.
- **Backwards-compat for the previous look.** Existing UI is replaced wholesale; no toggle to revert to v1.4 chrome. No one's saved-state depends on the old structure.

---

## Decisions (pinned)

| Decision | Choice | Reasoning |
|---|---|---|
| **Visual direction** | "Console" — TUI in a browser | Distinctive vs. the generic "Inter + indigo + dark" SaaS aesthetic; aligns with the project's CLI/utility heritage; the user gravitated to it after seeing 4 alternatives. |
| **Type** | JetBrains Mono everywhere (no Inter, no system-font fallback for body text) | Mono-as-display commits to the TUI identity; the original mockup used Inter and felt like a Linear clone. |
| **Frame** | Real Unicode box-drawing (`┌─ ┐ │ ├─ ┤ └─ ┘`) | The soul of the design is "this is actually a TUI." CSS borders styled to look TUI would feel cosplay. Trade-off accepted: copy-paste includes the chars (acceptable). |
| **Default theme** | Phosphor Green | Most "TUI" of the lineup; punchy first impression; user-selected explicitly. |
| **Theme storage** | `localStorage["audio-dl-theme"]` ← slug | No server round-trip; survives reload; easy to clear. |
| **Theme mechanism** | `<html data-theme="...">` + per-theme `:root[data-theme="..."]` CSS-vars block | Adding a theme = one new block, zero JS change. Standard pattern, no framework. |
| **Light-mode users** | First-visit only: auto-apply Rose Pine Dawn if `prefers-color-scheme: light` and no stored preference | Honors system preference once; doesn't override user choice afterward. |
| **Picker UX** | Popover anchored to header `theme: <slug> ▾` button | Keeps theme switching inside the TUI frame, not as separate chrome. Search input + 2-col thumbnail grid; click applies + closes; esc closes; click-outside closes. |
| **Keyboard** | `⌘↵` submit, `esc` cancel, `⌘T` cycle themes, `⌘K` open picker w/ search focused | Sets up future command-palette work without building one yet. |
| **Status glyphs** | `[OK]` done, `[..]` active (pulses), `[--]` queued, `[!!]` failed, `[xx]` cancelled | Reads at a glance; mono-aligned; htop-style. |
| **Progress bars** | ASCII (`▓▓▓▓▓▓░░░░░░ 73%`) | Not a CSS bar styled to look TUI. Same soul rule as the frame. |
| **Code organization** | Split `_INDEX_HTML` → `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`, `_INDEX_HTML_BODY`, `_INDEX_JS` constants + `_INDEX_TEMPLATE` shell, all in `audio_dl_ui.py` | Honors "no third module" rule from CLAUDE.md. Avoids PyInstaller bundle complications. Manageable per-constant size. |
| **Reduced motion** | Respect `prefers-reduced-motion: reduce` — disable the `[..]` pulse animation | A11y baseline; trivial to add. |

---

## Architecture

### Theme cascade

```
:root[data-theme="phosphor"] {
  --bg:    #000;
  --fg:    #d0d0d0;
  --frame: #1a4a1a;
  --label: #707070;
  --accent:#00ff88;
  --ok:    #00ff88;
  --err:   #ff5555;
  --warn:  #ffaa33;
  --live:  #00d9ff;
  --dim:   #555;
  --bar:   #00d9ff;
  --btn-fg:#000;
}
:root[data-theme="rose"] { --bg: #191724; --fg: #e0def4; --accent: #ebbcba; ... }
:root[data-theme="moon"] { --bg: #232136; ... }
/* …7 more */
```

10 theme blocks, one per slug — no `:root` default. The boot script always sets `documentElement.dataset.theme` to a known slug (chosen from localStorage, prefers-color-scheme, or `'phosphor'` fallback) before paint. No FOUC because the boot script is synchronous in `<head>`. All component CSS uses `var(--bg)`, `var(--fg)`, etc. — no theme-specific selectors anywhere except the cascade blocks.

### Theme registry (in JS)

```js
const THEMES = [
  { slug: 'phosphor', name: 'Phosphor Green',  default: true  },
  { slug: 'rose',     name: 'Rose Pine'                       },
  { slug: 'moon',     name: 'Rose Pine Moon'                  },
  { slug: 'dawn',     name: 'Rose Pine Dawn',  light: true    },
  { slug: 'amber',    name: 'Amber CRT'                       },
  { slug: 'solarized',name: 'Solarized Dark'                  },
  { slug: 'gruvbox',  name: 'Gruvbox Dark'                    },
  { slug: 'tokyo',    name: 'Tokyo Night'                     },
  { slug: 'atom',     name: 'Atom Dark Pro'                   },
  { slug: 'claude',   name: 'Claude'                          },
];
```

Single source of truth for the picker UI. The CSS blocks are written in the same order; mismatches are caught by the rendering test (see Testing).

### Boot sequence

The boot script runs **synchronously in `<head>`** (before body paint) so the theme is applied without flash:

1. Read `localStorage["audio-dl-theme"]`. If set and matches a known slug, use it.
2. Else, if `matchMedia('(prefers-color-scheme: light)').matches`, use `'dawn'`.
3. Else, use `'phosphor'`.
4. Set `documentElement.dataset.theme = chosen`.

A second JS block at end-of-body, on `DOMContentLoaded`:

5. Bind keyboard handlers (`⌘↵`, `esc`, `⌘T`, `⌘K`).
6. Bind picker open/close/search/select handlers.
7. Bind existing form-submit + SSE listeners as today (logic unchanged, only some DOM IDs may shift).

### Picker popover

- DOM: a `<div id="theme-popover" hidden>` after `<body>`, contains search input + thumbnail grid generated from the `THEMES` array.
- Open: clicking `theme: <slug> ▾` removes the `hidden` attr, focuses search, sets `aria-expanded="true"` on the trigger.
- Close: `esc`, click-outside (mousedown on `document` not in `#theme-popover`), or selecting a theme.
- Keyboard navigation: `arrow up/down` move active thumbnail focus; `enter` selects; typing into search filters thumbnails by name (case-insensitive substring match).
- Each thumbnail is a tiny `<button>` with the theme's slug, rendering 4 short rows of mock TUI content using that theme's actual colors (inline-styled in the popover so it doesn't depend on the `data-theme` cascade — thumbnails preview themes other than the active one).

### Frame markup pattern

```
┌─ audio-dl ─────────────── v1.4 ──── theme: phosphor ▾ ─┐
  urls      ▸ <input>
            <next-line>
  format    ▸ mp3 · 320k
  output    ▸ ~/Downloads/audio-dl
  jobs      ▸ [████░░░░] 4
  fragments ▸ [████████] 8

            [ download ]  ⌘↵
├─ job ─ 2 done · 1 active · 0 fail ─┤
  [OK] youtu.be/dQw4...   → Never Gonna...mp3
  [..] soundcloud.com/x/y ▓▓▓▓▓▓░░░ 73%
  [--] youtu.be/abc...    queued
└────────────────────────────────────────┘
```

The frame is rendered as a series of `<div>`s with `white-space: pre` and inline box-drawing chars. Inputs (textarea, file path, format select) sit inline with the frame, styled to be borderless and inherit the theme bg/fg so they merge into the TUI text flow.

---

## File changes

| File | Action | Notes |
|---|---|---|
| `audio_dl_ui.py` | Modify | Replace `_INDEX_HTML` (currently ~280 lines, single string) with `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`, `_INDEX_HTML_BODY`, `_INDEX_JS`, `_INDEX_TEMPLATE` constants + `_render_index()` helper. Net delta ~+400 lines (the theme CSS blocks are the bulk). The `index()` route + `JobRequest` + endpoints unchanged. |
| `test_audio_dl_ui.py` | Modify | Add `TestThemeRendering` class: (a) all 10 `:root[data-theme="<slug>"]` rules present; (b) `THEMES` JS array contains 10 entries with slugs matching the CSS rules; (c) default-theme entry's slug is `phosphor`; (d) CSRF token + format options + default dir injection still work after refactor. ~50 net add. **Plus:** retarget the existing `_INDEX_HTML`-importing test (~line 870, the UTF-8-safe `btoa` check) to import `_INDEX_JS` instead, since `_INDEX_HTML` no longer exists post-refactor. |
| `CHANGELOG.md` | Modify | Prepend `## v1.5 — Console UI + theme system` section above v1.4. |
| `audio_dl.py` | Modify | `__version__ = "1.5"`. |
| `pyproject.toml` | Modify | `version = "1.5"`. |
| `CLAUDE.md` | Modify | Update the `audio_dl_ui.py` Layout entry to mention the constant split (`_INDEX_CSS_BASE`, etc.) and the theme registry. Add a Conventions bullet about the theme system (CSS-vars cascade, slug must match between CSS block and JS registry). Link to this spec. |
| `README.md` | No change | The web UI screenshots in README would ideally update but that's a follow-up; the structural docs are accurate. |

No new files. No new dependencies. No `pyproject.toml` extras change. PyInstaller spec untouched.

---

## Status-glyph conventions (full table)

| State | Glyph | Color var | Notes |
|---|---|---|---|
| Queued (not yet started) | `[--]` | `--dim` | Placeholder rows render this way. |
| Active (downloading) | `[..]` | `--live` | Pulses 0.5 → 1.0 opacity, 1.4s ease-in-out, infinite. Disabled under `prefers-reduced-motion`. |
| Completed | `[OK]` | `--ok` | Stays after job ends. |
| Failed | `[!!]` | `--err` | Includes one-line `ev.error` after the URL on the next render line. |
| Cancelled | `[xx]` | `--err` | Distinct from failed; only emitted when the user cancels. |

---

## Keyboard reference (full table)

| Binding | Action | Scope |
|---|---|---|
| `⌘↵` (Mac) / `Ctrl+↵` (other) | Submit form | Global, unless inside `<input>` that already submits on enter (textarea: ⌘↵ only). |
| `esc` | Cancel active job (if any) **or** close popover (if open) | Global; popover-close takes priority. |
| `⌘T` | Cycle to next theme without opening picker | Global; wraps from last → first. |
| `⌘K` | Open picker with search input focused | Global; closes if already open. |
| `arrow ↑/↓` | Move focus between thumbnails | Picker only. |
| `enter` | Apply focused thumbnail | Picker only. |

OS detection (`navigator.platform.includes('Mac')`) decides whether to listen for `⌘` (`metaKey`) or `Ctrl` (`ctrlKey`).

---

## Testing

New tests in `test_audio_dl_ui.py` (`TestThemeRendering`):

1. **All 10 theme blocks present** — `index()` HTML contains exactly 10 `:root[data-theme="<slug>"]` selectors, slugs `{phosphor, rose, moon, dawn, amber, solarized, gruvbox, tokyo, atom, claude}`.
2. **Theme JS registry matches CSS** — extract the `const THEMES = [...]` block from the rendered JS, parse, assert slugs match the set of CSS-block slugs (catches drift between JS and CSS).
3. **Default theme is `phosphor`** — `THEMES.find(t => t.default)?.slug === 'phosphor'`.
4. **CSRF token, format options, output dir injection still work** — re-run the existing `_render_index` substitution checks against the new structure to catch refactor regressions.
5. **No XSS regression** — `default_dir` containing `<script>` is escaped into the HTML attribute.

Existing tests: one retarget (the `_INDEX_HTML`-importing UTF-8-safe `btoa` check at ~`test_audio_dl_ui.py:870` becomes a `_INDEX_JS` import — same assertion, different constant name). All other tests — SSE happy path, broadcast tests, cancel tests, reveal-path-guard, dep-check tests, dialog escaping — unaffected.

**Pylint:** 10.00/10. The new `_INDEX_*` constants will need `pylint: disable=line-too-long` per-constant (already the pattern for `_INDEX_HTML`).

**Manual verification (not automated):**
- All 10 themes render correctly (visual check).
- Picker opens/closes/searches/applies; `⌘T` cycles; `⌘K` opens.
- `prefers-reduced-motion: reduce` disables the `[..]` pulse.
- `prefers-color-scheme: light` first-visit applies Dawn; subsequent visits respect stored choice.
- Box-drawing chars align across active themes (different fonts could shift glyph widths, but JetBrains Mono is monospace so this should hold).
- Existing job flow (paste URLs → download → SSE → completion → reveal) still works end-to-end.

---

## Risks / open questions

- **Browser font availability.** JetBrains Mono is not a system font on macOS or Linux. We could (a) ship a webfont via Google Fonts CDN, (b) self-host as a base64 data-URI inside the CSS, or (c) fall back to `ui-monospace, SFMono-Regular, monospace` and accept slight visual drift. **Decision:** (c) — fallback to the system mono. The aesthetic still reads "TUI." Adding a webfont is a real cost (CDN dependency or +100KB inline) for marginal polish gain. Document the decision in CLAUDE.md.
- **Box-drawing alignment under different fallback fonts.** SFMono is monospace and aligns; Cascadia Code (Windows) is monospace and aligns; some Linux fallbacks may not. Acceptable risk for v1.5.
- **Popover positioning at narrow widths.** The popover is 360px wide; if the viewport is < 400px it should reflow inline rather than overflow. Implement with `@media (max-width: 480px)` collapse. Localhost UI usage is overwhelmingly desktop; mobile is best-effort.
- **Atom Dark Pro naming.** User asked for "Atom Dark Pro." The canonical names are "Atom One Dark" (editor) and "One Dark Pro" (VS Code). The CSS palette ships under slug `atom`, name "Atom Dark Pro" — matches user's terminology.
- **Theme drift over time.** Adding a new theme requires (a) a CSS block with all 12 vars and (b) an entry in the JS `THEMES` array. The render-test catches drift but the human-visible name lives only in JS. Acceptable.
- **Light-mode auto-apply on first visit.** A user on a light-mode-preferring system who *wants* the dark experience has to switch themes manually after first load. Acceptable: it's one click and it persists. We will not surface this as a "first run" prompt.

---

## Acceptance criteria

- [ ] All 10 themes render correctly (visual check across active themes).
- [ ] Picker opens, closes via esc / click-outside / selection, and the search input filters thumbnails.
- [ ] `⌘↵` submits, `esc` cancels (or closes picker if open), `⌘T` cycles themes inline, `⌘K` opens picker with search focused.
- [ ] Theme persists across reload via `localStorage["audio-dl-theme"]`.
- [ ] First-visit on a `prefers-color-scheme: light` system applies Dawn.
- [ ] `prefers-reduced-motion: reduce` disables the `[..]` pulse animation.
- [ ] Box-drawing frame renders aligned in JetBrains Mono and the SFMono fallback.
- [ ] All existing tests pass; new `TestThemeRendering` tests pass.
- [ ] Pylint: 10.00/10.
- [ ] CLI behavior is byte-identical (no `audio_dl.py` changes apart from `__version__`).
- [ ] `audio-dl.app` rebuilds cleanly via `scripts/build-app.sh` and the existing CI release pipeline runs green on the v1.5 tag.
