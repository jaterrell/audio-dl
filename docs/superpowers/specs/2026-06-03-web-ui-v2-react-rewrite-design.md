# Spec — v2.0 Web UI rewrite (React, Now Playing aesthetic)

**Status:** Design approved 2026-06-03
**Target files:** new `web/` directory at repo root (Vite + React app); `audio_dl_ui.py` shrinks dramatically — backend endpoints stay, the 3700-line inline HTML/CSS/JS template + `_render_index` get removed; `audio-dl.spec` (PyInstaller) gains the Vite `dist/` as a `datas` entry; `scripts/build-app.sh` gains a `npm install && npm run build` step before PyInstaller runs.
**Predecessors:**
[web UI](2026-05-10-web-ui-design.md) (v1.2),
[themes](2026-05-14-console-ui-themes.md) (v1.5),
[rich cards](2026-05-16-rich-job-cards-design.md) (v1.6),
[per-theme card variations](2026-05-16-per-theme-card-variations-design.md) (v1.7),
[UX rearchitecture](2026-05-19-ux-rearchitecture.md) (v1.8),
[per-URL format](2026-05-19-per-url-format-design.md) (v1.9)

## Problem

The web UI accreted from v1.2 to v1.9 inside a single 3700-line Python string template — base CSS, ten console-themed CSS variants, an HTML skeleton, and ~1500 lines of vanilla JS. Each new feature meant editing string-templated HTML and writing imperative DOM updates inside a single global `script` tag.

The maintainer's verdict after living with it:

- The TUI/console aesthetic was a fun experiment, but the wow wore off and the visual language fights the actual job (downloading and organizing audio). It reads as a tool for the tool's sake, not for the music.
- The single-file template is a maintenance trap. Adding the v1.8 three-zone UI and the v1.9 row-builder each required navigating ~1000 lines of unrelated CSS to land changes. Refactoring is high-friction.
- Vanilla JS state management has hit its ceiling. SSE-driven progress updates work but are brittle; adding richer interactions (drag, animation, derived state) costs disproportionate JS.

v2 is a clean front-end rewrite. The FastAPI backend stays; the front-end is reborn as a Vite-built React SPA served by `StaticFiles`.

## Goals

- Modern, contemporary front-end stack a 2026 FE developer would recognize and respect: React 19 + Vite + TypeScript + Tailwind v4 + shadcn/ui + TanStack Query + Biome.
- A fresh aesthetic — the "Now Playing" paradigm: single-focus stage for the active download, ambient color extracted from album art, quiet queue below, no console residue.
- Component-first architecture. Each screen and primitive is its own file. The single-string template anti-pattern dies.
- Server contract unchanged where possible — minimize backend churn so frontend can iterate without dragging Python with it.
- macOS `.app` bundle still works: Vite `dist/` ships inside the PyInstaller bundle as a static-files directory; no Node required at runtime.

## Non-goals

- **Native macOS UI (SwiftUI/Cocoa).** Considered and rejected — the web stack inside the `.app` bundle is good enough and keeps a single codebase. Native is a v3+ conversation.
- **HTMX path.** Considered. Pairs with Alpine for any non-trivial interaction; ends up as two micro-frameworks fighting each other. State of JS 2025 shows React has settled as the boring-productive default and we have no constraint against Node-at-build-time.
- **cmd-K command palette.** Removed entirely. The previous version's cmd-K never worked properly; rather than rebuild, we surface every action through visible UI. No keyboard-only paths.
- **Themes.** v1.5's ten console themes are gone. v2 has one aesthetic, with an adaptive accent color extracted from the active album art.
- **The v1.9 row-builder.** Per-URL format pickers in a pre-submit list are gone. v2's input bar takes one URL at a time, with an inline format pill. Multi-line paste auto-queues each line at the current default format.
- **Server-side persistence.** History remains a client-side `localStorage` concept. The thumbnail cache (described below) is the one new server-managed artifact.
- **Backend rewrite.** All FastAPI endpoints, `JOBS` dict, SSE fan-out, CSRF, reveal handler, and credential boundary stay as designed.
- **Mobile / responsive design beyond reasonable viewport scaling.** Single-machine app, primarily for the maintainer's desktop / `.app` window.

