"""Pure related-content discovery logic for the web UI.

Everything here is testable without network: providers go through the
single `_flat_extract` seam (added in a later task), and no function
touches FastAPI, JobState, or SSE. Integration glue lives in
``audio_dl_ui/__init__.py``.

Spec: docs/superpowers/specs/2026-07-01-related-content-discovery-design.md
"""
from __future__ import annotations

from urllib.parse import urlparse, urlunparse

SUPPORTED_PLATFORMS = frozenset({"youtube", "soundcloud"})
CROSS_PLATFORM = {"youtube": "soundcloud", "soundcloud": "youtube"}
MAX_ITEMS = 8
MAX_NATIVE_WITH_CROSS = 5
SEARCH_COUNT = 8

# Subdomain-safe suffixes; https-only enforced in is_allowed_thumb_url.
_THUMB_ALLOWED_SUFFIXES = ("i.ytimg.com", "sndcdn.com")


def _pick_thumbnail_url(info: dict) -> str | None:
    """Pick a reasonable thumbnail URL from a yt-dlp info dict.

    Prefers the largest thumbnail with width <= 480 (good for our 120px
    card thumbs without retina-blur). Falls back to the smallest width
    if none are <= 480, then the singular ``thumbnail`` field, then None.
    """
    thumbs = info.get("thumbnails") or []
    sized = [t for t in thumbs if isinstance(t.get("width"), int)]
    if sized:
        small = [t for t in sized if t["width"] <= 480]
        if small:
            chosen = max(small, key=lambda t: t["width"])
        else:
            chosen = min(sized, key=lambda t: t["width"])
        return chosen.get("url")
    if thumbs:
        return thumbs[0].get("url")
    return info.get("thumbnail") or None


def resolve_artist(info: dict) -> str | None:
    """artist → artists[0] → uploader → channel, stripping YouTube's auto
    ``" - Topic"`` channel suffix. Returns None when nothing usable."""
    artist = info.get("artist")
    if not artist:
        artists = info.get("artists")
        if isinstance(artists, list) and artists:
            artist = artists[0]
    artist = artist or info.get("uploader") or info.get("channel")
    if not isinstance(artist, str) or not artist.strip():
        return None
    artist = artist.strip()
    if artist.endswith(" - Topic"):
        artist = artist[: -len(" - Topic")].strip()
    return artist or None


