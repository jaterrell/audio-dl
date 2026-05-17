# Changelog

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
