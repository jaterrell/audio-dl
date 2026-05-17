#!/usr/bin/env python3
"""
audio_dl.py — Download high-quality audio (or video) from YouTube,
SoundCloud, and anywhere else yt-dlp supports.

The output format chosen via ``--format`` decides everything: audio
formats (mp3, m4a, flac, alac, opus, wav) extract the audio stream;
video formats (mp4) merge bestvideo+bestaudio into a single file.

Usage:
    python audio_dl.py <url> [<url> ...] [--format mp3|m4a|flac|alac|opus|wav|mp4] [--output DIR]
    python audio_dl.py <url> --cookies-from-browser chrome   # pull live cookies from browser
    python audio_dl.py <url> --cookies cookies.txt           # Netscape cookies file
    python audio_dl.py <url> --sc-auth <token>               # SoundCloud OAuth token
    python audio_dl.py <playlist_url> --playlist
    python audio_dl.py <url> --format mp4                    # download video instead of audio

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

__version__ = "1.7.1"

import argparse
from collections.abc import Callable
import importlib.util
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, urlencode


def _host_matches(hostname: str, *domains: str) -> bool:
    """Return True if hostname is exactly one of *domains or a subdomain of one."""
    return any(hostname == d or hostname.endswith("." + d) for d in domains)


def detect_platform(url: str) -> str:
    """Identify the source platform from the URL: youtube, soundcloud, bunnystream, or unknown."""
    hostname = urlparse(url).hostname or ""
    if _host_matches(hostname, "youtube.com", "youtu.be"):
        return "youtube"
    if _host_matches(hostname, "soundcloud.com"):
        return "soundcloud"
    if _host_matches(hostname, "mediadelivery.net"):
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
    if _host_matches(hostname, "youtube.com", "youtu.be"):
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
    if _host_matches(hostname, "soundcloud.com"):
        qs = parse_qs(parsed.query)
        # Keep secret_token if present (needed for private tracks)
        clean_params = {}
        if "secret_token" in qs:
            clean_params["secret_token"] = qs["secret_token"][0]
        query = f"?{urlencode(clean_params)}" if clean_params else ""
        return f"https://soundcloud.com{parsed.path}{query}"

    # Bunny Stream — the path carries all identity info (library_id + video guid);
    # player-UI params are stripped; token/expires are preserved for access-controlled videos.
    if _host_matches(hostname, "mediadelivery.net"):
        qs = parse_qs(parsed.query)
        clean_params = {}
        if "token" in qs:
            clean_params["token"] = qs["token"][0]
        if "expires" in qs:
            clean_params["expires"] = qs["expires"][0]
        query = f"?{urlencode(clean_params)}" if clean_params else ""
        return f"https://{parsed.hostname}{parsed.path}{query}"

    return url


def _find_ffmpeg() -> str | None:
    """Locate an ffmpeg binary, preferring the bundled one over ``PATH``.

    Returns the absolute path to a usable ffmpeg, or ``None`` if none found.

    Resolution order:

    1. ``imageio_ffmpeg.get_ffmpeg_exe()`` if the package is importable. This is
       the path the macOS ``.app`` bundle uses — the binary is shipped inside
       the .app via PyInstaller's ``collect_data_files``, so consumers don't
       need ``brew install ffmpeg``.
    2. ``shutil.which("ffmpeg")`` — the user's own install (Homebrew, apt,
       a venv-local copy, etc.). Power users running the CLI keep working.

    Pure-ish: imports and a single filesystem stat. No subprocess.
    """
    try:
        import imageio_ffmpeg  # pylint: disable=import-outside-toplevel
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        # get_ffmpeg_exe returns the binary path; double-check it exists and is
        # executable so a stale module install doesn't claim a non-existent file.
        if exe and os.path.isfile(exe) and os.access(exe, os.X_OK):
            return exe
    except (ImportError, AttributeError, RuntimeError, OSError):
        # ImportError: imageio_ffmpeg not installed (the CLI install path).
        # AttributeError: future imageio-ffmpeg API churn.
        # RuntimeError: imageio_ffmpeg.get_ffmpeg_exe() can raise this when the
        #   bundled binary can't be located (e.g. wheel without binary on
        #   a niche arch) — explicitly documented in their API.
        # OSError: filesystem checks (isfile/access) on a path with weird
        #   permissions or stat errors. We'd rather fall through than crash.
        pass
    return shutil.which("ffmpeg")


def _check_dependencies() -> list[str]:
    """Return human-readable problem lines for missing dependencies.

    Empty list means everything is present. Pure function: no stderr, no
    ``sys.exit``. GUI callers (the macOS ``.app`` bundle in particular) need
    to surface failures through a dialog instead of stdout/stderr, so the
    detection logic must be callable without side effects.

    First line of each problem is a one-sentence summary; subsequent lines
    are indented install hints intended for human reading.
    """
    problems: list[str] = []
    if _find_ffmpeg() is None:
        problems.append("ffmpeg is not installed or not on PATH.")
        problems.append("  macOS:   brew install ffmpeg")
        problems.append("  Ubuntu:  sudo apt install ffmpeg")
        problems.append("  Windows: https://ffmpeg.org/download.html")
    if importlib.util.find_spec("yt_dlp") is None:
        problems.append("yt-dlp is not installed.")
        problems.append("  Install it with:  pip install yt-dlp")
    return problems


def check_dependencies() -> None:
    """CLI dep check: print to stderr and ``sys.exit(1)`` if anything is missing."""
    problems = _check_dependencies()
    if not problems:
        return
    for line in problems:
        # Indented continuation lines pass through unchanged; summary lines
        # get the legacy "ERROR: " prefix so CLI output is byte-identical.
        print(line if line.startswith(" ") else f"ERROR: {line}")
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


AUDIO_FORMATS = ("mp3", "m4a", "flac", "alac", "opus", "wav")
VIDEO_FORMATS = ("mp4",)
ALL_FORMATS = AUDIO_FORMATS + VIDEO_FORMATS


def _build_ydl_opts(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches
    *,
    media_format: str,
    output_dir: str,
    playlist: bool,
    force: bool,
    concurrent_fragments: int,
    platform: str,
    sc_auth: str | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
    progress_hooks: list[Callable[[dict], None]] | None = None,
    ffmpeg_location: str | None = None,
    logger: object | None = None,
) -> dict:
    """
    Build the yt-dlp options dict for the requested media format.

    Pure: no I/O, no yt-dlp import. The format string is the single
    source of truth — audio formats trigger ``FFmpegExtractAudio``;
    video formats trigger video+audio merge into the chosen container.
    """
    # Template for the output filename (sanitized title). Playlist mode
    # groups each track under its playlist's folder.
    if playlist:
        outtmpl = os.path.join(output_dir, "%(playlist_title)s", "%(title)s.%(ext)s")
    else:
        outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    is_video = media_format in VIDEO_FORMATS

    if is_video:
        # Video mode: keep video stream, merge bestvideo+bestaudio into the
        # chosen container. mp4 supports embedded metadata + artwork.
        postprocessors = [
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail"},
        ]
        ydl_format = "bestvideo*+bestaudio/best"
        embed_art = True
    else:
        postprocessor = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": media_format,
        }
        if media_format == "mp3":
            postprocessor["preferredquality"] = "320"   # max CBR for mp3
        elif media_format == "m4a":
            postprocessor["preferredquality"] = "256"   # high AAC
        # flac / alac / wav are lossless; opus keeps source bitrate.

        postprocessors = [
            postprocessor,
            {"key": "FFmpegMetadata", "add_metadata": True},
        ]
        # WAV containers don't support embedded artwork; skip thumbnail work
        # entirely to avoid leftover .jpg/.webp files.
        embed_art = media_format != "wav"
        if embed_art:
            postprocessors.append({"key": "EmbedThumbnail"})
        ydl_format = "bestaudio/best"

    opts: dict = {
        "format": ydl_format,
        "outtmpl": outtmpl,
        "noplaylist": not playlist,
        "quiet": False,
        "no_warnings": False,
        "writethumbnail": embed_art,
        "postprocessors": postprocessors,
        "keepvideo": False,
        "concurrent_fragment_downloads": concurrent_fragments,
        # YouTube's JS challenge solver (introduced in yt-dlp's EJS work)
        # needs a JS runtime to compute the signature/n-challenge values.
        # Without a runtime OR a remote-fetched solver, yt-dlp falls back to
        # a degraded format pool (typically just opus webm, ~128kbps) and
        # emits "Signature solving failed" / "n challenge solving failed"
        # warnings on every YouTube download. Enabling ejs:github lets
        # yt-dlp fetch the official solver lib once per session and unlocks
        # the full format pool. Harmless for non-YouTube extractors.
        "remote_components": ["ejs:github"],
    }
    if is_video:
        opts["merge_output_format"] = media_format
    if force:
        opts["overwrites"] = True

    # SoundCloud OAuth token (needed for some Go+ / gated tracks).
    # yt-dlp has no dedicated option for this — set the header directly.
    if sc_auth and platform == "soundcloud":
        opts["http_headers"] = {"Authorization": f"OAuth {sc_auth}"}
    if cookies:
        opts["cookiefile"] = cookies
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if progress_hooks:
        opts["progress_hooks"] = progress_hooks
    if ffmpeg_location:
        # yt-dlp honours this both as the postprocessor binary path and as the
        # directory containing ffmpeg/ffprobe. Passing the binary path itself
        # works for both lookups on the supported yt-dlp range.
        opts["ffmpeg_location"] = ffmpeg_location
    if logger is not None:
        opts["logger"] = logger

    return opts


def _format_label(media_format: str) -> str:
    """Human-readable label for the format (used in console output)."""
    if media_format == "alac":
        return "ALAC (.m4a)"
    if media_format == "mp4":
        return "MP4 (video+audio)"
    return media_format.upper()


def download_media(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    url: str,
    media_format: str = "mp3",
    output_dir: str = ".",
    sc_auth: str | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
    playlist: bool = False,
    force: bool = False,
    concurrent_fragments: int = 4,
    progress_hooks: list[Callable[[dict], None]] | None = None,
    logger: object | None = None,
) -> list[str]:
    """
    Download from ``url`` in the requested ``media_format``.

    Audio formats (mp3, m4a, flac, alac, opus, wav) extract the audio
    stream. Video formats (mp4) merge bestvideo+bestaudio into the
    chosen container. Returns the list of saved file paths; an empty
    list means failure.
    """
    import yt_dlp  # pylint: disable=import-outside-toplevel

    os.makedirs(output_dir, exist_ok=True)

    platform = detect_platform(url)
    platform_label = platform.capitalize() if platform != "unknown" else "URL"

    ydl_opts = _build_ydl_opts(
        media_format=media_format,
        output_dir=output_dir,
        playlist=playlist,
        force=force,
        concurrent_fragments=concurrent_fragments,
        platform=platform,
        sc_auth=sc_auth,
        cookies=cookies,
        cookies_from_browser=cookies_from_browser,
        progress_hooks=progress_hooks,
        # Resolved once per call. Same lookup as _check_dependencies — if it
        # returns None we just don't set ffmpeg_location and yt-dlp will fall
        # back to PATH (which the dep check has already verified, or the user
        # bypassed the check via the API).
        ffmpeg_location=_find_ffmpeg(),
        logger=logger,
    )

    mode = "playlist" if playlist else "single track"
    print(f"\n[{platform_label}] Fetching {mode} from: {url}")
    print(f"Format: {_format_label(media_format)}  |  Output dir: {os.path.abspath(output_dir)}\n")

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
        description="Download high-quality audio (or video, with --format mp4) "
                    "from YouTube, SoundCloud, or any other site yt-dlp supports."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("urls", nargs="+", help="One or more source URLs")
    parser.add_argument(
        "-f", "--format",
        choices=list(ALL_FORMATS),
        default="mp3",
        help="Output format (default: mp3 @ 320 kbps). Audio: mp3, m4a, flac, "
             "alac (Apple Lossless), opus, wav. Video: mp4 (downloads "
             "video+audio merged into a single file).",
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
        saved = download_media(
            clean_url,
            media_format=args.format,
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
