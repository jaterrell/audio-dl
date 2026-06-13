# Third-party notices

audio-dl is MIT-licensed (see [LICENSE](LICENSE)). The following components
are bundled or otherwise distributed alongside it and carry their own
licenses.

## Embedded ffmpeg binary (macOS `.app` bundle only)

The macOS `.app` bundle includes a statically-linked `ffmpeg` binary from
the [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) project
so consumers don't need a separate Homebrew install. The binary is **only**
present in `dist/audio-dl.app` — `pipx install audio-dl` and
`pipx install 'audio-dl[ui]'` do not pull it in.

| Component | License | Source |
|---|---|---|
| `imageio-ffmpeg` wrapper | BSD 2-Clause | https://github.com/imageio/imageio-ffmpeg |
| `ffmpeg` static binary | LGPLv2.1+ ([LICENSES/ffmpeg-LGPL-2.1.txt](LICENSES/ffmpeg-LGPL-2.1.txt)) | https://ffmpeg.org/ — source: https://ffmpeg.org/download.html |
| `mutagen` (Python) | GPLv2+ ([LICENSES/mutagen-GPL-2.0.txt](LICENSES/mutagen-GPL-2.0.txt)) | https://github.com/quodlibet/mutagen |

The bundled `ffmpeg` is invoked as a subprocess (no static linking against
audio-dl's own code). To satisfy LGPL distribution requirements, the full
LGPLv2.1 license text is bundled at `LICENSES/ffmpeg-LGPL-2.1.txt`, and
the ffmpeg source for the exact version is available at the URL above. If
you'd like a tarball of the matching source release dropped into a
specific channel, open an issue and we'll cooperate.

`mutagen` (GPL-2.0-or-later) is bundled into the `.app` as Python bytecode
(v2.1.2+). yt-dlp uses it to embed cover art and metadata in pure Python,
which is why the bundle doesn't need `ffprobe` (see below). To satisfy GPL
distribution requirements the full GPLv2 text is at
`LICENSES/mutagen-GPL-2.0.txt`; corresponding source for the exact version
is at the URL above and on PyPI (`pip download mutagen==<version>`). Open
an issue for a source tarball in a specific channel and we'll cooperate.

### What's NOT bundled

`ffprobe` is not included — imageio-ffmpeg only ships `ffmpeg`. The audio
flows that would otherwise shell out to `ffprobe` (embedding thumbnails and
metadata) instead go through the bundled **mutagen**, which does it in pure
Python. Some niche yt-dlp paths (advanced format inspection, certain
extractor metadata) still invoke ffprobe; users hitting those should install
ffmpeg via Homebrew, which provides both binaries.

> Note: v2.1.0 and v2.1.1 shipped without mutagen and so hit the ffprobe
> fallback, making every download fail at the embed step. Fixed in v2.1.2 by
> bundling mutagen. The regression guard is `test_bundle_ships_mutagen`.

## Runtime dependencies (not bundled)

These are pulled in by `pip` / `pipx` and licensed by their respective
maintainers; audio-dl just imports them.

- `yt-dlp` — Unlicense
- `fastapi`, `starlette`, `pydantic` (UI extra) — MIT / BSD
- `uvicorn` (UI extra) — BSD
- `imageio-ffmpeg` (app extra; bundle build time) — BSD 2-Clause

## Build-time tools (not redistributed)

- `PyInstaller` — GPLv2 with bootloader exception (the exception explicitly
  permits redistribution of the bundled output under any license).
