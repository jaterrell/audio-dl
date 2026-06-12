# Changelog

## v2.1.0 — Toast notifications

The web UI gets a reusable feedback layer. Until now, failures were easy to miss: a bad URL paste failed silently unless you watched the queue, and a job that errored out in the background never told you. Toasts close that gap.

- **Toast notification system.** Success / error / info / loading variants, plus a promise-morph form (`toast.promise`) that shows "Queueing…" and morphs into the success or error result. Built on Radix Toast primitives with a `useSyncExternalStore`-pattern store (same shape as `use-history`), semantic color tokens, enter/swipe animations, and `prefers-reduced-motion` support. Screen-reader live-region politeness maps by variant (errors are assertive, the rest polite).
- **Wired into the flows that need feedback:** URL submission (promise toast on paste/submit), job completion and failure from the tracker — failures carry a **Retry** action that re-queues the URL with full event tracking, completions a **Reveal** action — and the Library tile menu's reveal / re-download actions report errors instead of failing silently.

## v2.0.1 — Live-test fixes

Three bugs found while smoke-testing v2.0.0 against the real backend. None of them showed up in the unit tests because the tests mocked exactly the wire shapes the unit tests asserted on, not what the backend actually emits.

- **Thumbnails now persist and render in the Library.** v2.0.0's `_run_one` looked for a sibling `.jpg` next to the downloaded audio. yt-dlp's `EmbedThumbnail` postprocessor (which runs for every audio format) embeds the thumbnail *into* the audio file and deletes the sidecar, so the sibling never existed. v2.0.1 reads from the live `_thumb_dir(job_id)/{url_idx}.jpg` path (populated by `_fetch_thumbnail` during the metadata callback) with a short polling window for fast downloads where the background fetch may not have finished. The `url_completed` event payload now includes `thumb_id` so the frontend can update history items that received their initial `job_snapshot` before persistence completed.
- **Titles and artists show up.** v2.0.0's frontend `UrlState` type didn't model `title` or `uploader`, so the backend's parsed values were dropped on the floor. `JobTracker` hard-coded `title: null, artist: null` into history items. v2.0.1 plumbs `title` and `uploader` through the `useJobEvents` snapshot normalization and `url_metadata` event handler, and `HeroStage`, `Queue`, `AlsoDownloading`, and `EmptyStage` all fall back to the URL only when the parsed title is missing.
- **SSE no longer reconnects in a loop on terminal jobs.** v2.0.0's `useJobEvents` left the raw `EventSource` running after the backend closed the stream. Browser default behavior is to auto-reconnect; the backend replied with the same terminal snapshot every time, churning at ~5 reqs/sec until navigation. v2.0.1 closes the `EventSource` (both on `onmessage` and `onerror`) once the cached snapshot reports a terminal state.

## v2.0.0 — Web UI v2 (React rewrite)

The web UI is rebuilt from scratch:

- **New aesthetic:** "Now Playing" single-focus design. Album art glows on a stage at the center; ambient color is extracted from that art using node-vibrant. The console / TUI look is gone.
- **New stack:** Vite + React 19 + TypeScript + TanStack Router + TanStack Query + Tailwind v4 + shadcn/ui (Radix primitives) + Lucide + Biome. The 3700-line inline `_INDEX_TEMPLATE` is replaced by a Vite-built bundle served via FastAPI `StaticFiles`.
- **New screens:** `/` (Now — active downloads, queue, URL input) and `/library` (full history with search + format filter, day-grouped tile grid).
- **No more themes.** The ten console themes from v1.5-1.7 are removed.
- **No cmd-K.** The keyboard palette is gone; every action is reachable through visible UI.
- **No more per-URL row builder.** Paste one URL at a time, or multi-line paste auto-queues each line at the current default format.
- **Adaptive accent color.** Each new hero album art re-tints the page's accent gradient.
- **Thumbnail cache.** Completed downloads' thumbnails are persisted on-disk under `~/Library/Application Support/audio-dl/thumbs/` and served by stable SHA-1 URLs via `GET /thumbs/{thumb_id}.jpg` — so the Library view always has art available.
- **Server additions:** `/api/version`, `/api/settings/defaults`, `/api/csrf` (dev-only), `/thumbs/{thumb_id}.jpg`. `POST /jobs` returns `thumb_id` per URL.
- **Backwards compatibility:** v1 history in localStorage carries forward as-is; old entries render with fallback gradients (no `thumb_id`). CLI is unchanged.

