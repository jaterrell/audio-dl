# Changelog

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