## Mental model — Now Playing

The screen is a stage. One album is in the spotlight: the latest-started active download. Its art glows; its progress bar wraps in an accent color extracted from the art; the page's ambient gradient is tinted to match.

When more than one download is active, an "Also downloading" strip sits directly below the stage — small cards that let the user see concurrent progress without losing the spotlight.

Queued URLs (not yet started — beyond the global parallelism cap) live in a quiet "Up next" list beneath the strip.

An input bar at the bottom of the screen is always present. Paste a URL, optionally change the format pill, click Add. Multi-line pastes auto-queue each line.

A second screen, **Library**, holds the full history of completed downloads — a grid of album art tiles with search and per-format filter. This is browsing-the-collection territory, not active-work territory.

The two screens are the entire app. No drawers, no modals beyond format-picker dropdowns and a confirm-on-cancel dialog. No cmd-K.

## Locked decisions

Settled and not up for re-derivation during implementation.

| # | Decision |
|---|---|
| 1 | **Stack:** Vite 6 + React 19 + TypeScript + TanStack Router (SPA mode, no SSR) + TanStack Query + Tailwind v4 + shadcn/ui (Radix primitives) + Lucide icons + Biome (lint/format, replaces ESLint+Prettier). |
| 2 | **No cmd-K palette.** No `cmdk` dep. Every action is reachable through visible UI. |
| 3 | **Two top-level routes:** `/` (Now) and `/library`. TanStack Router handles them. Routing is overkill for two routes but is the trivial setup that makes adding a third route cheap, and is the FE-default people expect. |
| 4 | **Now screen layout:** Topbar (brand + tabs) · Stage (hero art + progress) · Also-downloading strip (when N > 1) · Up-next queue · Input bar (always-on, bottom). |
| 5 | **Stage occupant:** the most-recently-started active download. Re-elects when a new download starts or when the current stage occupant completes. |
| 6 | **Also-downloading strip:** up to 2 inline cards. Beyond 2, the strip horizontally scrolls. |
| 7 | **Empty state (no active downloads):** stage shows the most-recently-completed download with a "Last added" eyebrow (different color from the active "Downloading" eyebrow). Ambient gradient persists from that art. URL input bar is the only interactive element. |
| 8 | **Adaptive accent color:** dominant color extracted from the current hero's album art at runtime in the browser using `node-vibrant` (which despite the name is browser-compatible). Applied as CSS custom properties: `--accent`, `--accent-2` (slightly shifted hue for gradient), `--ambient` (used in the radial background). Fallback to a neutral indigo when no art is available. The library is lazy-loaded so it doesn't ship until the first hero appears. |
| 9 | **Format picker:** inline pill in the URL bar, shadcn `DropdownMenu`. Click opens the list of formats with `m4a · 256 kbps` etc. The picker holds the *current default* — every URL added with that picker selection takes that format. Multi-line paste uses the same default for each line. |
| 10 | **Library screen layout:** Topbar (same) · Search input (filter-as-you-type by title/artist) · Format filter pills (All · FLAC · m4a · mp4 · etc) · Grid of album art tiles grouped by day, then by title. |
| 11 | **History persistence:** unchanged from v1.8 — `localStorage` under key `audio_dl_history`, capped at 100 entries, FIFO drop. New: each entry stores a `thumbId` referencing the server-side thumbnail cache (see §Server changes). |
| 12 | **SSE handling:** custom hook `useJobEvents(jobId)` that opens an `EventSource`, parses events, and feeds them into TanStack Query cache via `queryClient.setQueryData` (direct cache mutation, not invalidation). The events payload already has everything we need; refetching would be wasteful. |
| 13 | **Per-job global state shape:** TanStack Query is the source of truth for server-derived state (active jobs, queue, progress). React state hooks for purely-UI state (which format the picker shows, search input, etc). No Redux / Zustand / Jotai. |
| 14 | **Multi-line paste:** splits on `\n`, trims, deduplicates, fires one `POST /jobs` call with all URLs at the picker's current default — reuses the v1.9 batch-shape (`{ urls: [{ url, format }, ...] }`). Server returns per-URL state grouped under a single JobState; frontend treats each URL state as its own card. Single roundtrip, no API divergence. |
| 15 | **Cancel:** stage and also-downloading cards each have a small "×" affordance on hover. Clicking opens a one-line shadcn `AlertDialog` ("Cancel this download?") before calling the existing `POST /jobs/{id}/cancel`. |
| 16 | **Reveal:** completed downloads in Library get a right-click context menu (Radix `ContextMenu`) with "Reveal in Finder" → existing `POST /reveal`. Hover shows a subtler "..." menu trigger as the discoverable affordance. |
| 17 | **Build artifact:** `web/dist/` after `npm run build`. FastAPI mounts via `app.mount("/", StaticFiles(directory="audio_dl_ui/static", html=True), name="static")`. The build copies `dist/*` into `audio_dl_ui/static/` so a `pip install` ships a populated static dir. |
| 18 | **PyInstaller:** `audio-dl.spec` `datas` gains an entry for `audio_dl_ui/static/**` so the `.app` bundle includes the built React app. `scripts/build-app.sh` runs `npm ci && npm run build` before invoking PyInstaller. |
| 19 | **No backwards compatibility with v1 UI.** v2.0 replaces it wholesale. Anyone on v1.x stays there; v2.0 is a fresh major version. |