The `.app` build pipeline now runs `npm ci && npm run build` before PyInstaller. CI builds the bundle and runs the frontend test suite alongside pytest.

## v1.9.2 — nested-playlist output paths

**Fix:** `_collect_final_paths` now walks `entries` recursively so
channel pages, SoundCloud user URLs, and other playlist-of-playlists
shapes return their downloaded files instead of triggering the spurious
"Download succeeded but yt-dlp reported no output path" warning. The
previous shallow scan only looked one level deep, missing leaves that
yt-dlp produces 2+ levels in for `_type: "playlist"` /
`_type: "multi_video"` sub-resolutions. Includes a defensive
`id()`-based visited set to guard against self-referential entries.

## v1.9.1 — Codex review follow-ups

Two small correctness fixes from Codex's review of v1.9.0:

- **Reject duplicate URLs in a single submission with 400** instead of
  silently collapsing them via last-wins dict insertion. The UI already
  dedupes against `cardState`; API consumers now get a clear error
  ("Duplicate URL in submission: 'X'. Each URL may appear at most once
  per request.") instead of having one of their rows quietly dropped.
- **Submit button gating uses `renderQueue()` on success.** Previously
  the tail of `submitJob` re-enabled the button based on
  `queue.length === 0`. After a history re-download (which preserves the
  queue), that could re-enable submit even when invalid rows remained,
  letting the next submit silently drop them. `renderQueue()` honors the
  full validity predicate.

## v1.9.0 — per-URL format / single-screen row builder

The form is now a row builder: each URL carries its own target format,
set via a per-row dropdown. Mixed-format batches (music tracks + a
YouTube video, different audio codecs) submit in one shot instead of
one-format-per-submit.

**UI:**
- URLs zone is a list of rows with gutter marker · URL · format dropdown
  · remove (`×`). The last row is always an empty input ready for the
  next URL; pressing `↵` commits it.
- Pasting multi-line text splits into N rows. A trailing format token
  on a line (`mp3`, `m4a`, `flac`, `alac`, `opus`, `wav`, `mp4`,
  case-insensitive) is stripped from the URL and pre-fills that row's
  picker.
- Default-format strip below the queue: `default format for new URLs:
  [m4a ▾]` · `set all rows → default` · `clear all`. The default only
  affects newly added rows unless explicitly applied.
- In Flight cards gain a format chip in the header, color-bucketed by
  lossy (mp3/m4a/opus) / lossless (flac/alac/wav) / video (mp4).
- Submit button label reflects the row count: `[ SUBMIT N ]`.
- History rows already carried per-URL format (v1.8); re-download
  preserves it.

**Server:**
- `POST /jobs` body shape changed (breaking): `urls` is now
  `list[{url, format}]`. Top-level `format` and the vestigial `jobs`
  field are gone. The UI is the only client; CLI behavior is unchanged.
- `UrlState` gained `media_format`. `_run_one` reads it per-URL instead
  of the job-level default. `JobState.media_format` is retained as the
  submission default and surfaces in `job_snapshot.default_format`.
- `job_snapshot` events now include `media_format` per URL and
  `default_format` at the top level for late-joining subscribers.

**Non-goals (deliberately deferred):**
- CLI per-URL format syntax (still single `-f`).
- Smart per-platform format inference (`YouTube → mp4 automatically`).
- Edit-on-click for committed rows (use `×` + re-add).
- Persisting unsubmitted queue across browser refresh.
- Live re-download with a different format from History.

## v1.8.0 — UX rearchitecture: three-zone UI, persistent history

Replaces the v1.5–v1.7 single-pane card stack with a three-zone layout
(Input / In Flight / History) and adds a global concurrency cap. Fixes
the long-standing "no proper state management" pain: completed cards
no longer linger in the active view, the textarea clears after submit,
and a `localStorage`-backed History section persists across reloads.

**UI:**
- Three zones with live count headers and empty states. Completed URL
  cards leave In Flight via `url_completed` / `url_failed` and become
  compact rows in History.
- History stored in `localStorage` (key `audio_dl_history`, schema
  `{v: 1, items: [...]}`), capped at 100 entries with FIFO eviction.
  Per-row actions: re-download, reveal in Finder, dismiss. Thumbnails
  inlined as data URLs when ≤ 50KB; larger blobs are skipped.
- Textarea clears on successful submit.
- Per-submission `-j` field removed from the form (concurrency is now
  a launch-time setting).

**Server:**
- New `--max-parallel N` flag on `audio-dl-ui` (default 4). A single
  process-wide `ThreadPoolExecutor` replaces the per-job pool — URLs
  across all submissions share the same worker budget.
- `/reveal` validation switched from "path must appear in a live
  `JOBS` entry" to an allow-list of configured output directories
  (resolved with `Path.resolve()` + `is_relative_to`). History items
  can now reveal files long after their originating job aged out;
  path-traversal protection is unchanged.
- Server stays in-memory / stateless; no persistent storage added.

**Deferred to v1.9:** per-URL config, auto-retry on failure, `JOBS`
GC/TTL, live concurrency-cap adjustment in the UI. See
[spec](docs/superpowers/specs/2026-05-19-ux-rearchitecture.md).

## v1.7.1 — Enable yt-dlp EJS challenge solver

Single-line yt-dlp option fix for YouTube downloads.

yt-dlp's YouTube extractor now requires a JavaScript runtime (or a
remote-fetched solver) to compute the signature and `n` challenge
values that gate format URLs. Without either, every YouTube download
emits two warnings — *"Signature solving failed"* and *"n challenge
solving failed"* — and degrades the available format pool to a single
128kbps opus webm. The warnings flow straight into v1.6's rich-card
log tail, making every YouTube download look broken.

