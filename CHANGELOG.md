# Changelog

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
