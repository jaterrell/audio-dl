# audio-dl

[![Tests](https://github.com/jaterrell/audio-dl/actions/workflows/tests.yml/badge.svg)](https://github.com/jaterrell/audio-dl/actions/workflows/tests.yml)
[![Pylint](https://github.com/jaterrell/audio-dl/actions/workflows/pylint.yml/badge.svg)](https://github.com/jaterrell/audio-dl/actions/workflows/pylint.yml)

Download high-quality audio (or video) from YouTube, SoundCloud, Bunny Stream, or anywhere yt-dlp supports.

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