Setting `remote_components=['ejs:github']` in `_build_ydl_opts` tells
yt-dlp to fetch the official solver lib from GitHub once per session.
Warnings disappear; the full audio format pool comes back (verified:
8 formats discovered vs 1 on the broken path). Harmless for
non-YouTube extractors that ignore the key.

## v1.7 — Per-theme card structural variations

Cards now express each cluster's structural identity, not just its color palette.

- **Vintage cluster (amber · solarized · gruvbox):** dotted card + thumb borders, uppercase title and uploader, dithered/grayscale thumb filter, segmented progress bar via repeating-gradient, `>` log-line prefix.
- **Editorial cluster (rose · moon · dawn):** border-bottom only (no full box), serif title (Georgia), italic byline, thin rounded progress bar, italic log lines. Dawn additionally hides the thumb and collapses the card to a single-column grid.
- **Modern cluster (tokyo · atom · claude):** rounded 10px card with top-full-width thumb, duration overlay in the thumb's top-right corner, uppercase uploader-as-label *above* the title via CSS `order`, thin rounded progress bar.
- **Phosphor (default):** unchanged — remains the v1.6 reference card.

Implementation is pure CSS layered on the v1.6 card structure plus one new `setAttribute('data-duration')` call in `renderCard` to expose duration to the modern cluster's `::after` overlay. No backend, SSE, or `UrlState` changes.

Spec: `docs/superpowers/specs/2026-05-16-per-theme-card-variations-design.md`

## v1.6 — Rich job cards + structural-identity themes (2026-05-16)

Web UI: replaces the running-job row list with a stack of full-width
cards, each one a self-contained status panel — thumbnail, title +
uploader · duration, live speed/ETA/bytes, last 3 yt-dlp log lines,
and the v1.6/v1.7 per-theme structural typography + grid identities
shipped together.

