# audio-dl

Project guidance copied and adapted from `CLAUDE.md` and `.claude/settings.json`
for Codex use.

## Layout

- `audio_dl.py` is the CLI entry point; `main()` owns argument parsing.
- `audio_dl_ui.py` is the optional FastAPI/uvicorn web UI and should keep UI
  dependencies behind the `[ui]` extra.
- `_app_entry.py` is the PyInstaller shim used by the macOS `.app` bundle;
  it strips Finder argv and fixes `PATH` before calling `audio_dl_ui:main`.
- `audio-dl.spec` and `scripts/build-app.sh` drive the `.app` build
  (PyInstaller + ad-hoc codesign, macOS-only). The spec reads
  `__version__` from `audio_dl.py` so version stays dual-sourced only.
- `requirements.txt` intentionally stays minimal; runtime CLI dependency is
  `yt-dlp`, with `ffmpeg` expected on `PATH` (the `.app` bundles ffmpeg via
  `imageio-ffmpeg`).
- Tests live in `test_audio_dl.py` and `test_audio_dl_ui.py`.

Important CLI seams:

- `AUDIO_FORMATS`, `VIDEO_FORMATS`, and `ALL_FORMATS` are the source of truth
  for output pipeline selection.
- `sanitize_url` normalizes YouTube, SoundCloud, and Bunny Stream URLs while
  preserving access-control params such as SoundCloud `secret_token` and Bunny
  Stream `token` / `expires`.
- `_build_ydl_opts` is pure, does no I/O, and should remain easy to unit test.
- `_check_dependencies` is the pure dep-check seam; `check_dependencies`
  is the CLI wrapper that prints and exits.
- `_find_ffmpeg` prefers the bundled `imageio_ffmpeg.get_ffmpeg_exe()` over
  PATH so the `.app` ships self-contained ffmpeg.
- `_collect_final_paths` handles final output paths for single videos and
  playlists.

## Commands

First-time setup requires Python 3.10 or newer:

```bash
pip install -r requirements.txt
pip install -e '.[ui]'   # only when UI dependencies are needed
```

Common checks:

```bash
pytest -q
pylint $(git ls-files '*.py')
python3 -m py_compile audio_dl.py audio_dl_ui.py
python3 audio_dl.py --help
audio-dl-ui --help
```

## Conventions

- Prefer letting `yt-dlp` do the download and conversion work. Only call
  `ffmpeg` directly when `yt-dlp` cannot express the behavior.
- Format strings drive the pipeline. Do not add separate audio/video booleans;
  `--format mp4` is the video path and audio formats extract audio.
- Adding a video container means updating `VIDEO_FORMATS` and verifying
  ffmpeg and thumbnail/postprocessor behavior.
- `--sc-auth` sets `Authorization: OAuth <token>` through `http_headers`;
  yt-dlp has no dedicated SoundCloud option.
- WAV output skips thumbnail embedding because WAV containers do not support
  embedded art and leftover images would accumulate.
- Keep credentials for gated content in the CLI path. The UI intentionally does
  not expose cookies or SoundCloud OAuth controls.
- Keep the project as small top-level modules rather than introducing a package
  layout or framework structure without a clear need.

## Release Notes

- Version is dual-sourced in `audio_dl.py` (`__version__`) and
  `pyproject.toml` (`version`). Always bump both together.
- Release changes normally touch only `audio_dl.py`, `pyproject.toml`, and
  `CHANGELOG.md`.
- Before drafting a changelog entry, verify the old versions match and run
  `pytest -q` plus `pylint $(git ls-files '*.py')`.
- Draft changelog entries from commit subjects since the last tag, grouped as
  Added / Changed / Fixed, then stop before commit, tag, or push unless the
  user explicitly asks for those git operations.
