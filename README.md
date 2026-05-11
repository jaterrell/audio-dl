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

Paste URLs, pick a format, click Download. Live progress per URL, parallel
jobs slider (1–8), whole-job Cancel, click to reveal saved files in Finder.

```bash
audio-dl-ui --port 9000              # custom port
audio-dl-ui --output-dir ~/Music     # change the default output dir shown
audio-dl-ui --no-browser             # don't auto-open the browser
```

Bind defaults to `127.0.0.1` — no network exposure. Credentials for gated
content (cookies, SoundCloud OAuth) aren't surfaced in the UI; use the CLI
for those.