### Added
- **Rich job cards** ([2026-05-16 spec](docs/superpowers/specs/2026-05-16-rich-job-cards-design.md)).
  Per-URL card with:
  - Server-proxied thumbnail at `/jobs/{id}/thumb/{idx}.jpg`
    (CSRF-guarded; no cross-origin loads).
  - Title / uploader / duration extracted from yt-dlp's info dict.
  - Live speed, ETA, downloaded/total bytes on every progress tick.
  - Filtered yt-dlp log tail: keeps `[hls]`, `[ffmpeg]`,
    `[ExtractAudio]`, `[EmbedThumbnail]`, `[Metadata]`, warnings and
    errors; drops debug, download-destination and extractor chatter.
  - Reveal-in-Finder on completed cards.
- **Six lifecycle states per card:** queued, resolving, downloading,
  postprocessing, complete, failed. `phase` is set server-side and
  travels on the `progress` event.
- **`url_metadata` SSE event** (one-shot per URL, may fire twice — once
  on info-known, once on thumb-fetched).
- **`url_log` SSE event** (filtered yt-dlp output, bounded ring of 50
  per URL).
- **`progress` event** gains a `phase` field; existing fields preserved.
- **`job_snapshot`** carries title / uploader / duration /
  thumbnail_ready / phase / log for late-connect subscribers.
- **Per-theme typography + structural identities shipped:** Phosphor
  reference rendering, vintage cluster (Amber CRT, Solarized, Gruvbox),
  editorial cluster (Rose Pine + Moon + Dawn), modern cluster (Tokyo
  Night, Atom Dark Pro, Claude), and per-theme CSS Grid layouts so each
  theme is structurally distinct.

### Changed
- `progress` event payload includes the new `phase` field; existing
  consumers ignore unknown fields.
- yt-dlp now runs with a per-URL `logger=` so its output is routed
  through the SSE log stream rather than printed to the UI process's
  stderr.

### Internal
- Pure functions added: `_should_keep_log`, `_pick_thumbnail_url`,
  `_url_idx`. Each is independently unit-tested.
- Thumbnail cleanup runs on job-complete-and-last-subscriber-disconnect.
- One new runtime dependency: `httpx` (used for server-side thumbnail
  fetching). Added to the `[ui]` extra in `pyproject.toml`.

## v1.5 — Console UI + theme system (2026-05-15)

Web UI redesign — replaces the macOS-system-light look with a
TUI-in-browser direction (Console aesthetic) plus a runtime theme
system with 10 themes selectable via a popover picker.

### Added
- **Console UI direction.** Real Unicode box-drawing frame
  (`┌─ ┐ │ ├─ ┤ └─ ┘`), JetBrains Mono font stack, status glyphs
  (`[OK]`, `[..]`, `[--]`, `[!!]`, `[xx]`), ASCII progress bars
  (`▓▓▓▓░░░░ 73%`), panel summary header (`X done · Y active · Z fail`).
  All component CSS goes through `var(--bg)`, `var(--fg)`, etc.
- **10 themes.** Phosphor Green (default), Rose Pine, Rose Pine Moon,
  Rose Pine Dawn (light), Amber CRT, Solarized Dark, Gruvbox Dark,
  Tokyo Night, Atom Dark Pro, Claude. Implemented as
  `:root[data-theme="<slug>"]` CSS-vars blocks + a JS `THEMES`
  registry. Theme persists to `localStorage["audio-dl-theme"]`.
- **Picker popover.** Anchored to the `theme: <slug> ▾` button in
  the TUI frame header. Search input + thumbnail grid; each
  thumbnail is a tiny live preview using that theme's actual colors.
- **Synchronous boot script.** Runs in `<head>` before paint;
  reads `localStorage` (or `prefers-color-scheme: light` → `dawn`;
  else `phosphor`) and sets `documentElement.dataset.theme` to
  avoid FOUC.
- **Keyboard shortcuts.** `⌘↵` submit, `esc` cancel job (or close
  popover if open), `⌘T` cycle themes inline, `⌘K` toggle picker
  with search focused. Picker grid supports arrow-up/down + enter.
- **Reduced-motion respect.** `[..]` pulse animation disabled
  under `prefers-reduced-motion: reduce`.