## Aesthetic system

Concrete tokens. Tailwind v4's CSS-first config lets these all live as CSS custom properties.

**Color (dark, the only mode):**
- `--bg`: `#08080a` (near-black, slight blue)
- `--surface`: `rgba(255, 255, 255, 0.04)` (glass card on dark)
- `--surface-strong`: `rgba(255, 255, 255, 0.08)`
- `--border`: `rgba(255, 255, 255, 0.07)`
- `--text`: `#f5f5f7`
- `--text-2`: `#a1a1aa`
- `--text-3`: `#71717a`
- `--accent`, `--accent-2`, `--ambient`: dynamic, extracted from hero album art via Vibrant.js. Fallback `--accent: #818cf8`, `--accent-2: #c084fc`, `--ambient: rgba(129, 140, 248, 0.18)`.

**Background:**
- Body: solid `--bg`.
- Stage backdrop: two radial gradients composited — one large ellipse at top-center using `--ambient`, one smaller ellipse at bottom-right at lower opacity. Transitions over ~600ms when the hero changes (CSS transition on a wrapping div's `background` property — implemented via a swap of two stacked layers cross-fading, since `background` is not transition-animatable directly).

**Typography:**
- Sans: Inter (self-hosted via `@fontsource/inter`). Display weights 600/700 for titles; 400/500 for body.
- No mono font shipped. Numerals use `font-feature-settings: "tnum"` for tabular figures in progress meters.
- Sizes: title (stage) `26px / 700 / -0.025em`, sub-head (queue / library headings) `16px / 700`, body `14px`, meta `13px`, micro `12px`, eyebrow `11px / 700 / uppercase / 0.06em letterspacing`.

**Spacing:** Tailwind defaults (4px base). Standard rhythm — sections separated by `mt-7` (28px); card internals on `p-4` (16px); fine spacings on `gap-2` (8px).

**Radii:** `--radius-lg: 14px` (cards), `--radius-md: 10px` (inputs, pills), `--radius-sm: 6px` (chips, mini art).

**Shadows:**
- Hero art: `0 24px 64px rgba(0,0,0,0.55), 0 0 100px var(--ambient)` — the ambient glow is the only "decorative" shadow.
- Cards: `0 0 0 1px var(--border)` (subtle outline rather than drop shadow).
- Progress bar fill: `0 0 8px var(--accent)` at 50% opacity — small inner glow on the accent.

**Motion:**
- Hero art transitions: cross-fade between layers, 600ms ease.
- Stage occupant change: `framer-motion` `AnimatePresence` slide-up-and-fade (200ms).
- Progress bars: width transitions on `0.2s linear`.
- Hover affordances: 150ms ease on opacity/background changes.
- No "loading shimmer" placeholders. Empty states are quiet typographic states.

**Iconography:** Lucide. Sized 16px in body, 20px in tabs, 14px in chips. Stroke width 1.75.

**No emoji in UI.** No console-style ASCII glyphs as decoration. No monospace, anywhere.

## Architecture

### Front-end project layout

```
web/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── biome.json
├── index.html
└── src/
    ├── main.tsx              # entry, Router + QueryClient providers
    ├── routes/
    │   ├── __root.tsx        # AppShell (Topbar + <Outlet />)
    │   ├── index.tsx         # Now screen
    │   └── library.tsx       # Library screen
    ├── components/
    │   ├── topbar.tsx
    │   ├── stage.tsx
    │   ├── also-downloading.tsx
    │   ├── queue.tsx
    │   ├── url-input.tsx
    │   ├── format-picker.tsx
    │   ├── album-art.tsx     # accepts thumbId, renders <img> with fallback gradient
    │   ├── library-grid.tsx
    │   ├── library-filters.tsx
    │   ├── empty-stage.tsx
    │   └── ui/               # shadcn-installed primitives (button, dialog, ...)
    ├── hooks/
    │   ├── use-job-events.ts   # SSE → cache
    │   ├── use-active-jobs.ts
    │   ├── use-history.ts      # localStorage R/W
    │   └── use-vibrant.ts      # extract palette from <img>
    ├── lib/
    │   ├── api.ts            # POST /jobs, /cancel, /reveal; CSRF helper
    │   ├── csrf.ts
    │   └── format.ts         # format-list constants, shared with backend semantics
    └── styles/
        ├── globals.css       # @import "tailwindcss"; CSS vars; Inter
        └── tokens.css        # design token CSS vars
```

### Front-end state model

- **Server-derived state** (TanStack Query):
  - `useQuery(["job", jobId])` — per-job state, populated and updated via SSE side-channel.
  - `useQuery(["jobs"])` — list of active job IDs (kept in a single client-managed array; SSE events add/remove).
- **localStorage state**:
  - `audio_dl_history` (existing v1.8 shape, plus a new `thumbId` field per item).
  - `audio_dl_settings` (new): default format pill selection, last-used output dir, etc.
- **Pure UI state** (React `useState`):
  - Search query in Library.
  - Active format filter in Library.
  - Format picker open/closed.
  - Cancel-dialog open/closed.

### Data flow — happy path

1. User types/pastes URL into `<UrlInput />`. Picks format from `<FormatPicker />` (or accepts default). Clicks **Add**.
2. `api.postJob({ url, format })` → backend returns `{ jobId, url, format, ... }`. Frontend appends `jobId` to the `["jobs"]` query data.
3. `useJobEvents(jobId)` opens `EventSource` at `/jobs/{jobId}/events?token=…`. Each event mutates `queryClient.setQueryData(["job", jobId], next)`.
4. `<Stage />` reads the "current stage occupant" derived from `useActiveJobs()` — selects the most-recently-started active job. Other active jobs feed `<AlsoDownloading />`. Queued (not-yet-started) job IDs from `["jobs"]` query data populate `<Queue />`.
5. When a job's event stream emits a "completed" terminal state: the frontend reads `paths` from the event, asks the backend for the stable thumbnail (`GET /thumbs/{thumbId}.jpg`), and prepends a history entry to `audio_dl_history`. The job ID is removed from the active jobs query.
6. Stage occupant re-elects. If no remaining active jobs, `<Stage />` switches to its empty mode and renders the most-recently-completed history entry as a "Last added" preview.

### Color extraction

`useVibrant(imgRef)` hook:
- Loads the image via `img.crossOrigin = "anonymous"` (backend serves `Access-Control-Allow-Origin: *` for thumbnails — single-machine app, no leak risk).
- Once loaded, runs `Vibrant.from(img).getPalette()`.
- Returns `{ accent, accent2, ambient }`. These are written to `:root` CSS custom properties via a `style` element so all consuming components react.
- Transitions: a 600ms CSS cross-fade between the previous palette and the new one — implemented by two stacked layers on the background, swapping `opacity`.

## Screens

### `/` — Now

Default route. Components in order from top to bottom:

1. **Topbar** — brand mark on the left, two-tab nav on the right (`Now` / `Library`). Active tab is highlighted with a subtle background; no underline. Brand mark is a 24px logo + "audio-dl" wordmark in 16px Inter 600.
2. **Stage** — `<EmptyStage />` if no active jobs, else `<HeroStage />` with the current occupant's album art (240×240, glow shadow), eyebrow ("Downloading · 1 of 3"), title, artist, progress bar with accent gradient, and `MB/s · time left` line below.
3. **`<AlsoDownloading />`** — present iff ≥2 active jobs. Up to 2 inline cards; overflow scrolls horizontally. Each card shows mini art (32px), title (truncated), and a 2px progress line.
4. **`<Queue />`** — present iff ≥1 not-yet-started (queued) job. Header "Up next" with a "N queued" right-aligned count. Each row: 40px art · title + artist · format pill.
5. **`<UrlInput />`** — always present. Single input + inline format pill + Add button. On submit: clears the input, fires `POST /jobs`, and the new job ID enters the active jobs query so the stage updates.

**Cancel affordance:** hover state on hero stage and also-downloading cards reveals a small × icon top-right of the art. Click → confirm dialog → `POST /jobs/{id}/cancel`.

### `/library` — Library

The collection-browsing view. From top to bottom:

1. **Topbar** — same as Now, `Library` active.
2. **Filter row** — search input (placeholder: "Search by title or artist"), format filter pills (All / FLAC / m4a / mp4 / etc — populated from union of formats in history).
3. **Grid** — album art tiles, 6 per row at desktop width, 4 at smaller widths. Tile shows art (square), title (one line, truncated), artist (one line, muted). Hover reveals "..." menu trigger; click opens shadcn `DropdownMenu` with: Reveal in Finder · Re-download · Dismiss from history.
4. **Group headers** — between tile sections: "Today" / "Yesterday" / `Monday, May 25` etc. Generated from history `addedAt` timestamps. Sticky on scroll.

**Empty Library:** quiet typographic state — large but light-weight "Nothing yet. Downloads will appear here once they finish." centered. No illustration.

## Components

Brief contracts for the main ones. Each is its own file in `src/components/`.

| Component | Props | Owns |
|---|---|---|
| `<Topbar />` | — | route highlighting via TanStack Router |
| `<HeroStage />` | `job: ActiveJob` | rendering the active job's art + meta + progress; cancel button; firing `useVibrant` to set ambient |
| `<EmptyStage />` | `latest?: HistoryItem` | preview of latest history item or quiet wordmark if no history |
| `<AlsoDownloading />` | `jobs: ActiveJob[]` | horizontal scroll; per-card cancel |
| `<Queue />` | `jobs: QueuedJob[]` | listing only; no actions beyond format-display |
| `<UrlInput />` | — | input state, paste-splits, format-picker selection, submit |
| `<FormatPicker />` | `value: Format, onChange` | dropdown menu; persists choice to `audio_dl_settings` |
| `<AlbumArt />` | `thumbId?: string, fallback?: ReactNode, size: number` | `<img>` with `onError` → fallback gradient; sets `referrerPolicy="no-referrer"` |
| `<LibraryGrid />` | `items: HistoryItem[]` | grouping by day; tile rendering; context menu |
| `<LibraryFilters />` | `search, formats, onChange` | controlled inputs |

## Server changes

Minimal. The current FastAPI surface is correct; v2 adds one thing and slightly amends another.

### Add

- **Thumbnail cache.** A new directory `~/Library/Application Support/audio-dl/thumbs/` (or `XDG_DATA_HOME` equivalent on Linux). When a job's thumbnail bytes are first fetched (or extracted by yt-dlp postprocessor) the server writes them to `thumbs/{thumbId}.jpg`, where `thumbId` is the SHA-1 of the source URL (stable across re-downloads). The existing `GET /jobs/{job_id}/thumb/{url_idx}.jpg` continues to serve live; a new `GET /thumbs/{thumb_id}.jpg` serves the cached file for history items.
- **`GET /api/version`.** Returns `{ version, build }`. The React app fetches this on boot and warns (via shadcn `Sonner`) if the backend major version doesn't match what the bundle expects. Used during development to catch stale-bundle bugs; near-no-cost in prod.
- **`GET /api/settings/defaults`.** Returns `{ output_dir, max_parallel, available_formats }` — values the backend was given at launch. The React app currently has no way to know `--output-dir` or `--max-parallel` without inferring from job results.

### Amend

- **`POST /jobs`** request body adds an optional `thumb_id` field — the frontend can pass a precomputed SHA so the server doesn't have to recompute. Server falls back to computing if absent. Non-breaking change.
- **`POST /jobs` response** adds `thumb_id` for each accepted URL, so the frontend can store it in history on completion.

### Unchanged

- CSRF token in URL on first launch; subsequent requests via header.
- `POST /jobs/{id}/cancel`.
- `POST /reveal`.
- SSE event stream at `GET /jobs/{id}/events` — same envelope; React parses identically.
- `JobState` / `JOBS` dict / ThreadPoolExecutor / `_check_dependencies_gui`.

### Removed

- `_INDEX_TEMPLATE`, `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`, `_INDEX_HTML_BODY`, `_INDEX_JS`, and `_render_index`. Replaced by `StaticFiles`-mounted `audio_dl_ui/static/`.
- `GET /` HTML response — replaced by the static `index.html` from the Vite build.
- `THEMES` JS constant and all theme switching machinery on the client.

## Build & packaging

### Development

```
cd web/
npm install
npm run dev   # Vite on http://localhost:5173, proxies /api and /jobs to FastAPI
```

In a second terminal:

```
audio-dl-ui --port 9000 --no-browser
```

The Vite dev server proxies `/api/*`, `/jobs/*`, `/reveal`, `/thumbs/*` to `localhost:9000`. CSRF token is fetched from the running backend's `/api/csrf` (new minor endpoint, see below) so dev mode survives without copy-pasting tokens.

### Add `/api/csrf` (dev-only convenience)

`GET /api/csrf` returns `{ token }` only when the request originates from `localhost` and the server is in dev mode (`AUDIO_DL_DEV=1` env or `--dev` flag). Not enabled in production builds. This lets the Vite dev server hand the token to the React app without manual paste.

### Production build

```
cd web/
npm ci
npm run build  # → dist/
# copy / symlink dist into audio_dl_ui/static/
```

`pyproject.toml` gains a small build hook (or `scripts/build-app.sh` does the copy) so a `pip install` ships a populated `audio_dl_ui/static/`. For the `.app`:

```
scripts/build-app.sh
  ├── npm ci (in web/)
  ├── npm run build
  ├── cp -r web/dist/* audio_dl_ui/static/
  └── pyinstaller audio-dl.spec
```

The PyInstaller spec gains an entry in `datas`:

```
datas = [
    ("audio_dl_ui/static", "audio_dl_ui/static"),
]
```

### Runtime

`audio_dl_ui.py` mounts:

```python
from importlib.resources import files
static_dir = files("audio_dl_ui") / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

`html=True` makes any unknown path serve `index.html`, so client-side routing (TanStack Router) works without server config.

## Migration

v2.0 ships as a major-version release. There is no soft-rollout; v1 users update and get the new UI. The v1.x line is unsupported going forward.

**One-time data carry-over:** v1's `audio_dl_history` localStorage entries are forward-compatible with v2's — they just lack the new `thumbId` field. The Library tile component treats missing `thumbId` as "no art available" and renders a fallback gradient. Users see a slightly degraded Library for old history items, full fidelity for new ones. Acceptable; no migration script needed.

**Settings localStorage:** new key `audio_dl_settings` defaults are set on first launch.

**CLI:** unchanged. `audio-dl` continues to work exactly as before. `audio-dl-ui` continues to accept the same flags.

## Testing

| Layer | Tool | Scope |
|---|---|---|
| Frontend unit | Vitest + React Testing Library | components in isolation: `<FormatPicker />`, `<AlbumArt />` fallback path, `<UrlInput />` paste-splitting, history hook reducer. |
| Frontend integration | Vitest + MSW (Mock Service Worker) | full Now screen with mocked SSE stream: job lifecycle from POST → events → completion → history. |
| Frontend E2E | (deferred) | Playwright is an option for v2.1+ if the React app needs cross-browser confidence. v2.0 launches without. |
| Backend | existing pytest (`test_audio_dl_ui.py`) | extended with tests for new endpoints (`/api/version`, `/api/settings/defaults`, `/api/csrf`, `/thumbs/`), thumbnail cache writer, `POST /jobs` `thumb_id` field. |
| Visual | Storybook is **not** added in v2.0 — overkill for a single-developer project. |

CI matrix unchanged (Python 3.10–3.13). New CI job: `web-build` runs `npm ci && npm run build` and confirms the bundle compiles. Node 20 LTS.

## Out of scope / deferred

- **Drag-and-drop URL ingestion** (drop a YouTube link onto the window). Considered for v2.0; cut because the paste flow is already low-friction and DnD adds surface area for edge cases. v2.1 candidate.
- **Waveform / spectrogram visualization on the stage.** Tempting; out of scope for v2.0.
- **Cancel-all / pause-all controls.** v2.0 has per-item cancel only. Bulk operations come back if a user actually asks.
- **Toast notifications on completion.** Sonner is in the stack but unused in v2.0. Stage transition already conveys completion. Reserve for failure cases in a follow-up.
- **Theme system back.** v2 is dark-only with adaptive accent. Multiple themes will not return.
- **Server-pushed history sync across devices.** Stays out, per v1.8 spec.
- **`JOBS` dict GC.** Still deferred from v1.8; not made worse by v2.0.
- **Sentry / error reporting.** Out for a single-user app.
- **i18n.** Out.

## Open questions

- **`node-vibrant` bundle size.** ~30KB gzipped; acceptable. Decision #8 already calls for lazy-loading it so it doesn't ship until the first hero appears.
- **Thumbnail cache eviction.** v2.0 ships with no eviction — thumbs accumulate forever. Probably fine for years. Add LRU eviction in a later patch if disk usage becomes an issue.
- **Server `--dev` flag.** Need to decide whether `AUDIO_DL_DEV=1` env or a `--dev` CLI flag is preferred. Picking flag during plan-writing.
- **CSRF in SSE.** Current backend accepts token via `?token=` query param on SSE. React app passes it identically. Verify Vite dev proxy preserves it.

## Implementation order (preview, for the plan)

1. Scaffold `web/` with Vite + React + TypeScript + Biome + Tailwind v4 + shadcn/ui. Verify dev server runs and proxies to backend.
2. Add backend endpoints: `/api/version`, `/api/settings/defaults`, `/api/csrf` (dev-only), `/thumbs/{thumbId}.jpg`. Tests.
3. Implement `lib/api.ts`, `lib/csrf.ts`, `lib/format.ts`. Frontend talks to backend.
4. Implement `useJobEvents` SSE hook + TanStack Query setup. Single-job end-to-end works in dev.
5. Build Now screen components in dependency order: `<AlbumArt />` → `<UrlInput />` → `<HeroStage />` + `useVibrant` → `<AlsoDownloading />` + `<Queue />` → `<EmptyStage />`.
6. Wire Now screen as `/` route via TanStack Router. AppShell with Topbar.
7. Library screen: history hook, `<LibraryGrid />`, `<LibraryFilters />`, group-by-day.
8. Polish pass: motion (Framer Motion installs here), color cross-fade, cancel dialog, empty states.
9. Remove `_INDEX_*` constants and `_render_index` from `audio_dl_ui.py`. Mount `StaticFiles`. Backend tests updated.
10. Update `audio-dl.spec` PyInstaller config + `scripts/build-app.sh`. Verify `.app` ships and runs.
11. README, CHANGELOG, `__version__ = "2.0.0"`, `version = "2.0.0"` in `pyproject.toml`.
