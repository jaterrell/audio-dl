#!/usr/bin/env python3
"""
audio_dl.py — Download high-quality audio from YouTube, SoundCloud, and
anywhere else yt-dlp supports.

Usage:
    python audio_dl.py <url> [<url> ...] [--format mp3|m4a|flac|alac|opus|wav] [--output DIR]
    python audio_dl.py <url> --cookies-from-browser chrome   # pull live cookies from browser
    python audio_dl.py <url> --cookies cookies.txt           # Netscape cookies file
    python audio_dl.py <url> --sc-auth <token>               # SoundCloud OAuth token
    python audio_dl.py <playlist_url> --playlist

Credentials for gated / access-controlled content:
    --cookies-from-browser BROWSER  Use cookies from chrome/safari/firefox/edge (most sites)
    --cookies FILE                  Netscape-format cookies.txt exported from a browser
    --sc-auth TOKEN                 SoundCloud Go+/private tracks (OAuth token from DevTools)
    Bunny Stream token URLs         Pass the full URL with ?token=…&expires=…
                                    (sanitize_url preserves these automatically)

Requirements:
    pip install yt-dlp
    ffmpeg must be installed (for post-processing / conversion)
"""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import importlib.util
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, urlencode


def detect_platform(url: str) -> str:
    """Identify the source platform from the URL: youtube, soundcloud, bunnystream, or unknown."""
    hostname = urlparse(url).hostname or ""
    if "youtube.com" in hostname or "youtu.be" in hostname:
        return "youtube"
    if "soundcloud.com" in hostname:
        return "soundcloud"
    if hostname == "mediadelivery.net" or hostname.endswith(".mediadelivery.net"):
        return "bunnystream"
    return "unknown"


def sanitize_url(url: str) -> str:
    """
    Strip backslash escapes the shell may have injected and normalize
    the URL so yt-dlp receives a clean link. Handles YouTube, SoundCloud,
    and Bunny Stream (mediadelivery.net) URLs specially; others pass through.
    """
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
        qs = parse_qs(parsed.query)
        # Keep secret_token if present (needed for private tracks)
        clean_params = {}
        if "secret_token" in qs:
            clean_params["secret_token"] = qs["secret_token"][0]
        query = f"?{urlencode(clean_params)}" if clean_params else ""
        return f"https://soundcloud.com{parsed.path}{query}"

    # Bunny Stream — the path carries all identity info (library_id + video guid);
    # player-UI params are stripped; token/expires are preserved for access-controlled videos.
    if hostname == "mediadelivery.net" or hostname.endswith(".mediadelivery.net"):
        qs = parse_qs(parsed.query)
        clean_params = {}
        if "token" in qs:
            clean_params["token"] = qs["token"][0]
        if "expires" in qs:
            clean_params["expires"] = qs["expires"][0]
        query = f"?{urlencode(clean_params)}" if clean_params else ""
        return f"https://{parsed.hostname}{parsed.path}{query}"

    return url


def check_dependencies():
    """Verify yt-dlp and ffmpeg are available."""
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg is not installed or not on PATH.")
        print("  macOS:   brew install ffmpeg")
        print("  Ubuntu:  sudo apt install ffmpeg")
        print("  Windows: https://ffmpeg.org/download.html")
        sys.exit(1)

    if importlib.util.find_spec("yt_dlp") is None:
        print("ERROR: yt-dlp is not installed.")
        print("  Install it with:  pip install yt-dlp")
        sys.exit(1)


def _collect_final_paths(info: dict) -> list[str]:
    """
    Pull the final post-processed filepaths out of a yt-dlp info dict.
    Handles both single-video and playlist shapes.
    """
    requested = list(info.get("requested_downloads") or [])
    for entry in info.get("entries") or []:
        if isinstance(entry, dict):
            requested.extend(entry.get("requested_downloads") or [])
    return [r["filepath"] for r in requested if r.get("filepath")]