### Changed
- `audio_dl_ui.py` UI structure refactored from one ~280-line
  `_INDEX_HTML` string into five split constants
  (`_INDEX_TEMPLATE`, `_INDEX_CSS_BASE`, `_INDEX_CSS_THEMES`,
  `_INDEX_HTML_BODY`, `_INDEX_JS`) + `_render_index()` helper.
- `test_audio_dl_ui.py:870` (the UTF-8-safe `btoa` test) retargeted
  from `_INDEX_HTML` to `_INDEX_JS`.

### Decisions pinned (see [spec](docs/superpowers/specs/2026-05-14-console-ui-themes.md))
- TUI-in-browser, not "Linear with a nice icon."
- JetBrains Mono with `ui-monospace` fallback (no webfont CDN).
- Real Unicode box-drawing chars, not CSS-styled-to-look-TUI.
- Stays inline in `audio_dl_ui.py` — no static-files extraction
  (honors the CLAUDE.md sibling-file convention; no PyInstaller
  spec change).
- Drag-drop / clipboard paste / history / format presets / per-URL
  options bundled together as the deferred "new features" bucket
  for v1.6+ — out of scope for this slice.

### Test count
- 150 (was 147) — `TestThemeRendering` adds 3 tests; the
  refactor + status-glyph rewrite preserve every other test.

## v1.4 — Automated macOS release pipeline (2026-05-13)

Phase 3c + Phase 4 of the macOS .app roadmap, shipped as one slice:

### Added
- `.github/workflows/release.yml` — tag push to the public repo (gated
  with `if: github.repository == 'jaterrell/audio-dl'`) builds the arm64
  `.app` on a `macos-14` runner, smoke-tests the embedded uvicorn,
  packages a versioned zip alongside `SHA256SUMS`, extracts notes from
  this CHANGELOG, and publishes a GitHub Release. `workflow_dispatch`
  available for re-running a failed release on an existing tag.
- `scripts/extract_changelog.py` — stdlib-only release-notes extractor.
  Looks up the `## <tag>` section, falls back from `vX.Y.0` to `vX.Y`
  when the literal tag doesn't match, exits non-zero on no match so a
  missing CHANGELOG entry fails the workflow loudly.
- `scripts/package-release.sh` — stages the built `.app` with a bundled
  `README-FIRST.txt` (first-launch instructions for Gatekeeper), zips
  the directory, generates SHA256SUMS.
- `scripts/smoke-test-bundle.sh` — boots the bundle headless with
  `--no-browser`, polls `127.0.0.1:8000` for HTTP 200 with a 30s budget,
  fails the workflow if uvicorn can't bind.
- `scripts/release-templates/README-FIRST.txt` — bundled in every
  release zip; explains the right-click → Open Gatekeeper workaround
  next to the binary, not buried in the repo.
- `INSTALL.md` — full first-launch walkthrough for non-technical
  testers. README gets a short pointer subsection.

### Changed
- `_app_entry.py` strips only `-psn_*` argv (Finder process-serial-number
  flags) rather than clearing all argv. Real CLI flags like
  `--no-browser` now pass through to `audio_dl_ui.main`, which is what
  makes the CI smoke test possible.
- `scripts/build-app.sh` — dropped the dead Developer-ID
  signing/notarization `# TODO` block. The project is staying unsigned;
  the workaround (right-click → Open, documented in `INSTALL.md` /
  `README-FIRST.txt`) is the answer, not deferred signing work.

### Decisions pinned (see [spec](docs/superpowers/specs/2026-05-13-release-pipeline.md))
- Unsigned distribution (no Apple Developer Program enrollment).
- arm64 only (Apple Silicon). Intel users build from source.
- Tag-push trigger on the public repo only; internal mirror's same
  workflow file no-ops via the repo guard.
- Release notes auto-extracted from this CHANGELOG; missing section
  fails the workflow before publish.
- Smoke test is the gate: a built-but-unbindable bundle never reaches
  users.
- Build artifacts uploaded to the workflow run *before* `gh release
  create`, so a failed publish still leaves a downloadable zip.

