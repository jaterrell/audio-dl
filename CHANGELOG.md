# Changelog

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
