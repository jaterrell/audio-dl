#!/usr/bin/env python3
"""
audio_dl.py — Download high-quality audio from YouTube or SoundCloud.

Usage:
    python audio_dl.py <url> [--format mp3|m4a|flac|alac|opus|wav] [--output DIR]
    python audio_dl.py <soundcloud_url> --sc-auth TOKEN

Supported sources:
    - YouTube    (youtube.com, youtu.be)
    - SoundCloud (soundcloud.com) — some tracks require OAuth token

Requirements:
    pip install yt-dlp
    ffmpeg must be installed (for post-processing / conversion)
"""

import argparse
import sys
import os
import shutil


def detect_platform(url: str) -> str:
    """Identify the source platform from the URL."""
    from urllib.parse import urlparse
    hostname = urlparse(url).hostname or ""
    if "youtube.com" in hostname or "youtu.be" in hostname:
        return "youtube"
    if "soundcloud.com" in hostname:
        return "soundcloud"
    return "unknown"


def sanitize_url(url: str) -> str:
    """
    Strip backslash escapes the shell may have injected and normalize
    the URL so yt-dlp receives a clean link.
    """
    from urllib.parse import urlparse, parse_qs, urlencode

    # Remove any backslashes (zsh / bash escape artifacts)
    url = url.replace("\\", "")

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # YouTube — rebuild cleanly to drop junk params
    if "youtube.com" in hostname or "youtu.be" in hostname:
        qs = parse_qs(parsed.query)
        path_parts = [p for p in parsed.path.split("/") if p]

        # Video ID lives in different places depending on URL shape:
        #   youtu.be/<id>, youtube.com/shorts/<id>, youtube.com/embed/<id>,
        #   youtube.com/watch?v=<id>
        video_id = None
        if "youtu.be" in hostname and path_parts:
            video_id = path_parts[0]
        elif path_parts and path_parts[0] in ("shorts", "embed", "live") and len(path_parts) > 1:
            video_id = path_parts[1]
        elif "v" in qs:
            video_id = qs["v"][0]

        if not video_id:
            # Not a recognizable single-video URL — hand it back untouched.
            return url

        clean_params = {"v": video_id}
        if "t" in qs:
            clean_params["t"] = qs["t"][0]
        if "list" in qs:
            clean_params["list"] = qs["list"][0]
        return f"https://www.youtube.com/watch?{urlencode(clean_params)}"

    # SoundCloud — strip tracking params, keep the path clean
    if "soundcloud.com" in hostname:
        # SoundCloud URLs are path-based: soundcloud.com/artist/track
        # Just strip query string junk (UTM params, si, etc.)
        qs = parse_qs(parsed.query)
        # Keep secret_token if present (needed for private tracks)
        clean_params = {}
        if "secret_token" in qs:
            clean_params["secret_token"] = qs["secret_token"][0]
        query = f"?{urlencode(clean_params)}" if clean_params else ""
        return f"https://soundcloud.com{parsed.path}{query}"

    return url


def check_dependencies():
    """Verify yt-dlp and ffmpeg are available."""
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg is not installed or not on PATH.")
        print("  macOS:   brew install ffmpeg")
        print("  Ubuntu:  sudo apt install ffmpeg")
        print("  Windows: https://ffmpeg.org/download.html")
        sys.exit(1)

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("ERROR: yt-dlp is not installed.")
        print("  Install it with:  pip install yt-dlp")
        sys.exit(1)


def download_audio(
    url: str,
    audio_format: str = "mp3",
    output_dir: str = ".",
    sc_auth: str | None = None,
) -> str:
    """
    Download the best audio stream from a YouTube or SoundCloud URL
    and convert it to the requested format. Returns the path to the saved file.
    """
    import yt_dlp

    os.makedirs(output_dir, exist_ok=True)

    platform = detect_platform(url)
    platform_label = platform.capitalize() if platform != "unknown" else "URL"

    # Template for the output filename (sanitized title)
    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    # ALAC is packaged in an m4a container; every other codec uses its own ext.
    ext_by_format = {
        "mp3": "mp3", "m4a": "m4a", "flac": "flac",
        "alac": "m4a", "opus": "opus", "wav": "wav",
    }
    dl_ext = ext_by_format[audio_format]

    postprocessor = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": audio_format,
    }
    if audio_format == "mp3":
        postprocessor["preferredquality"] = "320"   # max CBR for mp3
    elif audio_format == "m4a":
        postprocessor["preferredquality"] = "256"   # high AAC
    # flac / alac / wav are lossless; opus keeps source bitrate.

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "writethumbnail": True,
        "postprocessors": [
            postprocessor,
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail"},
        ],
        "keepvideo": False,
    }

    # SoundCloud OAuth token (needed for some Go+ / gated tracks).
    # yt-dlp has no dedicated option for this — set the header directly.
    if sc_auth and platform == "soundcloud":
        ydl_opts["http_headers"] = {"Authorization": f"OAuth {sc_auth}"}

    fmt_label = "ALAC (.m4a)" if audio_format == "alac" else audio_format.upper()
    print(f"\n[{platform_label}] Fetching audio from: {url}")
    print(f"Format: {fmt_label}  |  Output dir: {os.path.abspath(output_dir)}\n")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = ydl.prepare_filename(info)
        base, _ = os.path.splitext(title)
        final_path = f"{base}.{dl_ext}"

    # If the predicted path doesn't exist, look for a same-basename match.
    if not os.path.isfile(final_path):
        expected_base = os.path.basename(base)
        candidates = [
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir)
            if f.endswith(f".{dl_ext}") and os.path.splitext(f)[0] == expected_base
        ]
        if candidates:
            final_path = candidates[0]
        else:
            print("\n⚠  Download appeared to succeed but the output file was not found.")
            return ""

    if os.path.isfile(final_path):
        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        print(f"\n✔  Saved: {final_path}  ({size_mb:.1f} MB)")
        return final_path

    print("\n⚠  Download appeared to succeed but the output file was not found.")
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Download high-quality audio from YouTube or SoundCloud."
    )
    parser.add_argument("url", help="YouTube or SoundCloud URL")
    parser.add_argument(
        "-f", "--format",
        choices=["mp3", "m4a", "flac", "alac", "opus", "wav"],
        default="mp3",
        help="Audio format (default: mp3 @ 320 kbps). Use 'alac' for Apple Lossless.",
    )
    parser.add_argument(
        "-o", "--output",
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--sc-auth",
        default=None,
        help="SoundCloud OAuth token (required for Go+ / gated tracks)",
    )
    args = parser.parse_args()

    check_dependencies()
    clean_url = sanitize_url(args.url)
    if clean_url != args.url:
        print(f"Sanitized URL → {clean_url}")
    path = download_audio(
        clean_url,
        audio_format=args.format,
        output_dir=args.output,
        sc_auth=args.sc_auth,
    )

    if path:
        print(f"\nDone. File is ready at:\n  file://{os.path.abspath(path)}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