### Test count
- 138 → 147 (added: 1 for the `_app_entry.py` argv refactor, 7 for
  `TestExtractChangelog` including bracket-style terminator regression,
  1 for `TestPackageRelease`; existing `test_strips_argv_before_delegating`
  renamed and retargeted).

## v1.3 — Automated macOS .app + SSE per-subscriber broadcast (2026-05-13)

### Added
- **Phase 3b: embedded ffmpeg in the macOS `.app` bundle.** `ffmpeg` now
  ships inside the bundle via
  [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) (LGPLv2.1+,
  attribution in [NOTICE.md](NOTICE.md), full license text in
  [LICENSES/ffmpeg-LGPL-2.1.txt](LICENSES/ffmpeg-LGPL-2.1.txt)). Consumers
  no longer need `brew install ffmpeg` for the .app to work. Bundle grew
  from ~47 MB → ~95 MB for the static binary. **Caveat:** imageio-ffmpeg
  ships only `ffmpeg`, not `ffprobe`; common audio/video flows work fine,
  but advanced yt-dlp extractor paths that invoke ffprobe still need a
  Homebrew install.
- Phase 3a (carried over from the prior PR): bundle infra, entry-point
  shim with Finder-argv stripping + Homebrew PATH bootstrap, `osascript`
  dialog for missing dependencies, ad-hoc codesigning. Developer-ID
  signing + notarization remain TODO blocks (Phase 3c).
- `_app_entry.py` — entry-point shim that strips Finder-injected argv
  (`-psn_NNN_MMM`) and bootstraps `/opt/homebrew/bin` + `/usr/local/bin`
  into `$PATH` before delegating to `audio_dl_ui:main`. Bundled-only;
  not part of the public API.
- `audio_dl_ui._show_macos_dialog` + `_check_dependencies_gui` — `osascript`
  dialog surfaces missing-dependency errors when stderr is invisible
  (the `.app` case). Falls through to stderr if the dialog itself can't be
  displayed. Terminal users get unchanged stderr output.
- `audio_dl._find_ffmpeg` — pure-ish resolver preferring the bundled
  `imageio_ffmpeg.get_ffmpeg_exe()` over `shutil.which("ffmpeg")`. Resolution
  feeds both `_check_dependencies` and `download_media` (via
  `ffmpeg_location` in the yt-dlp opts dict).
- `[project.optional-dependencies] app = ["imageio-ffmpeg"]` — build-time
  dep for the bundle. Install with `pip install -e '.[ui,app]'`.
- `NOTICE.md` — third-party attribution for the bundled LGPL ffmpeg.

### Changed
- **`audio_dl.check_dependencies` refactored** into a pure
  `_check_dependencies() -> list[str]` plus a thin CLI wrapper. Behavior
  change: when both ffmpeg AND yt-dlp are missing, the CLI now reports
  both before exiting instead of short-circuiting on ffmpeg.
- **`download_media` resolves ffmpeg per call** via `_find_ffmpeg()` and
  passes the path to yt-dlp as `ffmpeg_location`. Power users with a
  Homebrew ffmpeg keep that behavior (PATH fallback); bundle users get the
  embedded binary automatically.

### Fixed
- **SSE single-consumer queue (carried over from v1.2.1).** Replaced
  ``JobState.queue`` with a per-subscriber broadcast architecture. Each
  SSE connection registers its own ``queue.Queue`` and ``_emit`` fans
  events out to all of them, so a browser reconnect mid-job no longer
  races and splits events between the zombie and the new connection. New
  subscribers receive a ``job_snapshot`` event (cumulative state: URL list,
  per-URL status/percent/paths, ``complete`` flag, summary) — the UI is
  state-driven, so the snapshot is everything a fresh subscriber needs to
  render correctly. Events emitted before a subscriber connects are
  intentionally dropped (the worker thread can race ahead of the
  EventSource open); the snapshot covers their cumulative effect. The
  ``job_started`` event was removed — the snapshot conveys the initial
  URL list.

## v1.2.1 — 2026-05-11