def download_audio(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches
    url: str,
    audio_format: str = "mp3",
    output_dir: str = ".",
    sc_auth: str | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
    playlist: bool = False,
    force: bool = False,
    concurrent_fragments: int = 4,
) -> list[str]:
    """
    Download the best audio stream(s) from a URL and convert to the
    requested format. Returns the list of saved file paths (one entry
    for a single track, many for a playlist). Empty list means failure.
    """
    import yt_dlp  # pylint: disable=import-outside-toplevel

    os.makedirs(output_dir, exist_ok=True)

    platform = detect_platform(url)
    platform_label = platform.capitalize() if platform != "unknown" else "URL"

    # Template for the output filename (sanitized title). Playlist mode
    # groups each track under its playlist's folder.
    if playlist:
        outtmpl = os.path.join(output_dir, "%(playlist_title)s", "%(title)s.%(ext)s")
    else:
        outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    postprocessor = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": audio_format,
    }
    if audio_format == "mp3":
        postprocessor["preferredquality"] = "320"   # max CBR for mp3
    elif audio_format == "m4a":
        postprocessor["preferredquality"] = "256"   # high AAC
    # flac / alac / wav are lossless; opus keeps source bitrate.

    postprocessors = [
        postprocessor,
        {"key": "FFmpegMetadata", "add_metadata": True},
    ]
    # WAV containers don't support embedded artwork; skip thumbnail work
    # entirely to avoid leftover .jpg/.webp files.
    embed_art = audio_format != "wav"
    if embed_art:
        postprocessors.append({"key": "EmbedThumbnail"})

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": not playlist,
        "quiet": False,
        "no_warnings": False,
        "writethumbnail": embed_art,
        "postprocessors": postprocessors,
        "keepvideo": False,
        "concurrent_fragment_downloads": concurrent_fragments,
    }
    if force:
        ydl_opts["overwrites"] = True

    # SoundCloud OAuth token (needed for some Go+ / gated tracks).
    # yt-dlp has no dedicated option for this — set the header directly.
    if sc_auth and platform == "soundcloud":
        ydl_opts["http_headers"] = {"Authorization": f"OAuth {sc_auth}"}
    if cookies:
        ydl_opts["cookiefile"] = cookies
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)

    fmt_label = "ALAC (.m4a)" if audio_format == "alac" else audio_format.upper()
    mode = "playlist" if playlist else "single track"
    print(f"\n[{platform_label}] Fetching {mode} from: {url}")
    print(f"Format: {fmt_label}  |  Output dir: {os.path.abspath(output_dir)}\n")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        print(f"\n✖  Download failed: {e}")
        return []

    paths = _collect_final_paths(info)
    if not paths:
        print("\n⚠  Download succeeded but yt-dlp reported no output path.")
        return []

    saved = []
    for p in paths:
        if not os.path.isfile(p):
            print(f"⚠  Expected output missing: {p}")
            continue
        size_mb = os.path.getsize(p) / (1024 * 1024)
        print(f"✔  Saved: {p}  ({size_mb:.1f} MB)")
        saved.append(p)
    return saved


def main():
    """Parse CLI arguments and run downloads."""
    parser = argparse.ArgumentParser(
        description="Download high-quality audio from YouTube, SoundCloud, "
                    "or any other site yt-dlp supports."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("urls", nargs="+", help="One or more source URLs")
    parser.add_argument(
        "-f", "--format",
        choices=["mp3", "m4a", "flac", "alac", "opus", "wav"],
        default="mp3",
        help="Audio format (default: mp3 @ 320 kbps). Use 'alac' for Apple Lossless.",
    )
    parser.add_argument(
        "-o", "--output", default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--playlist", action="store_true",
        help="Download the full playlist (default: single track only). "
             "Saves under <output>/<playlist_title>/.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing files (default: skip if already present).",
    )
    parser.add_argument(
        "--cookies", default=None, metavar="FILE",
        help="Path to a Netscape-format cookies.txt for gated content.",
    )
    parser.add_argument(
        "--cookies-from-browser", default=None, metavar="BROWSER",
        help="Pull cookies from a local browser (chrome, safari, firefox, edge, ...).",
    )
    parser.add_argument(
        "--sc-auth", default=None, metavar="TOKEN",
        help="SoundCloud OAuth token (alternative to --cookies for gated tracks).",
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=1, metavar="N",
        help="Number of URLs to download in parallel (default: 1). "
             "Use -j4 for batch downloads.",
    )
    parser.add_argument(
        "--fragments", type=int, default=4, metavar="N",
        help="Parallel fragment downloads per track (default: 4). "
             "Higher values speed up DASH/HLS streams on fast connections.",
    )
    args = parser.parse_args()

    check_dependencies()

    def _download_one(url: str) -> tuple[str, list[str]]:
        clean_url = sanitize_url(url)
        if clean_url != url:
            print(f"Sanitized URL → {clean_url}")
        saved = download_audio(
            clean_url,
            audio_format=args.format,
            output_dir=args.output,
            sc_auth=args.sc_auth,
            cookies=args.cookies,
            cookies_from_browser=args.cookies_from_browser,
            playlist=args.playlist,
            force=args.force,
            concurrent_fragments=args.fragments,
        )
        return url, saved

    any_failed = False
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(_download_one, url): url for url in args.urls}
        for future in as_completed(futures):
            url, saved = future.result()
            if saved:
                for p in saved:
                    print(f"  → file://{os.path.abspath(p)}")
            else:
                any_failed = True

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
