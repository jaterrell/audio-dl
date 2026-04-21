# audio-dl

Download high-quality audio from YouTube or SoundCloud.

## Requirements

- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (pip)
- [`ffmpeg`](https://ffmpeg.org/) (system)

## Install

```
pip install -r requirements.txt
```

## Usage

```
python audio_dl.py <url> [--format mp3|m4a|flac|alac|opus|wav] [--output DIR]
python audio_dl.py <soundcloud_url> --sc-auth TOKEN
```