def is_allowed_thumb_url(url: str) -> bool:
    """https-only + per-provider host allowlist (subdomain-safe suffix match).

    Guards the server-side thumbnail fetch: only CDN hosts we expect
    yt-dlp entries to reference may be contacted."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _THUMB_ALLOWED_SUFFIXES
    )


# 2026-07-04: Task-2's live probe of soundcloud.com/.../recommended (run
# 2026-07-03) returned bare url-stub entries — only `_type`/`ie_key`/`id`/
# `title`/`url`, no `webpage_url`/`uploader`/`duration`/`thumbnails` — so it
# doesn't match the shape the native path needs. Per the spec's gating
# pre-requisite, the SoundCloud native path ships disabled; SoundCloud seeds
# go through the cross-platform search path only. See SC_NATIVE_ENABLED in
# test_audio_dl_related.py and the design spec's "Open follow-ups".
SC_NATIVE_PATH_ENABLED = False


def build_native_query(seed: dict) -> str | None:
    """Platform-native related-content query for a seed, or None.

    youtube → the seed video's Mix (radio) playlist; soundcloud → the
    track's /recommended page. The Mix's first entry is the seed itself —
    ``select_items`` drops it via the seed-exclusion rule."""
    platform = seed.get("platform")
    if platform == "youtube" and seed.get("id"):
        vid = seed["id"]
        return f"https://www.youtube.com/watch?v={vid}&list=RD{vid}"
    if platform == "soundcloud" and SC_NATIVE_PATH_ENABLED and seed.get("webpage_url"):
        # Append "/recommended" to the *path*, not the whole URL. A seed
        # permalink can carry a query string (e.g. ?secret_token=… for a
        # private track); naive concatenation would yield
        # ".../track?secret_token=…/recommended", a broken URL. Parse, extend
        # the path, and reassemble so the query/fragment stay in place.
        parts = urlparse(seed["webpage_url"])
        return urlunparse(parts._replace(path=parts.path.rstrip("/") + "/recommended"))
    return None


def build_search_query(seed: dict) -> str | None:
    """Cross-platform same-artist search prefix query, or None without artist."""
    artist = seed.get("artist")
    platform = seed.get("platform")
    if not artist or platform not in CROSS_PLATFORM:
        return None
    prefix = "scsearch" if platform == "youtube" else "ytsearch"
    return f"{prefix}{SEARCH_COUNT}:{artist}"


def normalize_entry(entry: dict, platform: str) -> dict | None:
    """Normalize one flat-extraction entry to the wire item shape.

    Returns None for unusable entries (no title/id/linkable URL). For
    SoundCloud the ``url`` field is an api.soundcloud.com URL — only
    ``webpage_url`` (the human permalink) may be linked."""
    title = entry.get("title")
    if not title or not entry.get("id"):
        return None
    if platform == "youtube":
        webpage_url = entry.get("url") or entry.get("webpage_url")
    else:
        webpage_url = entry.get("webpage_url")
    if not webpage_url:
        return None
    duration = entry.get("duration")
    return {
        "id": str(entry["id"]),
        "title": title,
        "artist": resolve_artist(entry),
        "platform": platform,
        "webpage_url": webpage_url,
        "duration": int(duration) if isinstance(duration, (int, float)) else None,
        "thumb_id": None,
        "_thumb_src": _pick_thumbnail_url(entry),
    }


def select_items(seed: dict, native: list[dict], cross: list[dict]) -> list[dict]:
    """Allocate up to MAX_ITEMS slots: native first (capped at
    MAX_NATIVE_WITH_CROSS while cross results exist), cross fills the
    remainder, then native backfills if cross ran short. Drops the seed
    echo and dedupes by (platform, id)."""
    seen: set[tuple[str, str]] = {(str(seed.get("platform")), str(seed.get("id")))}
    out: list[dict] = []

    def _take(pool: list[dict], cap: int) -> None:
        for item in pool:
            if len(out) >= cap:
                return
            key = (item["platform"], item["id"])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)

    _take(native, MAX_NATIVE_WITH_CROSS if cross else MAX_ITEMS)
    _take(cross, MAX_ITEMS)
    _take(native, MAX_ITEMS)  # backfill when cross was short
    return out


def _flat_extract(query: str) -> dict:
    """The one real yt-dlp call — module-level so tests monkeypatch it.

    ``socket_timeout`` bounds individual socket operations, not total
    wall time (yt-dlp may retry internally); the caller's thumbnail-phase
    budget is the only hard bound. See the spec's Providers section."""
    import yt_dlp  # pylint: disable=import-outside-toplevel

    opts = {
        "extract_flat": True,
        "skip_download": True,
        "playlist_items": "1-10",
        "socket_timeout": 8,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(query, download=False) or {}


def discover(seed: dict) -> tuple[str, list[dict]]:
    """Run native + cross-platform providers for a seed.

    Returns ``(status, items)`` with status "ready" (>=1 item), "none"
    (providers ran, zero usable items), or "error" (every attempted
    provider raised). One provider failing while the other returns items
    is still "ready"."""
    native_q = build_native_query(seed)
    search_q = build_search_query(seed)
    attempted = 0
    errored = 0
    native: list[dict] = []
    cross: list[dict] = []

    if native_q:
        attempted += 1
        try:
            result = _flat_extract(native_q)
            native = [
                item for e in (result.get("entries") or [])
                if (item := normalize_entry(e, seed["platform"])) is not None
            ]
        except Exception:  # pylint: disable=broad-except
            errored += 1
    if search_q:
        attempted += 1
        try:
            result = _flat_extract(search_q)
            cross_platform = CROSS_PLATFORM[seed["platform"]]
            cross = [
                item for e in (result.get("entries") or [])
                if (item := normalize_entry(e, cross_platform)) is not None
            ]
        except Exception:  # pylint: disable=broad-except
            errored += 1

    items = select_items(seed, native, cross)
    if items:
        return ("ready", items)
    if attempted and errored == attempted:
        return ("error", [])
    return ("none", [])
