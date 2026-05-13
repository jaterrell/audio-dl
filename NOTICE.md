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

The bundled `ffmpeg` is invoked as a subprocess (no static linking against
audio-dl's own code). To satisfy LGPL distribution requirements, the full
LGPLv2.1 license text is bundled at `LICENSES/ffmpeg-LGPL-2.1.txt`, and
the ffmpeg source for the exact version is available at the URL above. If
you'd like a tarball of the matching source release dropped into a
specific channel, open an issue and we'll cooperate.

### What's NOT bundled

`ffprobe` is not included — imageio-ffmpeg only ships `ffmpeg`. yt-dlp's
common audio-extract and video-merge flows don't require ffprobe and
work fine inside the bundle (verified end-to-end with `mp3` and `mp4`
downloads on a stripped `PATH`). Some niche yt-dlp paths (advanced format
inspection, certain extractor metadata) do invoke ffprobe; users hitting
those should install ffmpeg via Homebrew, which provides both binaries.

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
