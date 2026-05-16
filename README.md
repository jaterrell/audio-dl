# audio-dl

[![Tests](https://github.com/jaterrell/audio-dl/actions/workflows/tests.yml/badge.svg)](https://github.com/jaterrell/audio-dl/actions/workflows/tests.yml)
[![Pylint](https://github.com/jaterrell/audio-dl/actions/workflows/pylint.yml/badge.svg)](https://github.com/jaterrell/audio-dl/actions/workflows/pylint.yml)

Download high-quality audio (or video) from YouTube, SoundCloud, and any other site yt-dlp supports.

## Intended use

This tool is a frontend to [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) for **personal, non-commercial use**:

- Archiving content you own, created, or have explicit permission to download.
- Saving content explicitly made available for offline use.
- Educational or research use.

You are responsible for complying with the terms of service of any platform you access. Do not use this tool to redistribute, sell, or commercially exploit content you don't own.

audio-dl does not host any content, does not bypass DRM, does not decrypt protected streams, and provides no warranty (see [LICENSE](LICENSE)). It is a thin wrapper around yt-dlp's existing capabilities — the same legal considerations apply.

If you represent a content platform with concerns about specific usage patterns: audio-dl is content-agnostic infrastructure and does not target or assist circumvention of any specific service's protections. Please open an issue and we'll cooperate in good faith.

## Requirements

- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (pip)
- [`ffmpeg`](https://ffmpeg.org/) (system)

## Install

```
pip install -r requirements.txt
```

Or install as a command with [pipx](https://pipx.pypa.io/):

```
pipx install .
```

## Usage

```
python audio_dl.py <url> [<url> ...] [--format mp3|m4a|flac|alac|opus|wav|mp4] [--output DIR]
python audio_dl.py <url> --cookies-from-browser chrome    # gated content (pull live cookies)
python audio_dl.py <url> --cookies cookies.txt            # gated content (Netscape cookies file)
python audio_dl.py <url> --sc-auth TOKEN                  # SoundCloud Go+/private tracks
python audio_dl.py <playlist_url> --playlist              # full playlist
python audio_dl.py <url1> <url2> -j4                      # 4 URLs in parallel
python audio_dl.py <url> --format mp4                     # download video instead of audio
python audio_dl.py <url> --force                          # re-download existing files
python audio_dl.py <url> --fragments 8                    # 8 parallel fragments per track
```

`--format` is the single switch for output type. Audio formats (`mp3`, `m4a`, `flac`, `alac`, `opus`, `wav`) extract the audio stream; video formats (`mp4`) merge bestvideo+bestaudio into a single file. Default is mp3 @ 320 kbps. If installed via `pipx install .`, use `audio-dl` in place of `python audio_dl.py`.

## Web UI (optional)

Prefer a browser to a terminal? Install the UI extra and run the launcher:

```bash
pipx install 'audio-dl[ui]'   # or: pip install '.[ui]'
audio-dl-ui                   # opens http://127.0.0.1:8000 in your browser
```

Paste URLs, pick a format, click Download. Each URL becomes a card
showing its thumbnail, title, uploader, duration, live speed/ETA/bytes,
and the last few lines of yt-dlp output. 10 themes (toggle in the
header), parallel jobs slider (1–8), whole-job Cancel, click to reveal
saved files in Finder.

```bash
audio-dl-ui --port 9000              # custom port
audio-dl-ui --output-dir ~/Music     # change the default output dir shown
audio-dl-ui --no-browser             # don't auto-open the browser
```

Bind defaults to `127.0.0.1` — no network exposure. Credentials for gated
content (cookies, SoundCloud OAuth) aren't surfaced in the UI; use the CLI
for those.

## macOS `.app` bundle

Build a double-clickable `.app` that launches the web UI with no terminal
window. `ffmpeg` is embedded — no Homebrew install required.

```bash
python -m pip install -e '.[ui,app]'   # one-time (UI deps + imageio-ffmpeg)
python -m pip install pyinstaller      # one-time
scripts/build-app.sh                   # produces dist/audio-dl.app (~95 MB)
open dist/audio-dl.app
```

**Caveats:**

- **Unsigned.** macOS Gatekeeper will block first launch on a Mac that
  didn't build it. Workaround: right-click the bundle → Open, or run
  `xattr -d com.apple.quarantine dist/audio-dl.app` once. Developer-ID
  signing + notarization is a future phase.
- **macOS only** for now. PyInstaller can target Windows/Linux too, but
  the build script and `Info.plist` are macOS-specific.

### Installing a release build

If you don't want to build the bundle yourself, download a prebuilt
release from the [Releases page](https://github.com/jaterrell/audio-dl/releases).
Each release ships an Apple Silicon (`arm64`) zip with the `.app` and a
first-launch instructions file inside.

Full step-by-step including the Gatekeeper workaround is in
[INSTALL.md](INSTALL.md).

Intel Mac users: build from source via the instructions above. There is
no x86_64 prebuilt bundle yet.

The bundle ships a statically-linked LGPL `ffmpeg` from
[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg). The companion
`ffprobe` binary is **not** bundled — common yt-dlp audio/video flows
work fine without it (verified for mp3 + mp4), but some advanced extractor
paths invoke ffprobe and would need a full Homebrew install. See
[NOTICE.md](NOTICE.md) for full third-party attribution and the bundled
LGPL text at [LICENSES/ffmpeg-LGPL-2.1.txt](LICENSES/ffmpeg-LGPL-2.1.txt).
