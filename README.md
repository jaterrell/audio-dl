# audio-dl

[![Tests](https://github.com/jaterrell/audio-dl/actions/workflows/tests.yml/badge.svg)](https://github.com/jaterrell/audio-dl/actions/workflows/tests.yml)
[![Pylint](https://github.com/jaterrell/audio-dl/actions/workflows/pylint.yml/badge.svg)](https://github.com/jaterrell/audio-dl/actions/workflows/pylint.yml)

Download high-quality audio from YouTube, SoundCloud, Bunny Stream, or anywhere yt-dlp supports.

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
audio-dl <url> [--format mp3|m4a|flac|alac|opus|wav] [--output DIR]
audio-dl <url> --cookies-from-browser chrome    # gated content (pull live cookies)
audio-dl <url> --cookies cookies.txt            # gated content (Netscape cookies file)
audio-dl <url> --sc-auth TOKEN                  # SoundCloud Go+/private tracks
audio-dl <playlist_url> --playlist              # full playlist
audio-dl <url1> <url2> -j4                      # 4 URLs in parallel
```

Default format is mp3 @ 320 kbps. Use `python audio_dl.py` in place of `audio-dl` if running directly.