### Fixed
- **[Security] CSRF token on web UI endpoints.** Random per-launch token,
  required on all state-changing endpoints (`X-Audio-DL-Token` header) and
  the SSE stream (`?token=` query param, since EventSource cannot set
  custom headers). Closes a drive-by-download attack class where malicious
  websites could trigger downloads via fetch to the localhost-bound server.
- **[Security] Refuse non-loopback bind without `--allow-remote`.** Prevents
  accidentally exposing the UI to a LAN or the public internet. `--host
  0.0.0.0` now requires explicit opt-in.
- **HTML-escape `--output-dir` in the form.** Was a self-XSS sink if the
  launcher was passed a crafted directory name (e.g., `'"><script>...'`).
- **`sanitize_url` exceptions no longer hang the UI row.** Now caught inside
  `_run_one`'s try block; emits `url_failed` and lets `job_completed`
  summarize correctly.
- **`/reveal` no longer crashes under concurrent job submission.** Snapshot
  `JOBS` before iterating instead of iterating the live dict.
- **Bound SSE queue at 128 events**, drop overflow progress events (already
  throttled to 5/sec/URL upstream). Prevents unbounded memory growth from
  slow/disconnected clients. Terminal events (`url_started`/`completed`/
  `failed`, `job_completed`) still go through.
- **UTF-8 safe URL row hashing.** Pasting URLs with non-ASCII characters
  (IDN domains, accented chars) no longer throws in the browser.
- **Rewrite `0.0.0.0` to `127.0.0.1` in the auto-opened browser URL.** The
  bind-all address often doesn't load in browsers; the server still binds
  to `0.0.0.0` when `--allow-remote` is passed.

### Known issues (deferred to v1.3)
- SSE single-consumer queue: if the browser reconnects mid-job (network
  hiccup, refresh), events may be split between connections. Fix requires
  a per-subscriber broadcast architecture.

## v1.2.0 — 2026-05-10

### Added
- **Web UI** (`audio-dl-ui`). One-page browser UI for downloads — paste URLs,
  pick a format, click Download, watch real-time progress, click to reveal
  the saved file in Finder. Parallel jobs (1–8) with a slider, whole-job
  Cancel button. Sets up the Phase-3 `.app` bundle.
- Optional `progress_hooks` parameter on `download_media` (used by the UI;
  CLI behavior unchanged).
- `[project.optional-dependencies] ui = ["fastapi", "uvicorn[standard]"]` —
  install with `pipx install 'audio-dl[ui]'`.

### Changed
- `pyproject.toml`: `py-modules = ["audio_dl", "audio_dl_ui"]`; new
  `audio-dl-ui` script entry.

## [1.1.0] - 2026-05-10

### Added
- **mp4 video format** — pass `-f mp4` to download video+audio merged into a single file (default remains audio extraction)

### Changed
- Extracted pure `_build_ydl_opts` function — yt-dlp options-dict construction is now testable without a live network call
- Renamed `download_audio` → `download_media` (and `audio_format` → `media_format`) to reflect the broader scope; the format string is now the single source of truth for the output pipeline

## [1.0.0] - 2026-05-04

### Added
- **Bunny Stream support** — detects and downloads from `mediadelivery.net` URLs; preserves `token`/`expires` params for access-controlled videos
- **`--cookies` flag** — accept a Netscape-format cookies.txt file for gated content on any site
- **`--fragments N` flag** — parallel fragment downloads per track for faster DASH/HLS streams (default: 4)
- **`-j N` / `--jobs N` flag** — download multiple URLs in parallel
- **`--force` flag** — overwrite existing files (default: skip)
- **`pyproject.toml`** — installable via `pipx install .`; provides `audio-dl` command
- **`--version` flag** — prints version and exits
- **CI** — GitHub Actions running pylint and pytest across Python 3.10–3.13 on every push and PR
- **Dependabot** — weekly auto-PRs for yt-dlp dependency updates
- **MIT license**

### Changed
- URL sanitization now strips shell backslash escapes and tracking params for YouTube and SoundCloud
- WAV output skips thumbnail embedding (WAV containers do not support embedded art)
- README updated with badge dashboard, pipx install instructions, and full usage examples
