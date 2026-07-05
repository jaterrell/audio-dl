# Related-Content Discovery ("More like this") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a download job runs in the web UI, discover related tracks on YouTube + SoundCloud via yt-dlp, stream them over the existing SSE channel, and render a "More like this" thumbnail strip with link-out + one-click queue; results persist onto localStorage history so the idle stage keeps the strip after completion.

**Architecture:** Pure discovery logic lives in a new `audio_dl_ui/related.py` (query builders, entry normalization, selection — all testable without network via a `_flat_extract` seam). Integration glue in `audio_dl_ui/__init__.py` triggers discovery from the first info-dict progress-hook tick, runs it on a dedicated 2-worker executor, prefetches thumbnails into the existing persistent `/thumbs/` cache, emits one `url_related` SSE event per URL, and lingers the SSE stream ≤10 s after `job_completed` so late results still reach the client. The React client patches results into its react-query snapshot, upserts them onto `HistoryItem`s, and renders a `RelatedStrip` component under the hero stage and on the idle stage.

**Tech Stack:** Python 3.10+ / FastAPI / yt-dlp / httpx (all existing deps — **no new dependencies**); React 19 + TanStack Query + Vite/Vitest in `web/`.

**Spec:** `docs/superpowers/specs/2026-07-01-related-content-discovery-design.md` (approved; merged via #42 + #52). Read it before starting — the "Late results" section explains the trickiest mechanism.

## Global Constraints

- **Zero changes to `audio_dl.py`** except the `__version__` bump in the final task.
- **No new runtime dependencies, no new HTTP endpoints, no Vite proxy changes.**
- Python ≥3.10 (`X | None` unions OK). CI runs `pylint $(git ls-files '*.py')` with repo defaults (no pylintrc) — new module needs docstrings. In `test_audio_dl_related.py`, ALL module-level imports live in the single top-of-file block; later tasks EXTEND that block in place — appending a new `import`/`from` line after code trips pylint C0413 `wrong-import-position` and fails the gate.
- All network I/O in tests is mocked. Exactly ONE task (Task 2) performs a live probe, and it is a fixture-capture step, not a test.
- Item cap: **8 per URL**; native results capped at **5 while cross-platform results exist**, either side may fill all 8 when the other is short/empty/skipped.
- Timeouts: provider `socket_timeout: 8`; thumbnail fetch 5 s each, **15 s hard budget for the whole thumbnail phase**; SSE linger cap **10 s**; frontend linger cap **10 s**; visual teardown stays **1.5 s**.
- `related_status` contract: `None` (never started) | `"pending"` (task submitted) | `"ready"` / `"none"` / `"error"` / `"unsupported"`. Every exit path moves it off `"pending"`. Linger predicates key on `"pending"` **and** download `status == "completed"`, never on `None`.
- Discovery must never fail a download or a job: the in-hook trigger is wrapped in its own try/except; the task body is wrapped end-to-end.
- Thumb fetch hardening: `https` only, host allowlist (`i.ytimg.com`, `*.sndcdn.com`, subdomain-safe), `follow_redirects=False`, existing 5 MB cap.
- Frontend: theme tokens only (`var(--surface/--border/--text*/--accent/--on-accent/--radius-*)`), shared `Button`, `focus-ring` class on interactives, `enter-fade` for entrance, no new keyframes.
- Commit after every task with the message given in its final step.

---

### Task 1: `related.py` scaffold — `resolve_artist`, `is_allowed_thumb_url`, relocate `_pick_thumbnail_url`

**Files:**
- Create: `audio_dl_ui/related.py`
- Modify: `audio_dl_ui/__init__.py:218-236` (remove `_pick_thumbnail_url`, import it from `.related`)
- Create: `test_audio_dl_related.py`

**Interfaces:**
- Consumes: nothing (pure module; `yt_dlp` imported only in Task 4's `_flat_extract`).
- Produces: `resolve_artist(info: dict) -> str | None`; `is_allowed_thumb_url(url: str) -> bool`; `_pick_thumbnail_url(info: dict) -> str | None` (moved verbatim); constants `SUPPORTED_PLATFORMS`, `MAX_ITEMS = 8`, `MAX_NATIVE_WITH_CROSS = 5`, `SEARCH_COUNT = 8`, `CROSS_PLATFORM`. `audio_dl_ui.__init__` re-exports `_pick_thumbnail_url` so `test_audio_dl_ui.py`'s existing `from audio_dl_ui import _pick_thumbnail_url` keeps working.

- [ ] **Step 1: Write the failing tests**

Create `test_audio_dl_related.py`:

```python
# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
# pylint: disable=protected-access
"""Tests for audio_dl_ui.related — pure discovery logic, no network."""
import pytest

# Later tasks EXTEND this import block in place — never append a new
# module-level import after code below (pylint C0413 wrong-import-position).
from audio_dl_ui.related import (
    resolve_artist,
    is_allowed_thumb_url,
    _pick_thumbnail_url,
)


class TestResolveArtist:
    @pytest.mark.parametrize("info,expected", [
        ({"artist": "Daft Punk"}, "Daft Punk"),
        ({"artists": ["Daft Punk", "Pharrell"]}, "Daft Punk"),
        ({"uploader": "Rick Astley"}, "Rick Astley"),
        ({"channel": "a-ha"}, "a-ha"),
        ({"artist": None, "artists": [], "uploader": "U"}, "U"),
        ({"uploader": "Tycho - Topic"}, "Tycho"),
        ({"artist": "  "}, None),
        ({}, None),
        ({"artists": "not-a-list", "uploader": "U"}, "U"),
    ])
    def test_fallback_chain_and_topic_strip(self, info, expected):
        assert resolve_artist(info) == expected


class TestThumbHostAllowlist:
    @pytest.mark.parametrize("url,allowed", [
        ("https://i.ytimg.com/vi/x/hqdefault.jpg", True),
        ("https://i1.sndcdn.com/artworks-abc-t500x500.jpg", True),
        ("https://sndcdn.com/a.jpg", True),
        ("http://i.ytimg.com/vi/x/hqdefault.jpg", False),          # not https
        ("https://evil-i.ytimg.com.evil.test/x.jpg", False),       # suffix spoof
        ("https://ytimg.com.evil.test/x.jpg", False),
        ("https://example.com/x.jpg", False),
        ("not a url", False),
        ("", False),
    ])
    def test_allowlist(self, url, allowed):
        assert is_allowed_thumb_url(url) is allowed


class TestPickThumbnailUrlReExport:
    def test_moved_helper_still_picks_largest_at_most_480(self):
        info = {"thumbnails": [
            {"url": "a.jpg", "width": 168},
            {"url": "b.jpg", "width": 480},
            {"url": "c.jpg", "width": 1280},
        ]}
        assert _pick_thumbnail_url(info) == "b.jpg"

    def test_import_from_package_root_still_works(self):
        from audio_dl_ui import _pick_thumbnail_url as from_root
        assert from_root is _pick_thumbnail_url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_audio_dl_related.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_dl_ui.related'`

- [ ] **Step 3: Create `audio_dl_ui/related.py`**

```python
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
```

- [ ] **Step 4: Relocate `_pick_thumbnail_url` in `__init__.py`**

In `audio_dl_ui/__init__.py`, delete the entire `_pick_thumbnail_url` function (currently lines 218-236, from `def _pick_thumbnail_url(info: dict) -> str | None:` through `return info.get("thumbnail") or None`). Then add the package-internal import directly below the `from audio_dl import (...)` block (after line 53):

```python
from audio_dl_ui.related import _pick_thumbnail_url
from audio_dl_ui import related as _related
```

(`_related` is used from Task 6 onward; importing it now keeps this the only import-block edit.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest test_audio_dl_related.py -v && pytest test_audio_dl_ui.py -k "Thumbnail or PickThumbnail" -q`
Expected: all PASS (the existing `TestPickThumbnailUrl` class in `test_audio_dl_ui.py` still passes via the re-export).

- [ ] **Step 6: Commit**

```bash
git add audio_dl_ui/related.py audio_dl_ui/__init__.py test_audio_dl_related.py
git commit -m "feat(related): pure discovery module scaffold — artist resolution, thumb-host allowlist"
```

---

### Task 2: Gating prerequisite — live-probe SoundCloud `/recommended`, capture fixtures

**Files:**
- Modify: `test_audio_dl_related.py` (append fixture constants)

**Interfaces:**
- Produces: module-level fixture dicts in `test_audio_dl_related.py`: `YT_MIX_ENTRY`, `YT_SEARCH_ENTRY`, `SC_SEARCH_ENTRY`, `SC_RECOMMENDED_ENTRY`, plus `SC_NATIVE_ENABLED: bool`. Tasks 3-4 consume these.

**This is the spec's gating prerequisite.** The SoundCloud native path ships ONLY if this probe confirms `/recommended` flat entries match the `scsearch` shape. This step needs network; every other step in this plan is offline.

- [ ] **Step 1: Run the probe**

Run this script (it is throwaway — do NOT commit it):

```bash
python3 - <<'EOF'
import json, yt_dlp
OPTS = {"quiet": True, "no_warnings": True, "extract_flat": True,
        "skip_download": True, "playlist_items": "1-6", "socket_timeout": 8}
with yt_dlp.YoutubeDL(OPTS) as ydl:
    rel = ydl.extract_info(
        "https://soundcloud.com/daftpunkofficialmusic/one-more-time/recommended",
        download=False)
    entries = rel.get("entries") or []
    print(f"entries: {len(entries)}")
    for e in entries[:2]:
        keep = {k: e.get(k) for k in
                ("id", "title", "uploader", "artists", "duration",
                 "webpage_url", "url")}
        keep["thumbnails"] = (e.get("thumbnails") or [])[:3]
        print(json.dumps(keep, indent=2))
EOF
```

Expected: `entries:` ≥ 1 and each entry carries `id`, `title`, `webpage_url` (a `soundcloud.com/...` permalink), and a `thumbnails` list of `sndcdn.com` URLs.

- [ ] **Step 2: Record the outcome as fixtures**

**Branch A — probe succeeded (expected):** append to `test_audio_dl_related.py`, substituting real captured values for the `SC_RECOMMENDED_ENTRY` fields (keep the shape below; the exact title/id values don't matter as long as they're real):

```python
# ---------------------------------------------------------------------------
# Fixtures captured from live yt-dlp probes (2026-07-01 and this task's probe).
# These are REAL flat-extraction entry shapes — do not invent fields.
# ---------------------------------------------------------------------------

SC_NATIVE_ENABLED = True  # /recommended probe succeeded; native path ships

YT_MIX_ENTRY = {
    "_type": "url", "ie_key": "Youtube", "id": "PIb6AZdTr-A",
    "title": "Cyndi Lauper - Girls Just Want To Have Fun (Official Video)",
    "uploader": "Cyndi Lauper", "channel": "Cyndi Lauper",
    "duration": 267.0,
    "url": "https://www.youtube.com/watch?v=PIb6AZdTr-A",
    "thumbnails": [
        {"url": "https://i.ytimg.com/vi/PIb6AZdTr-A/hqdefault.jpg",
         "width": 168, "height": 94},
        {"url": "https://i.ytimg.com/vi/PIb6AZdTr-A/hqdefault.jpg",
         "width": 336, "height": 188},
    ],
}

YT_SEARCH_ENTRY = {
    "_type": "url", "ie_key": "Youtube", "id": "FGBhQbmPwH8",
    "title": "Daft Punk - One More Time (Official Video)",
    "uploader": "Daft Punk", "channel": "Daft Punk",
    "duration": 322.0, "view_count": 607694979,
    "url": "https://www.youtube.com/watch?v=FGBhQbmPwH8",
    "thumbnails": [
        {"url": "https://i.ytimg.com/vi/FGBhQbmPwH8/hq720.jpg",
         "width": 360, "height": 202},
    ],
}

SC_SEARCH_ENTRY = {
    "_type": "url", "ie_key": "Soundcloud", "id": "254112129",
    "title": "One More Time",
    "uploader": "Daft Punk", "artists": ["Daft Punk"],
    "duration": 320.38,
    "url": "https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A254112129",
    "webpage_url": "https://soundcloud.com/daftpunkofficialmusic/one-more-time",
    "thumbnails": [
        {"url": "https://i1.sndcdn.com/artworks-9K96MSC0MPxz-0-mini.jpg",
         "width": 16, "height": 16},
        {"url": "https://i1.sndcdn.com/artworks-9K96MSC0MPxz-0-t500x500.jpg",
         "width": 500, "height": 500},
    ],
}

# Captured by this task's probe — replace field values with real output:
SC_RECOMMENDED_ENTRY = {
    "_type": "url", "ie_key": "Soundcloud", "id": "<captured id>",
    "title": "<captured title>",
    "uploader": "<captured uploader>", "artists": ["<captured artist>"],
    "duration": 123.4,
    "url": "https://api.soundcloud.com/tracks/<captured>",
    "webpage_url": "https://soundcloud.com/<captured permalink>",
    "thumbnails": [
        {"url": "https://i1.sndcdn.com/<captured>-t500x500.jpg", "width": 500},
    ],
}
```

**Branch B — probe failed or shape mismatched (no `webpage_url`, no entries, extractor error):** set `SC_NATIVE_ENABLED = False`, set `SC_RECOMMENDED_ENTRY = SC_SEARCH_ENTRY` (placeholder so imports resolve), and in Task 3's `build_native_query` the soundcloud branch must `return None` with a comment `# /recommended probe failed <date>; native path deferred — see spec follow-ups`. Also add a line to the spec's "Open follow-ups" section in the same commit. All later tasks then rely on `SC_NATIVE_ENABLED` guards already written into their tests.

- [ ] **Step 3: Commit**

```bash
git add test_audio_dl_related.py
git commit -m "test(related): capture live flat-extraction fixtures; gate SoundCloud native path"
```

---

### Task 3: `related.py` — query builders + `normalize_entry`

**Files:**
- Modify: `audio_dl_ui/related.py`
- Modify: `test_audio_dl_related.py`

**Interfaces:**
- Consumes: Task 1 constants + `resolve_artist` + `_pick_thumbnail_url`; Task 2 fixtures.
- Produces: `build_native_query(seed: dict) -> str | None`; `build_search_query(seed: dict) -> str | None`; `normalize_entry(entry: dict, platform: str) -> dict | None`. A normalized item dict has EXACTLY these keys: `id: str`, `title: str`, `artist: str | None`, `platform: str`, `webpage_url: str`, `duration: int | None`, `thumb_id: None`, `_thumb_src: str | None`. (`_thumb_src` is internal — the glue pops it before emitting; `id` stays on the wire and feeds the React key.)
- Seed dict shape (produced by the hook in Task 6): `{"platform": str, "id": str | None, "title": str | None, "artist": str | None, "webpage_url": str | None}`.

- [ ] **Step 1: Write the failing tests**

First, EXTEND the top-of-file import block of `test_audio_dl_related.py` in place (do NOT append a new import statement after code — pylint C0413). The block becomes:

```python
from audio_dl_ui.related import (
    resolve_artist,
    is_allowed_thumb_url,
    _pick_thumbnail_url,
    build_native_query,
    build_search_query,
    normalize_entry,
    SC_NATIVE_PATH_ENABLED,
)
```

Then append to the end of the file:

```python
def _yt_seed(**over):
    seed = {"platform": "youtube", "id": "dQw4w9WgXcQ", "title": "Never Gonna",
            "artist": "Rick Astley",
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    seed.update(over)
    return seed


def _sc_seed(**over):
    seed = {"platform": "soundcloud", "id": "254112129", "title": "One More Time",
            "artist": "Daft Punk",
            "webpage_url": "https://soundcloud.com/daftpunkofficialmusic/one-more-time"}
    seed.update(over)
    return seed


class TestBuildNativeQuery:
    def test_youtube_mix_url(self):
        assert build_native_query(_yt_seed()) == (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ"
        )

    def test_youtube_without_id_returns_none(self):
        assert build_native_query(_yt_seed(id=None)) is None

    @pytest.mark.skipif(not SC_NATIVE_ENABLED, reason="SC native path gated off")
    def test_soundcloud_recommended_url(self):
        assert build_native_query(_sc_seed()) == (
            "https://soundcloud.com/daftpunkofficialmusic/one-more-time/recommended"
        )

    @pytest.mark.skipif(not SC_NATIVE_ENABLED, reason="SC native path gated off")
    def test_soundcloud_recommended_url_preserves_query(self):
        # A private-track permalink carries ?secret_token=…; /recommended must
        # be inserted into the path, not appended after the query string.
        seed = _sc_seed(
            webpage_url="https://soundcloud.com/artist/private-track?secret_token=s-AbC12"
        )
        assert build_native_query(seed) == (
            "https://soundcloud.com/artist/private-track/recommended?secret_token=s-AbC12"
        )

    def test_soundcloud_without_permalink_returns_none(self):
        assert build_native_query(_sc_seed(webpage_url=None)) is None

    def test_unsupported_platform_returns_none(self):
        assert build_native_query({"platform": "bunnystream", "id": "x",
                                   "webpage_url": "https://x"}) is None

    def test_native_path_matches_gate(self):
        # When the Task-2 probe failed, the soundcloud branch must be OFF.
        result = build_native_query(_sc_seed())
        assert (result is not None) == SC_NATIVE_ENABLED == SC_NATIVE_PATH_ENABLED


class TestBuildSearchQuery:
    def test_youtube_seed_searches_soundcloud(self):
        assert build_search_query(_yt_seed()) == "scsearch8:Rick Astley"

    def test_soundcloud_seed_searches_youtube(self):
        assert build_search_query(_sc_seed()) == "ytsearch8:Daft Punk"

    def test_no_artist_returns_none(self):
        assert build_search_query(_yt_seed(artist=None)) is None


class TestNormalizeEntry:
    def test_youtube_mix_entry(self):
        item = normalize_entry(YT_MIX_ENTRY, "youtube")
        assert item == {
            "id": "PIb6AZdTr-A",
            "title": "Cyndi Lauper - Girls Just Want To Have Fun (Official Video)",
            "artist": "Cyndi Lauper",
            "platform": "youtube",
            "webpage_url": "https://www.youtube.com/watch?v=PIb6AZdTr-A",
            "duration": 267,
            "thumb_id": None,
            "_thumb_src": "https://i.ytimg.com/vi/PIb6AZdTr-A/hqdefault.jpg",
        }

    def test_soundcloud_entry_links_permalink_not_api_url(self):
        item = normalize_entry(SC_SEARCH_ENTRY, "soundcloud")
        assert item is not None
        assert item["webpage_url"] == (
            "https://soundcloud.com/daftpunkofficialmusic/one-more-time"
        )
        assert "api.soundcloud.com" not in item["webpage_url"]
        assert item["artist"] == "Daft Punk"
        assert item["duration"] == 320

    @pytest.mark.skipif(not SC_NATIVE_ENABLED, reason="SC native path gated off")
    def test_soundcloud_recommended_entry(self):
        item = normalize_entry(SC_RECOMMENDED_ENTRY, "soundcloud")
        assert item is not None
        assert item["platform"] == "soundcloud"
        assert item["webpage_url"].startswith("https://soundcloud.com/")

    def test_missing_title_returns_none(self):
        assert normalize_entry({**YT_MIX_ENTRY, "title": None}, "youtube") is None

    def test_soundcloud_missing_webpage_url_returns_none(self):
        entry = dict(SC_SEARCH_ENTRY)
        del entry["webpage_url"]
        assert normalize_entry(entry, "soundcloud") is None

    def test_missing_id_returns_none(self):
        assert normalize_entry({**YT_MIX_ENTRY, "id": None}, "youtube") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_audio_dl_related.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_native_query'`

- [ ] **Step 3: Implement in `related.py`**

Append:

```python
# Flipped to False (with a dated comment) if the Task-2 /recommended probe
# fails — SoundCloud seeds then ship cross-platform-only per the spec's
# gating pre-requisite.
SC_NATIVE_PATH_ENABLED = True


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
```

If Task 2 took **Branch B**, set `SC_NATIVE_PATH_ENABLED = False` with the dated comment.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_audio_dl_related.py -v`
Expected: PASS (skips are OK only under Branch B).

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui/related.py test_audio_dl_related.py
git commit -m "feat(related): query builders + entry normalization against live fixtures"
```

---

### Task 4: `related.py` — `select_items` + `discover` + `_flat_extract` seam

**Files:**
- Modify: `audio_dl_ui/related.py`
- Modify: `test_audio_dl_related.py`

**Interfaces:**
- Consumes: Task 3 builders + `normalize_entry`.
- Produces: `select_items(seed: dict, native: list[dict], cross: list[dict]) -> list[dict]`; `discover(seed: dict) -> tuple[str, list[dict]]` where status ∈ `{"ready", "none", "error"}`; `_flat_extract(query: str) -> dict` (module-level, monkeypatch seam — Task 7's glue calls `discover`, tests patch `audio_dl_ui.related._flat_extract`).

- [ ] **Step 1: Write the failing tests**

First, extend the imports of `test_audio_dl_related.py` in place: add `from unittest.mock import patch` at the very top of the import section (stdlib imports sit ABOVE `import pytest` — pylint C0411 import-order), and add `discover` and `select_items` to the existing `from audio_dl_ui.related import (...)` block. Then append to the end of the file:

```python
def _item(platform: str, iid: str, title: str = "t") -> dict:
    return {"id": iid, "title": title, "artist": "A", "platform": platform,
            "webpage_url": f"https://{platform}/{iid}", "duration": 60,
            "thumb_id": None, "_thumb_src": None}


class TestSelectItems:
    SEED = {"platform": "youtube", "id": "seed", "artist": "A",
            "title": "T", "webpage_url": "https://x"}

    def test_excludes_seed_echo(self):
        # YouTube Mix returns the seed itself as entry 1.
        native = [_item("youtube", "seed"), _item("youtube", "n1")]
        out = select_items(self.SEED, native, [])
        assert [i["id"] for i in out] == ["n1"]

    def test_dedupes_by_platform_and_id(self):
        native = [_item("youtube", "n1"), _item("youtube", "n1")]
        out = select_items(self.SEED, native, [])
        assert len(out) == 1

    def test_native_capped_at_5_when_cross_exists(self):
        native = [_item("youtube", f"n{i}") for i in range(8)]
        cross = [_item("soundcloud", f"c{i}") for i in range(8)]
        out = select_items(self.SEED, native, cross)
        assert len(out) == 8
        assert sum(1 for i in out if i["platform"] == "youtube") == 5
        assert sum(1 for i in out if i["platform"] == "soundcloud") == 3

    def test_native_fills_all_8_when_cross_empty(self):
        native = [_item("youtube", f"n{i}") for i in range(10)]
        out = select_items(self.SEED, native, [])
        assert len(out) == 8
        assert all(i["platform"] == "youtube" for i in out)

    def test_cross_fills_all_8_when_native_empty(self):
        cross = [_item("soundcloud", f"c{i}") for i in range(10)]
        out = select_items(self.SEED, [], cross)
        assert len(out) == 8

    def test_native_backfills_when_cross_is_short(self):
        native = [_item("youtube", f"n{i}") for i in range(8)]
        cross = [_item("soundcloud", "c0")]
        out = select_items(self.SEED, native, cross)
        assert len(out) == 8
        assert sum(1 for i in out if i["platform"] == "soundcloud") == 1


class TestDiscover:
    SEED = {"platform": "youtube", "id": "seed", "artist": "Rick Astley",
            "title": "T", "webpage_url": "https://www.youtube.com/watch?v=seed"}

    def test_ready_merges_native_and_cross(self):
        def fake_extract(query):
            if "list=RD" in query:
                return {"entries": [YT_MIX_ENTRY]}
            assert query == "scsearch8:Rick Astley"
            return {"entries": [SC_SEARCH_ENTRY]}
        with patch("audio_dl_ui.related._flat_extract", side_effect=fake_extract):
            status, items = discover(self.SEED)
        assert status == "ready"
        assert {i["platform"] for i in items} == {"youtube", "soundcloud"}

    def test_one_provider_fails_other_stands(self):
        def fake_extract(query):
            if "list=RD" in query:
                raise RuntimeError("boom")
            return {"entries": [SC_SEARCH_ENTRY]}
        with patch("audio_dl_ui.related._flat_extract", side_effect=fake_extract):
            status, items = discover(self.SEED)
        assert status == "ready"
        assert len(items) == 1

    def test_both_fail_is_error(self):
        with patch("audio_dl_ui.related._flat_extract",
                   side_effect=RuntimeError("boom")):
            status, items = discover(self.SEED)
        assert (status, items) == ("error", [])

    def test_zero_items_is_none(self):
        with patch("audio_dl_ui.related._flat_extract",
                   return_value={"entries": []}):
            status, items = discover(self.SEED)
        assert (status, items) == ("none", [])

    def test_no_artist_skips_search_provider(self):
        calls = []
        def fake_extract(query):
            calls.append(query)
            return {"entries": [YT_MIX_ENTRY]}
        seed = dict(self.SEED, artist=None)
        with patch("audio_dl_ui.related._flat_extract", side_effect=fake_extract):
            status, _items = discover(seed)
        assert status == "ready"
        assert calls == ["https://www.youtube.com/watch?v=seed&list=RDseed"]

    def test_one_fails_other_empty_is_none_not_error(self):
        def fake_extract(query):
            if "list=RD" in query:
                raise RuntimeError("boom")
            return {"entries": []}
        with patch("audio_dl_ui.related._flat_extract", side_effect=fake_extract):
            status, items = discover(self.SEED)
        assert (status, items) == ("none", [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_audio_dl_related.py -v`
Expected: FAIL with `ImportError: cannot import name 'discover'`

- [ ] **Step 3: Implement in `related.py`**

Append:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_audio_dl_related.py -v`
Expected: PASS

- [ ] **Step 5: Run pylint on the new module**

Run: `pylint audio_dl_ui/related.py test_audio_dl_related.py`
Expected: 10.00/10 (fix any complaints now, matching the repo's existing disable style).

- [ ] **Step 6: Commit**

```bash
git add audio_dl_ui/related.py test_audio_dl_related.py
git commit -m "feat(related): selection rules + discover orchestration behind _flat_extract seam"
```

---

### Task 5: Backend state + protocol — `UrlState` fields, guaranteed-events rename, `url_metadata.related_status`, snapshot

**Files:**
- Modify: `audio_dl_ui/__init__.py` (UrlState ~line 110; `_TERMINAL_EVENT_TYPES` lines 161-168; `_put_with_overflow` line 179; `_make_progress_hook` emits lines 408-416 and 424-432; `_build_snapshot` lines 756-779)
- Modify: `test_audio_dl_ui.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `UrlState.related_status: str | None` and `UrlState.related_items: list[dict]`; `_GUARANTEED_EVENT_TYPES` (renamed from `_TERMINAL_EVENT_TYPES`, now including `"url_related"`); both `url_metadata` emissions carry `"related_status"`; snapshot per-URL entries carry `"related_status"` + `"related_items"`. Tasks 6-8 and the frontend rely on these exact field names.

- [ ] **Step 1: Write the failing tests**

Append to `test_audio_dl_ui.py`:

```python
# ---------------------------------------------------------------------------
# Related-content discovery — state + protocol (spec 2026-07-01)
# ---------------------------------------------------------------------------

class TestRelatedStateAndProtocol:
    def test_urlstate_defaults(self):
        st = UrlState(url="https://x", media_format="mp3")
        assert st.related_status is None
        assert st.related_items == []

    def test_url_related_is_guaranteed_delivery(self):
        from audio_dl_ui import _GUARANTEED_EVENT_TYPES, _put_with_overflow
        assert "url_related" in _GUARANTEED_EVENT_TYPES
        q: queue.Queue = queue.Queue(maxsize=1)
        q.put_nowait({"type": "progress"})  # fill the queue
        _put_with_overflow(q, {"type": "url_related", "status": "ready"})
        # Oldest dropped, guaranteed event delivered.
        drained = [q.get_nowait() for _ in range(q.qsize())]
        assert any(e["type"] == "url_related" for e in drained)

    def test_snapshot_carries_related_fields(self):
        from audio_dl_ui import _build_snapshot
        job = _fresh_job()
        st = list(job.url_states.values())[0]
        st.related_status = "ready"
        st.related_items = [{"id": "n1", "title": "t", "artist": "a",
                             "platform": "youtube", "webpage_url": "https://w",
                             "duration": 60, "thumb_id": None}]
        snap = _build_snapshot(job)
        entry = snap["urls"][0]
        assert entry["related_status"] == "ready"
        assert entry["related_items"][0]["id"] == "n1"

    def test_url_metadata_carries_related_status(self):
        from audio_dl_ui import _make_progress_hook
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        urlst.related_status = "unsupported"  # pre-set; hook must echo current value
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        hook = _make_progress_hook(job, urlst)
        hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 100,
              "info_dict": {"title": "T"}})
        events = [q.get_nowait() for _ in range(q.qsize())]
        meta = [e for e in events if e["type"] == "url_metadata"]
        assert meta and "related_status" in meta[0]
```

Note: the `related_status` value asserted here is whatever the trigger (Task 6) leaves — this task only asserts the FIELD is present. `test_url_metadata_carries_related_status` pre-sets `"unsupported"` so it passes both before and after Task 6 lands.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_audio_dl_ui.py::TestRelatedStateAndProtocol -v`
Expected: FAIL (`AttributeError: ... no attribute 'related_status'`, `ImportError: _GUARANTEED_EVENT_TYPES`)

- [ ] **Step 3: Implement**

In `audio_dl_ui/__init__.py`:

(a) `UrlState` — after the `thumb_id: str | None = None` field (line 110), add:

```python
    # Related-content discovery (spec 2026-07-01):
    # None       — never started (disabled, or failed before first metadata tick)
    # "pending"  — discovery task submitted, unresolved
    # "ready" | "none" | "error" | "unsupported" — resolved outcomes.
    # Every task exit path moves the status off "pending".
    related_status: str | None = None
    related_items: list[dict] = field(default_factory=list)
```

(b) Rename the guaranteed-delivery set (lines 161-168) and add `url_related`:

```python
# Guaranteed events must always be delivered even if the queue is full;
# progress events can be dropped (they're throttled to ~5/sec/URL upstream
# and a missed sample is harmless). ``job_snapshot`` is delivered out-of-band
# (yielded directly by _events_iter before draining the queue) so it doesn't
# appear here. (Renamed from _TERMINAL_EVENT_TYPES when the one-shot
# url_related event joined — "terminal" no longer described the contents.)
_GUARANTEED_EVENT_TYPES = frozenset({
    "url_started", "url_completed", "url_failed", "job_completed",
    "url_related",
})
```

Update the single use in `_put_with_overflow` (line 179): `if event.get("type") in _GUARANTEED_EVENT_TYPES:`.

(c) Both `url_metadata` emit dicts in `_make_progress_hook` (the `thumbnail_ready: False` one at lines 408-416 and the `thumbnail_ready: True` one inside `_do_fetch` at lines 424-432) gain one line each:

```python
                "related_status": url_state.related_status,
```

(d) `_build_snapshot` per-URL dict (after `"thumb_id": s.thumb_id,` line 776) gains:

```python
                "related_status": s.related_status,
                "related_items": list(s.related_items),
```

- [ ] **Step 4: Run the full backend suite**

Run: `pytest test_audio_dl_ui.py test_audio_dl_related.py -q`
Expected: PASS — including all pre-existing tests (the rename has exactly one definition + one use; `grep -n "_TERMINAL_EVENT_TYPES" audio_dl_ui/__init__.py test_audio_dl_ui.py` must return nothing).

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui/__init__.py test_audio_dl_ui.py
git commit -m "feat(related): UrlState related fields, guaranteed url_related delivery, protocol additions"
```

---

### Task 6: Backend trigger — seed from the hook + `--no-related` flag

**Files:**
- Modify: `audio_dl_ui/__init__.py` (imports line 47-53; `_make_progress_hook` metadata block lines 403-434; `main()` argparse ~line 1217 and app.state ~line 1278)
- Modify: `test_audio_dl_ui.py`

**Interfaces:**
- Consumes: `_related.resolve_artist`, `_related.SUPPORTED_PLATFORMS` (Task 1); `UrlState.related_status` (Task 5). `detect_platform` newly imported from `audio_dl`.
- Produces: hook sets `related_status` to `"pending"` (+ submits `_run_discovery(job, url_state, seed)` to `_related_executor()`) / `"unsupported"` / leaves `None` when disabled / `"error"` on trigger failure. `app.state.related_enabled: bool` (default True; `--no-related` flips it). Task 7 implements `_run_discovery` and `_related_executor` — this task adds them as minimal stubs so the wiring is testable now.

- [ ] **Step 1: Write the failing tests**

Append to `test_audio_dl_ui.py`:

```python
class _FakeRelatedExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args):
        self.submitted.append((fn, args))
        return MagicMock()


def _info(platform_url: str, **over) -> dict:
    info = {"id": "dQw4w9WgXcQ", "title": "T", "uploader": "U",
            "webpage_url": platform_url}
    info.update(over)
    return info


class TestRelatedTrigger:
    @pytest.fixture(autouse=True)
    def _fake_executor(self, monkeypatch):
        import audio_dl_ui as ui
        fake = _FakeRelatedExecutor()
        monkeypatch.setattr(ui, "_RELATED_EXECUTOR", fake)
        app.state.related_enabled = True
        yield fake

    def _tick(self, job, urlst, info):
        from audio_dl_ui import _make_progress_hook
        hook = _make_progress_hook(job, urlst)
        hook({"status": "downloading", "downloaded_bytes": 0,
              "total_bytes": 100, "info_dict": info})

    def test_supported_platform_sets_pending_and_submits_once(self, _fake_executor):
        job = _fresh_job("https://youtu.be/dQw4w9WgXcQ")
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        self._tick(job, urlst, _info("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        assert urlst.related_status == "pending"
        assert len(_fake_executor.submitted) == 1
        fn, args = _fake_executor.submitted[0]
        assert fn.__name__ == "_run_discovery"
        seed = args[2]
        assert seed == {"platform": "youtube", "id": "dQw4w9WgXcQ",
                        "title": "T", "artist": "U",
                        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        # url_metadata emitted on the same tick carries "pending"
        meta = [e for e in (q.get_nowait() for _ in range(q.qsize()))
                if e["type"] == "url_metadata"]
        assert meta[0]["related_status"] == "pending"

    def test_unsupported_platform_no_submit(self, _fake_executor):
        job = _fresh_job("https://video.mediadelivery.net/play/1/x")
        urlst = list(job.url_states.values())[0]
        self._tick(job, urlst, _info("https://video.mediadelivery.net/play/1/x"))
        assert urlst.related_status == "unsupported"
        assert _fake_executor.submitted == []

    def test_disabled_leaves_none(self, _fake_executor):
        app.state.related_enabled = False
        job = _fresh_job("https://youtu.be/dQw4w9WgXcQ")
        urlst = list(job.url_states.values())[0]
        self._tick(job, urlst, _info("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        assert urlst.related_status is None
        assert _fake_executor.submitted == []

    def test_missing_id_is_unsupported(self, _fake_executor):
        job = _fresh_job("https://youtu.be/dQw4w9WgXcQ")
        urlst = list(job.url_states.values())[0]
        self._tick(job, urlst,
                   _info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", id=None))
        assert urlst.related_status == "unsupported"
        assert _fake_executor.submitted == []

    def test_trigger_exception_never_fails_download(self, _fake_executor, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "detect_platform",
                            MagicMock(side_effect=RuntimeError("boom")))
        job = _fresh_job("https://youtu.be/dQw4w9WgXcQ")
        urlst = list(job.url_states.values())[0]
        # Must not raise — a raise here would fail the real download.
        self._tick(job, urlst, _info("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        assert urlst.related_status == "error"
        # Metadata capture still happened.
        assert urlst.title == "T"


class TestNoRelatedFlag:
    def test_flag_disables(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "uvicorn", MagicMock())
        monkeypatch.setattr(ui, "_check_dependencies_gui", lambda: None)
        monkeypatch.setattr(ui, "_preflight_or_exit", lambda h, p: None)
        monkeypatch.setattr("sys.argv", ["audio-dl-ui", "--no-browser", "--no-related"])
        ui.main()
        assert app.state.related_enabled is False

    def test_default_enabled(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "uvicorn", MagicMock())
        monkeypatch.setattr(ui, "_check_dependencies_gui", lambda: None)
        monkeypatch.setattr(ui, "_preflight_or_exit", lambda h, p: None)
        monkeypatch.setattr("sys.argv", ["audio-dl-ui", "--no-browser"])
        ui.main()
        assert app.state.related_enabled is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_audio_dl_ui.py::TestRelatedTrigger test_audio_dl_ui.py::TestNoRelatedFlag -v`
Expected: FAIL (`AttributeError: module 'audio_dl_ui' has no attribute '_RELATED_EXECUTOR'`, `unrecognized arguments: --no-related`)

- [ ] **Step 3: Implement**

In `audio_dl_ui/__init__.py`:

(a) Add `detect_platform` to the `from audio_dl import (...)` block (lines 47-53):

```python
from audio_dl import (
    ALL_FORMATS,
    _check_dependencies,
    detect_platform,
    download_media,
    sanitize_url,
    __version__,
)
```

(b) Below `_GLOBAL_EXECUTOR` (line 154), add the discovery executor + stubs (Task 7 fills the stubs in):

```python
# Related-content discovery pool: deliberately small and separate from
# _GLOBAL_EXECUTOR so a slow platform search can never starve download
# workers. Two workers bound total discovery egress regardless of batch
# size. Lazily created (tests monkeypatch _RELATED_EXECUTOR directly).
_RELATED_EXECUTOR: ThreadPoolExecutor | None = None


def _related_executor() -> ThreadPoolExecutor:
    """Lazily create the 2-worker discovery pool (mirrors _GLOBAL_EXECUTOR's
    pytest-friendly lazy init)."""
    global _RELATED_EXECUTOR  # pylint: disable=global-statement
    if _RELATED_EXECUTOR is None:
        _RELATED_EXECUTOR = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="related"
        )
    return _RELATED_EXECUTOR


def _run_discovery(job: "JobState", url_state: "UrlState", seed: dict) -> None:
    """Discovery task body — implemented in the discovery-task task."""
    raise NotImplementedError  # replaced in the next task
```

Note for the trigger below: it must submit via `(_RELATED_EXECUTOR or _related_executor())` so a test-injected fake executor is used without the lazy init overwriting it.

(c) In `_make_progress_hook`, inside the `if info and not url_state.metadata_emitted:` block — insert AFTER `url_state.metadata_emitted = True` (line 407) and BEFORE the `_emit(job, {"type": "url_metadata", ...})` call, so the emitted event already carries the resolved status. This block only *resolves* the status (and stashes the seed in `related_seed`); the discovery task is submitted in (c2) below, after the event is emitted:

```python
            # Related-content discovery trigger (spec 2026-07-01). This runs
            # in the hot download path (yt-dlp calls hooks in-band), so it is
            # wrapped: an exception here would otherwise be caught by
            # _run_one's broad handler and fail the REAL download.
            #
            # Only the *status* is resolved here (and the seed stashed in
            # related_seed); the discovery task is submitted in (c2), AFTER
            # the url_metadata event below. A fast _run_discovery could
            # otherwise emit url_related before url_metadata carries
            # related_status="pending", and the client's later url_metadata
            # handler would downgrade the already-resolved status back to
            # "pending" — stalling teardown until the SSE linger cap.
            related_seed = None
            try:
                if getattr(app.state, "related_enabled", True):
                    seed = {
                        "platform": detect_platform(
                            info.get("webpage_url")
                            or url_state.sanitized_url
                            or url_state.url
                        ),
                        "id": info.get("id"),
                        "title": info.get("title"),
                        "artist": _related.resolve_artist(info),
                        "webpage_url": info.get("webpage_url"),
                    }
                    if (
                        seed["platform"] in _related.SUPPORTED_PLATFORMS
                        and seed["id"]
                    ):
                        url_state.related_status = "pending"
                        related_seed = seed
                    else:
                        url_state.related_status = "unsupported"
                # disabled → related_status stays None (no event, no strip)
            except Exception:  # pylint: disable=broad-except
                url_state.related_status = "error"
```

(c2) Immediately AFTER that `_emit(job, {"type": "url_metadata", ...})` call (still inside the `if info and not url_state.metadata_emitted:` block), submit the discovery task — never before the event is emitted:

```python
            # Submit only now that url_metadata (carrying "pending") has been
            # emitted, so the worker thread can't race a url_related ahead of
            # it. related_seed is None unless the status resolved to "pending".
            if related_seed is not None:
                executor = _RELATED_EXECUTOR or _related_executor()
                executor.submit(_run_discovery, job, url_state, related_seed)
```

(d) In `main()`, after the `--allow-remote` argument (line 1227), add:

```python
    parser.add_argument(
        "--no-related", action="store_true",
        help="Disable related-content discovery (no extra YouTube/SoundCloud "
             "queries or thumbnail fetches during downloads).",
    )
```

and after `app.state.max_parallel = args.max_parallel` (line 1278):

```python
    # Related-content discovery kill switch (default on; see spec decision #8).
    app.state.related_enabled = not args.no_related
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_audio_dl_ui.py -q`
Expected: PASS (all — including untouched suites; the trigger is additive).

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui/__init__.py test_audio_dl_ui.py
git commit -m "feat(related): hook trigger builds seed + submits discovery; --no-related kill switch"
```

---

### Task 7: Backend discovery task — hardened thumb fetch, persist, emit

**Files:**
- Modify: `audio_dl_ui/__init__.py` (replace the `_run_discovery` stub; add `_fetch_related_thumb_bytes` near `_fetch_thumbnail`)
- Modify: `test_audio_dl_ui.py`

**Interfaces:**
- Consumes: `_related.discover` (Task 4), `_related.is_allowed_thumb_url` (Task 1), `_persist_thumb` (existing, line 1052), `_emit`, `_THUMB_MAX_BYTES`.
- Produces: `_run_discovery(job, url_state, seed) -> None` — full behavior: cancel/failure suppression, 15 s thumbnail budget, single `url_related` emit `{type, job_id, url, status, items}` where each item has `id/title/artist/platform/webpage_url/duration/thumb_id` (NO `_thumb_src` on the wire). `_fetch_related_thumb_bytes(src_url: str, timeout: float = 5.0) -> bytes | None`.

- [ ] **Step 1: Write the failing tests**

Append to `test_audio_dl_ui.py`:

```python
def _ready_item(**over) -> dict:
    item = {"id": "n1", "title": "Song", "artist": "Artist",
            "platform": "youtube", "webpage_url": "https://www.youtube.com/watch?v=n1",
            "duration": 60, "thumb_id": None,
            "_thumb_src": "https://i.ytimg.com/vi/n1/hqdefault.jpg"}
    item.update(over)
    return item


class TestRunDiscovery:
    def _job_with_queue(self):
        job = _fresh_job("https://youtu.be/dQw4w9WgXcQ")
        urlst = list(job.url_states.values())[0]
        urlst.related_status = "pending"
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        return job, urlst, q

    SEED = {"platform": "youtube", "id": "dQw4w9WgXcQ", "title": "T",
            "artist": "U", "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}

    def test_ready_emits_url_related_with_thumb_ids(self, monkeypatch, tmp_path):
        import audio_dl_ui as ui
        job, urlst, q = self._job_with_queue()
        monkeypatch.setattr(ui._related, "discover",
                            lambda seed: ("ready", [_ready_item()]))
        monkeypatch.setattr(ui, "_fetch_related_thumb_bytes",
                            lambda url, timeout=None: b"\xff\xd8\xff\xe0jpeg")
        monkeypatch.setattr(ui, "_thumb_cache_dir", lambda: tmp_path)
        ui._run_discovery(job, urlst, self.SEED)
        assert urlst.related_status == "ready"
        assert len(urlst.related_items) == 1
        item = urlst.related_items[0]
        assert "_thumb_src" not in item
        assert isinstance(item["thumb_id"], str) and len(item["thumb_id"]) == 40
        events = [q.get_nowait() for _ in range(q.qsize())]
        rel = [e for e in events if e["type"] == "url_related"]
        assert len(rel) == 1
        assert rel[0]["status"] == "ready"
        assert rel[0]["url"] == urlst.url
        assert rel[0]["items"][0]["thumb_id"] == item["thumb_id"]

    def test_thumb_fetch_failure_leaves_null_thumb_id(self, monkeypatch):
        import audio_dl_ui as ui
        job, urlst, q = self._job_with_queue()
        monkeypatch.setattr(ui._related, "discover",
                            lambda seed: ("ready", [_ready_item()]))
        monkeypatch.setattr(ui, "_fetch_related_thumb_bytes",
                            lambda url, timeout=None: None)
        ui._run_discovery(job, urlst, self.SEED)
        assert urlst.related_items[0]["thumb_id"] is None
        assert urlst.related_status == "ready"

    def test_cancelled_job_suppresses_emit(self, monkeypatch):
        import audio_dl_ui as ui
        job, urlst, q = self._job_with_queue()
        job.cancelled = True
        monkeypatch.setattr(ui._related, "discover",
                            lambda seed: ("ready", [_ready_item()]))
        ui._run_discovery(job, urlst, self.SEED)
        assert urlst.related_status == "none"
        assert q.empty()

    def test_failed_url_suppresses_emit(self, monkeypatch):
        import audio_dl_ui as ui
        job, urlst, q = self._job_with_queue()
        monkeypatch.setattr(ui._related, "discover",
                            lambda seed: ("ready", [_ready_item()]))
        monkeypatch.setattr(ui, "_fetch_related_thumb_bytes",
                            lambda url, timeout=None: None)
        urlst.status = "failed"
        ui._run_discovery(job, urlst, self.SEED)
        assert urlst.related_status == "none"
        assert urlst.related_items == []
        assert q.empty()

    def test_none_status_emits_empty_items(self, monkeypatch):
        import audio_dl_ui as ui
        job, urlst, q = self._job_with_queue()
        monkeypatch.setattr(ui._related, "discover", lambda seed: ("none", []))
        ui._run_discovery(job, urlst, self.SEED)
        rel = [e for e in (q.get_nowait() for _ in range(q.qsize()))
               if e["type"] == "url_related"]
        assert rel[0]["status"] == "none"
        assert rel[0]["items"] == []

    def test_task_exception_resolves_error_never_raises(self, monkeypatch):
        import audio_dl_ui as ui
        job, urlst, q = self._job_with_queue()
        monkeypatch.setattr(ui._related, "discover",
                            MagicMock(side_effect=RuntimeError("boom")))
        ui._run_discovery(job, urlst, self.SEED)  # must not raise
        assert urlst.related_status == "error"
        assert q.empty()  # error from an exception is silent (log line only)
        assert any("related discovery failed" in e["text"] for e in urlst.log)

    def test_thumbnail_budget_skips_items_past_deadline(self, monkeypatch, tmp_path):
        """The 15s thumbnail-phase budget is the task's one hard time bound
        (spec Providers/Thumbnails): once exceeded, remaining items keep
        thumb_id None but the result still emits as ready."""
        import audio_dl_ui as ui
        job, urlst, q = self._job_with_queue()
        items = [
            _ready_item(),
            _ready_item(id="n2",
                        webpage_url="https://www.youtube.com/watch?v=n2",
                        _thumb_src="https://i.ytimg.com/vi/n2/hqdefault.jpg"),
        ]
        monkeypatch.setattr(ui._related, "discover", lambda seed: ("ready", items))
        monkeypatch.setattr(ui, "_fetch_related_thumb_bytes",
                            lambda url, timeout=None: b"\xff\xd8jpeg")
        monkeypatch.setattr(ui, "_thumb_cache_dir", lambda: tmp_path)
        # Fake clock (repo precedent: TestProgressHook fakes time.monotonic):
        # call 1 = deadline calc (1000 → deadline 1015), call 2 = item-1
        # check (inside budget), call 3 = item-2 check (past budget).
        # Clamped, not exhausted, so stray background callers can't flake it.
        seq = [1000.0, 1001.0, 1020.0]
        calls = {"n": 0}
        def fake_monotonic():
            v = seq[min(calls["n"], len(seq) - 1)]
            calls["n"] += 1
            return v
        monkeypatch.setattr(ui.time, "monotonic", fake_monotonic)
        ui._run_discovery(job, urlst, self.SEED)
        assert urlst.related_status == "ready"
        thumb_ids = [i["thumb_id"] for i in urlst.related_items]
        assert thumb_ids[0] is not None
        assert thumb_ids[1] is None


class TestFetchRelatedThumbBytes:
    def test_disallowed_host_refused_without_network(self):
        from audio_dl_ui import _fetch_related_thumb_bytes
        # No httpx mock: if the allowlist check didn't run first, this would
        # attempt a real request and (in CI) fail slowly. Refusal is instant.
        assert _fetch_related_thumb_bytes("https://example.com/x.jpg") is None
        assert _fetch_related_thumb_bytes("http://i.ytimg.com/x.jpg") is None

    def test_fetches_allowed_host(self):
        from audio_dl_ui import _fetch_related_thumb_bytes
        with patch("audio_dl_ui.httpx.stream",
                   return_value=_mock_httpx_stream(content=b"\xff\xd8jpeg")) as m:
            data = _fetch_related_thumb_bytes("https://i.ytimg.com/vi/x/hq.jpg")
        assert data == b"\xff\xd8jpeg"
        # follow_redirects must be OFF so a 302 can't bypass the allowlist.
        assert m.call_args.kwargs.get("follow_redirects") is False

    def test_non_200_returns_none(self):
        from audio_dl_ui import _fetch_related_thumb_bytes
        with patch("audio_dl_ui.httpx.stream",
                   return_value=_mock_httpx_stream(status_code=302)):
            assert _fetch_related_thumb_bytes("https://i.ytimg.com/x.jpg") is None

    def test_size_cap_returns_none(self):
        from audio_dl_ui import _fetch_related_thumb_bytes
        big = b"x" * (5 * 1024 * 1024 + 1)
        with patch("audio_dl_ui.httpx.stream",
                   return_value=_mock_httpx_stream(content=big)):
            assert _fetch_related_thumb_bytes("https://i.ytimg.com/x.jpg") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_audio_dl_ui.py::TestRunDiscovery test_audio_dl_ui.py::TestFetchRelatedThumbBytes -v`
Expected: FAIL (`NotImplementedError` from the stub; `ImportError: _fetch_related_thumb_bytes`)

- [ ] **Step 3: Implement**

In `audio_dl_ui/__init__.py`, add below `_fetch_thumbnail` (line 306):

```python
def _fetch_related_thumb_bytes(src_url: str, timeout: float = 5.0) -> bytes | None:
    """Hardened fetch for related-item artwork. Returns raw bytes or None.

    Unlike ``_fetch_thumbnail`` (which trusts yt-dlp's own resolved thumb
    for the download in progress), related-item thumbnails come from many
    search-result entries — so this path enforces https + a host allowlist
    and refuses redirects (a 302 would otherwise bypass the allowlist).
    ``timeout`` is the per-fetch HTTP budget; the caller clamps it to the
    remaining thumbnail-phase budget so a slow CDN can't overrun the wall
    clock. Never raises."""
    if not _related.is_allowed_thumb_url(src_url):
        return None
    try:
        with httpx.stream(
            "GET", src_url, timeout=timeout, follow_redirects=False
        ) as resp:
            if resp.status_code != 200:
                return None
            total = 0
            chunks: list[bytes] = []
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > _THUMB_MAX_BYTES:
                    return None
                chunks.append(chunk)
        return b"".join(chunks)
    except Exception:  # pylint: disable=broad-except
        return None
```

Replace the `_run_discovery` stub with:

```python
def _run_discovery(job: "JobState", url_state: "UrlState", seed: dict) -> None:
    """Discovery task body — runs on _RELATED_EXECUTOR, never raises.

    Sequence: bail early on cancel → discover via related.py → prefetch
    thumbnails into the persistent cache (15 s phase budget) → suppress if
    the job was cancelled or this URL's download failed → record state and
    emit exactly one ``url_related``. Every exit path moves
    ``related_status`` off "pending" (the SSE linger depends on that)."""
    try:
        if job.cancelled:
            url_state.related_status = "none"
            return
        status, items = _related.discover(seed)

        # Thumbnail phase: the one hard time bound in the task (the
        # provider socket_timeout is per-operation, not wall-clock).
        deadline = time.monotonic() + 15.0
        for item in items:
            src = item.pop("_thumb_src", None)
            if not src:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            # Clamp the per-fetch HTTP timeout to what's left of the phase
            # budget: checking the deadline only before the fetch is not
            # enough, since a fetch started just under the deadline could
            # otherwise burn its full socket timeout and overrun the 15s cap.
            data = _fetch_related_thumb_bytes(src, timeout=min(5.0, remaining))
            if data:
                try:
                    item["thumb_id"] = _persist_thumb(src, data)
                except OSError:
                    pass  # cache write failure → gradient fallback tile

        # Suppression: no strip for cancelled jobs or failed downloads —
        # and no linger stall (status resolves off "pending" regardless).
        if job.cancelled or url_state.status in ("failed", "cancelled"):
            url_state.related_status = "none"
            url_state.related_items = []
            return

        url_state.related_status = status
        url_state.related_items = items if status == "ready" else []
        _emit(job, {
            "type": "url_related",
            "job_id": job.id,
            "url": url_state.url,
            "status": status,
            "items": url_state.related_items,
        })
    except Exception as e:  # pylint: disable=broad-except
        url_state.related_status = "error"
        url_state.related_items = []
        url_state.log.append({
            "ts": time.time(), "level": "warning",
            "text": f"related discovery failed: {e}",
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_audio_dl_ui.py -q && pylint audio_dl_ui/__init__.py`
Expected: PASS / 10.00

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui/__init__.py test_audio_dl_ui.py
git commit -m "feat(related): discovery task — hardened thumb prefetch, suppression, url_related emit"
```

---

### Task 8: Backend SSE linger after `job_completed`

**Files:**
- Modify: `audio_dl_ui/__init__.py` (`_events_iter` lines 830-831)
- Modify: `test_audio_dl_ui.py`

**Interfaces:**
- Consumes: `UrlState.related_status` (Task 5).
- Produces: `_events_iter` keeps the stream open ≤10 s after forwarding `job_completed` while any URL with download `status == "completed"` has `related_status == "pending"`; forwards late events; ends early on cancel/resolution. The frontend (Task 11) relies on receiving `url_related` AFTER `job_completed` on the same stream.

- [ ] **Step 1: Write the failing tests**

Append to `test_audio_dl_ui.py`:

```python
def _gate_worker_on_subscriber(ui, monkeypatch) -> threading.Event:
    """TestSseHappyPath's race gate (see test_audio_dl_ui.py:404-416): block
    the worker in sanitize_url until the SSE subscriber has registered, so
    live events (incl. job_completed) deterministically reach the stream.
    The returned Event must be .set() when the stream sees job_snapshot."""
    sse_ready = threading.Event()
    original_sanitize = ui.sanitize_url

    def gated_sanitize(u):
        sse_ready.wait(timeout=5)
        return original_sanitize(u)

    monkeypatch.setattr(ui, "sanitize_url", gated_sanitize)
    return sse_ready


class TestSseLinger:
    INFO = {"id": "dQw4w9WgXcQ", "title": "T", "uploader": "U",
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}

    def _drain(self, job_id, sse_ready, on_event=None, break_on=None):
        events = []
        with client.stream("GET", f"/jobs/{job_id}/events{_csrf_query()}",
                           timeout=15) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                events.append(json.loads(line[len("data: "):]))
                if events[-1]["type"] == "job_snapshot":
                    sse_ready.set()
                if on_event:
                    on_event(events[-1])
                if break_on and events[-1]["type"] == break_on:
                    break
        return events

    def test_linger_forwards_late_url_related(self, tmp_path, monkeypatch):
        """Download finishes before discovery: stream must stay open after
        job_completed and deliver the late url_related, then close."""
        import audio_dl_ui as ui
        sse_ready = _gate_worker_on_subscriber(ui, monkeypatch)
        release_discovery = threading.Event()

        def fake_discover(seed):
            release_discovery.wait(timeout=5)
            return ("ready", [_ready_item()])

        monkeypatch.setattr(ui._related, "discover", fake_discover)
        monkeypatch.setattr(ui, "_fetch_related_thumb_bytes",
                            lambda url, timeout=None: None)

        def fake_download(_url, *, progress_hooks=None, **_kwargs):
            progress_hooks[0]({"status": "downloading", "downloaded_bytes": 10,
                               "total_bytes": 100, "info_dict": dict(self.INFO)})
            return [str(tmp_path / "t.mp3")]

        monkeypatch.setattr(ui, "download_media", fake_download)
        app.state.related_enabled = True
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/dQw4w9WgXcQ", "format": "mp3"}]
        job_id = client.post("/jobs", json=body,
                             headers=_csrf_headers()).json()["job_id"]

        def on_event(ev):
            if ev["type"] == "job_completed":
                # Job done, discovery still blocked: linger must hold the
                # stream open. Release discovery now.
                release_discovery.set()

        events = self._drain(job_id, sse_ready, on_event, break_on="url_related")
        types = [e["type"] for e in events]
        assert "job_completed" in types
        assert types.index("url_related") > types.index("job_completed")
        assert next(e for e in events if e["type"] == "url_related")["status"] == "ready"

    def test_no_pending_closes_immediately(self, tmp_path, monkeypatch):
        """A URL that never reached its metadata tick stays related_status=None
        and must NOT stall the close."""
        import audio_dl_ui as ui
        sse_ready = _gate_worker_on_subscriber(ui, monkeypatch)
        monkeypatch.setattr(ui, "download_media",
                            lambda *a, **k: [str(tmp_path / "t.mp3")])
        app.state.related_enabled = True
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/BBB", "format": "mp3"}]
        job_id = client.post("/jobs", json=body,
                             headers=_csrf_headers()).json()["job_id"]

        start = time.monotonic()
        events = self._drain(job_id, sse_ready)
        elapsed = time.monotonic() - start
        assert events[-1]["type"] == "job_completed"
        assert elapsed < 5, f"stream lingered {elapsed:.1f}s with nothing pending"

    def test_failed_url_with_inflight_discovery_does_not_stall(self, tmp_path, monkeypatch):
        """Download fails after discovery was seeded: the linger predicate
        requires status=='completed', so the close must be prompt and the
        suppressed result must never surface."""
        import audio_dl_ui as ui
        sse_ready = _gate_worker_on_subscriber(ui, monkeypatch)
        never = threading.Event()  # discovery blocks until test teardown
        monkeypatch.setattr(ui._related, "discover",
                            lambda seed: (never.wait(timeout=30), ("none", []))[1])

        def fake_download(_url, *, progress_hooks=None, **_kwargs):
            progress_hooks[0]({"status": "downloading", "downloaded_bytes": 10,
                               "total_bytes": 100, "info_dict": dict(self.INFO)})
            raise RuntimeError("network died")

        monkeypatch.setattr(ui, "download_media", fake_download)
        app.state.related_enabled = True
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/CCC", "format": "mp3"}]
        job_id = client.post("/jobs", json=body,
                             headers=_csrf_headers()).json()["job_id"]

        start = time.monotonic()
        events = self._drain(job_id, sse_ready)
        elapsed = time.monotonic() - start
        never.set()
        assert events[-1]["type"] == "job_completed"
        assert "url_related" not in [e["type"] for e in events]
        assert elapsed < 5, f"failed URL stalled the close for {elapsed:.1f}s"

    def test_linger_closes_at_cap_when_discovery_never_resolves(self, tmp_path, monkeypatch):
        """Pathological provider stall on a COMPLETED url: the stream must
        close at the cap with no url_related. Cap shrunk via the module
        constant so the test stays fast."""
        import audio_dl_ui as ui
        sse_ready = _gate_worker_on_subscriber(ui, monkeypatch)
        monkeypatch.setattr(ui, "_RELATED_LINGER_CAP_SECONDS", 0.5)
        never = threading.Event()
        monkeypatch.setattr(ui._related, "discover",
                            lambda seed: (never.wait(timeout=30), ("none", []))[1])

        def fake_download(_url, *, progress_hooks=None, **_kwargs):
            progress_hooks[0]({"status": "downloading", "downloaded_bytes": 10,
                               "total_bytes": 100, "info_dict": dict(self.INFO)})
            return [str(tmp_path / "t.mp3")]

        monkeypatch.setattr(ui, "download_media", fake_download)
        app.state.related_enabled = True
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/DDD", "format": "mp3"}]
        job_id = client.post("/jobs", json=body,
                             headers=_csrf_headers()).json()["job_id"]

        start = time.monotonic()
        events = self._drain(job_id, sse_ready)
        elapsed = time.monotonic() - start
        never.set()
        assert events[-1]["type"] == "job_completed"
        assert "url_related" not in [e["type"] for e in events]
        assert elapsed < 5, f"cap did not bound the linger ({elapsed:.1f}s)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_audio_dl_ui.py::TestSseLinger -v`
Expected: `test_linger_forwards_late_url_related` FAILS (stream closes at `job_completed`, so the `url_related` index assertion raises ValueError) and `test_linger_closes_at_cap_when_discovery_never_resolves` FAILS (`AttributeError: ... has no attribute '_RELATED_LINGER_CAP_SECONDS'`). The no-pending and failed-URL tests may pass already — that's fine, they're regression guards for the linger you're about to add.

- [ ] **Step 3: Implement**

In `audio_dl_ui/__init__.py`, add a module-level constant directly above the `_events_iter` definition:

```python
# Late-results SSE linger cap (spec "Late results"). Module-level so tests
# can shrink it instead of waiting out the real window.
_RELATED_LINGER_CAP_SECONDS = 10.0
```

Then in `_events_iter`, replace (lines 830-831):

```python
            if event.get("type") == "job_completed":
                return
```

with:

```python
            if event.get("type") == "job_completed":
                # Late-results linger (spec 2026-07-01, "Late results"):
                # short-track downloads can finish before their 2-6s
                # discovery task. Hold the stream open while any URL whose
                # download COMPLETED still has discovery in flight —
                # explicitly not None (never started) and not failed/
                # cancelled URLs (their results are suppressed) — capped,
                # ended early on cancel.
                deadline = time.monotonic() + _RELATED_LINGER_CAP_SECONDS
                while (
                    not job.cancelled
                    and time.monotonic() < deadline
                    and any(
                        s.status == "completed" and s.related_status == "pending"
                        for s in job.url_states.values()
                    )
                ):
                    try:
                        late = await asyncio.to_thread(sub_queue.get, True, 0.5)
                    except queue.Empty:
                        continue
                    yield f"data: {json.dumps(late)}\n\n"
                return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_audio_dl_ui.py -q`
Expected: PASS (all, including `TestSseHappyPath` — jobs with nothing pending still close immediately).

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui/__init__.py test_audio_dl_ui.py
git commit -m "feat(related): SSE linger delivers late url_related after job_completed"
```

---

### Task 9: Frontend types + `use-history.updateItem`

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/hooks/use-history.ts`
- Modify: `web/src/hooks/use-history.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: `RelatedItem` type; `UrlState.related_status?: string | null` + `UrlState.related?: RelatedItem[]`; `HistoryItem.related?: RelatedItem[]`; module-level `updateItem(url: string, patch: Partial<HistoryItem>): void` exported from `use-history.ts` (callable outside React — Task 10's `applyEvent` needs that) and also returned by the `useHistory()` hook.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/hooks/use-history.test.tsx` (inside the existing `describe`):

```tsx
  it("updateItem patches the newest record matching the url", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.addItem(mk("https://b", 2)));
    const related = [{
      id: "n1", title: "Song", artist: "Artist", platform: "youtube" as const,
      webpage_url: "https://www.youtube.com/watch?v=n1",
      duration: 60, thumb_id: null,
    }];
    act(() => result.current.updateItem("https://a", { related }));
    const a = result.current.history.find((h) => h.url === "https://a")!;
    expect(a.related).toEqual(related);
    // Other records untouched.
    expect(result.current.history.find((h) => h.url === "https://b")!.related)
      .toBeUndefined();
  });

  it("updateItem no-ops when no record matches", () => {
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => result.current.updateItem("https://zzz", { title: "X" }));
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0].title).toBeNull();
  });

  it("module-level updateItem notifies mounted subscribers", async () => {
    const { updateItem } = await import("./use-history");
    const { result } = renderHook(() => useHistory());
    act(() => result.current.addItem(mk("https://a", 1)));
    act(() => updateItem("https://a", { title: "Patched" }));
    expect(result.current.history[0].title).toBe("Patched");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/hooks/use-history.test.tsx`
Expected: FAIL (`result.current.updateItem is not a function` / type errors)

- [ ] **Step 3: Implement**

In `web/src/lib/types.ts`, add after `UrlStateName` (line 7):

```ts
export type RelatedPlatform = "youtube" | "soundcloud";

/** One related-track suggestion, as normalized by the backend. */
export interface RelatedItem {
  id: string;
  title: string;
  artist: string | null;
  platform: RelatedPlatform;
  webpage_url: string;
  duration: number | null;
  thumb_id: string | null;
}
```

Extend `UrlState` (after `uploader: string | null;` line 20):

```ts
  related_status?: string | null;
  related?: RelatedItem[];
```

Extend `HistoryItem` (after `added_at: number;` line 37):

```ts
  related?: RelatedItem[];
```

In `web/src/hooks/use-history.ts`, add a module-level function after `write()` (line 24) and return it from the hook:

```ts
/**
 * Patch the newest record matching `url`; no-op when none matches.
 * Module-level (not hook-bound) so the SSE event handler can upsert
 * late-arriving related items outside a React component ("Late results"
 * in the related-content spec). Notifies subscribers so a mounted
 * EmptyStage updates in place.
 */
export function updateItem(url: string, patch: Partial<HistoryItem>): void {
  const items = read();
  // addItem prepends, so the first match is the newest record.
  const idx = items.findIndex((h) => h.url === url);
  if (idx === -1) return;
  items[idx] = { ...items[idx], ...patch };
  write(items);
  refresh();
  notify();
}
```

And in `useHistory()`'s return (line 54): `return { history, addItem, removeItem, updateItem };`

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/hooks/use-history.test.tsx && npx tsc -b`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/hooks/use-history.ts web/src/hooks/use-history.test.tsx
git commit -m "feat(web): RelatedItem types + history updateItem for late-result upserts"
```

---

### Task 10: Frontend `use-job-events` — `url_related` routing + `related_status` tracking

**Files:**
- Modify: `web/src/hooks/use-job-events.ts`
- Modify: `web/src/hooks/use-job-events.test.tsx`

**Interfaces:**
- Consumes: `RelatedItem` + `updateItem` (Task 9); backend wire shapes (Tasks 5, 7).
- Produces: `UrlRelatedEvent` in the `AnyEvent` union; `BackendUrl.related_status?/related_items?`; `mapUrlState` maps them to `related_status`/`related`; `applyEvent` handles `url_related` BEFORE the missing-snapshot early-return with both-actions routing (patch record if it exists; upsert history when record missing or terminal); `url_metadata` handler patches `related_status`. Task 11 adds the connection-lifetime change on top.

- [ ] **Step 1: Write the failing tests**

Append inside the `describe("useJobEvents", ...)` block of `web/src/hooks/use-job-events.test.tsx`:

```tsx
  const RELATED_ITEM = {
    id: "n1", title: "Girls Just Want To Have Fun", artist: "Cyndi Lauper",
    platform: "youtube", webpage_url: "https://www.youtube.com/watch?v=PIb6AZdTr-A",
    duration: 267, thumb_id: "a".repeat(40),
  };

  it("url_related patches the matching URL's related fields", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].related_status).toBe("ready");
    });
    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.urls[0].related).toEqual([RELATED_ITEM]);
  });

  it("url_metadata patches related_status", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );
    es.emit({ type: "url_metadata", job_id: "job-1", url: "https://a",
              title: "T", uploader: "U", duration: 1,
              thumbnail_ready: false, related_status: "pending" });
    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].related_status).toBe("pending");
    });
  });

  it("snapshot round-trips related fields", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    const urls = makeSnapshotEvent().urls.map((u: object) => ({
      ...u, related_status: "ready", related_items: [RELATED_ITEM],
    }));
    es.emit(makeSnapshotEvent({ urls }));
    await waitFor(() => {
      const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
      expect(snap.urls[0].related).toEqual([RELATED_ITEM]);
      expect(snap.urls[0].related_status).toBe("ready");
    });
  });

  it("late url_related with NO cached record upserts into history", async () => {
    localStorage.setItem("audio_dl_history", JSON.stringify({
      v: 1,
      items: [{ url: "https://a", title: "T", artist: "U", media_format: "m4a",
                paths: [], thumb_id: null, added_at: 1 }],
    }));
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    // NO snapshot emitted: the query record does not exist (post-teardown).
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    const stored = JSON.parse(localStorage.getItem("audio_dl_history")!);
    expect(stored.items[0].related).toEqual([RELATED_ITEM]);
  });

  it("url_related on a terminal record patches cache AND upserts history", async () => {
    // The Codex-P2 ordering race: url_completed then url_related arrive
    // back-to-back before JobTracker's effect writes the history row. The
    // cache patch must land so the pending history write carries the items.
    localStorage.setItem("audio_dl_history", JSON.stringify({ v: 1, items: [] }));
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent());
    await waitFor(() =>
      expect(client.getQueryData<JobSnapshot>(["job", "job-1"])).toBeDefined()
    );
    es.emit({ type: "url_completed", job_id: "job-1", url: "https://a",
              paths: ["/tmp/a.mp3"], thumb_id: null });
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    const snap = client.getQueryData<JobSnapshot>(["job", "job-1"])!;
    expect(snap.state).toBe("completed");
    expect(snap.urls[0].related).toEqual([RELATED_ITEM]); // cache patched
    // History had no matching row yet → module updateItem no-oped, harmless.
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/hooks/use-job-events.test.tsx`
Expected: the five new tests FAIL (`related_status` undefined / history not patched).

- [ ] **Step 3: Implement**

In `web/src/hooks/use-job-events.ts`:

(a) Imports (line 3-5): add `RelatedItem` to the type import and import the history upsert:

```ts
import type { JobSnapshot, UrlState, UrlStateName, Format, RelatedItem } from "@/lib/types";
import { updateItem as updateHistoryItem } from "@/hooks/use-history";
```

(b) `BackendUrl` (line 9-21) gains:

```ts
  related_status?: string | null;
  related_items?: RelatedItem[];
```

(c) `UrlMetadataEvent` (line 23-31) gains:

```ts
  related_status?: string | null;
```

(d) New event interface after `UrlFailedEvent` (line 69), and add it to the `AnyEvent` union:

```ts
interface UrlRelatedEvent {
  type: "url_related";
  job_id: string;
  url: string;
  status: "ready" | "none" | "error";
  items: RelatedItem[];
}
```

(e) `mapUrlState` (line 88-102) gains:

```ts
    related_status: b.related_status ?? null,
    related: b.related_items ?? [],
```

(f) In `applyEvent`, insert the `url_related` branch AFTER the `job_snapshot` branch (line 204) and **BEFORE** `if (!prev) return;` (line 206):

```ts
  if (ev.type === "url_related") {
    const e = ev as UrlRelatedEvent;
    // Both actions, not either/or (spec "Late results"): patch the record
    // whenever it still exists (a pending history write reads it), and
    // ALSO upsert history when the record is missing or terminal (rows
    // already written). Both are idempotent.
    if (prev) {
      const urls = prev.urls.map((u): UrlState =>
        u.url === e.url
          ? { ...u, related_status: e.status, related: e.items ?? [] }
          : u
      );
      qc.setQueryData(key, { ...prev, urls });
    }
    if (
      (!prev || TERMINAL.includes(prev.state)) &&
      e.status === "ready" &&
      e.items?.length
    ) {
      updateHistoryItem(e.url, { related: e.items });
    }
    return;
  }
```

(g) In the shared per-URL block's `url_metadata` branch (lines 244-248), add:

```ts
        if (m.related_status !== undefined) next.related_status = m.related_status ?? null;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/hooks/use-job-events.test.tsx && npx tsc -b`
Expected: PASS (all — including every pre-existing test in the file).

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/use-job-events.ts web/src/hooks/use-job-events.test.tsx
git commit -m "feat(web): url_related event routing with cache-patch + history-upsert both-actions rule"
```

---

### Task 11: Frontend `use-job-events` — connection lifetime (pendingRelated / sawTerminal / 10 s cap)

**Files:**
- Modify: `web/src/hooks/use-job-events.ts` (the `useEffect` body, lines 121-183)
- Modify: `web/src/hooks/use-job-events.test.tsx`

**Interfaces:**
- Consumes: `related_status` plumbing (Task 10).
- Produces: the relocated terminal close. Contract for Task 12: the HOOK owns the socket lifetime entirely; `JobTracker` only defers `untrackJob` (unmount).

- [ ] **Step 1: Write the failing tests**

Append inside the `describe` block:

```tsx
  function terminalSnapshotWithPending(related_status: string | null) {
    return makeSnapshotEvent({
      complete: true,
      urls: [{
        url: "https://a", media_format: "mp3", status: "completed",
        percent: 100, speed: null, eta: null, paths: ["/tmp/a.mp3"],
        error: null, thumb_id: null, title: null, uploader: null,
        related_status, related_items: [],
      }],
    });
  }

  it("terminal with nothing pending closes immediately (unchanged behavior)", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(terminalSnapshotWithPending(null));
    await waitFor(() => expect(es.closed).toBe(true));
  });

  it("terminal with a pending completed URL keeps the socket open, then a late url_related closes it silently", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(terminalSnapshotWithPending("pending"));
    // Deliberately NOT closed: the linger window is open.
    expect(es.closed).toBe(false);
    es.emit({ type: "url_related", job_id: "job-1", url: "https://a",
              status: "ready", items: [RELATED_ITEM] });
    await waitFor(() => expect(es.closed).toBe(true));
    expect(getToasts().some((t) => /lost connection/i.test(t.title))).toBe(false);
  });

  it("hook's own 10s cap closes the lingering socket", async () => {
    vi.useFakeTimers();
    try {
      const client = new QueryClient();
      renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
      await vi.waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
      const es = MockEventSource.instances[0];
      es.emit(terminalSnapshotWithPending("pending"));
      expect(es.closed).toBe(false);
      await vi.advanceTimersByTimeAsync(10_000);
      expect(es.closed).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("server close after terminal is silent — no Lost-connection toast even with the query record deleted", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(terminalSnapshotWithPending("pending"));
    // Simulate JobTracker's 1.5s removeQueries firing before the server closes.
    client.removeQueries({ queryKey: ["job", "job-1"] });
    es.onerror?.(new Event("error"));
    expect(es.closed).toBe(true);
    expect(getToasts().some((t) => /lost connection/i.test(t.title))).toBe(false);
  });

  it("failed URLs are dropped from the pending set at terminal", async () => {
    const client = new QueryClient();
    renderHook(() => useJobEvents("job-1"), { wrapper: wrapper(client) });
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    const es = MockEventSource.instances[0];
    es.emit(makeSnapshotEvent({
      complete: true,
      urls: [{
        url: "https://a", media_format: "mp3", status: "failed",
        percent: 0, speed: null, eta: null, paths: [],
        error: "boom", thumb_id: null, title: null, uploader: null,
        related_status: "pending", related_items: [],
      }],
    }));
    // Failed URL's pending discovery is suppressed server-side — no wait.
    await waitFor(() => expect(es.closed).toBe(true));
  });
```

Note: `vi` is already imported in this file's sibling test (`job-tracker.test.tsx`); add `vi` to this file's vitest import line: `import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";`

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/hooks/use-job-events.test.tsx`
Expected: the keep-open test FAILS (`es.closed` is `true` — today's code closes on terminal unconditionally).

- [ ] **Step 3: Implement**

Rewrite the `useEffect` body of `useJobEvents` (lines 123-182) as:

```ts
  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let disconnected = false;
    let sawTerminal = false;
    let lingerTimer: number | null = null;
    const pendingRelated = new Set<string>();
    const sseToastId = `sse-${jobId}`;

    // Client-initiated close is silent: no onerror, no reconnect.
    const closeNow = () => {
      if (lingerTimer !== null) {
        clearTimeout(lingerTimer);
        lingerTimer = null;
      }
      es?.close();
      es = null;
    };

    (async () => {
      const token = await discoverCsrfToken();
      if (cancelled) return;
      const url = token
        ? `/jobs/${jobId}/events?token=${encodeURIComponent(token)}`
        : `/jobs/${jobId}/events`;
      es = new EventSource(url);
      es.onmessage = (e) => {
        if (disconnected) {
          disconnected = false;
          toast.dismiss(sseToastId);
        }
        try {
          const event = JSON.parse(e.data) as AnyEvent;
          applyEvent(queryClient, jobId, event);

          // Track which URLs still have discovery in flight, from the
          // events themselves (the query record dies 1.5s after terminal,
          // so it can't be the source of truth — spec "Late results").
          if (event.type === "url_metadata") {
            const m = event as UrlMetadataEvent;
            if (m.related_status === "pending") pendingRelated.add(m.url);
            else if (m.related_status !== undefined) pendingRelated.delete(m.url);
          }
          if (event.type === "job_snapshot") {
            const s = event as JobSnapshotEvent;
            for (const u of s.urls) {
              if (u.related_status === "pending") pendingRelated.add(u.url);
              else pendingRelated.delete(u.url);
            }
          }
          if (event.type === "url_related") {
            pendingRelated.delete((event as UrlRelatedEvent).url);
          }

          // Terminal handling — the close-on-terminal RELOCATED here from
          // the old unconditional close: while any COMPLETED URL's
          // discovery is pending, keep the socket open (the backend
          // lingers ≤10s to forward the late url_related), bounded by our
          // own 10s cap.
          const snapshot = queryClient.getQueryData<JobSnapshot>(["job", jobId]);
          if (snapshot && TERMINAL.includes(snapshot.state)) {
            sawTerminal = true;
            for (const u of snapshot.urls) {
              // Failed/cancelled downloads never surface a strip — their
              // results are suppressed server-side. Don't wait on them.
              if (u.state !== "completed") pendingRelated.delete(u.url);
            }
            if (pendingRelated.size === 0) {
              closeNow();
            } else if (lingerTimer === null) {
              lingerTimer = window.setTimeout(closeNow, 10_000);
            }
          }
        } catch {
          /* ignore malformed */
        }
      };
      es.onerror = () => {
        // After terminal, any error (typically the server closing the
        // lingered stream) is a clean end: close silently, never toast.
        // sawTerminal is deliberately independent of the query record,
        // which JobTracker removes 1.5s after completion.
        const snapshot = queryClient.getQueryData<JobSnapshot>(["job", jobId]);
        if (sawTerminal || (snapshot && TERMINAL.includes(snapshot.state))) {
          closeNow();
          return;
        }
        if (!disconnected) {
          disconnected = true;
          toast.error("Lost connection — reconnecting…", {
            id: sseToastId,
            description: "Trying to reconnect to the download.",
          });
        }
      };
    })();
    return () => {
      cancelled = true;
      closeNow();
      toast.dismiss(sseToastId);
    };
  }, [jobId, queryClient]);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/hooks/use-job-events.test.tsx && npx tsc -b`
Expected: PASS — including the two pre-existing regression tests "closes the EventSource when a job_snapshot reports terminal state" (its snapshot has no `related_status`, so the pending set is empty → immediate close) and "does not toast on the terminal-state error".

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/use-job-events.ts web/src/hooks/use-job-events.test.tsx
git commit -m "feat(web): relocate terminal SSE close behind pendingRelated drain with 10s cap"
```

---

### Task 12: Frontend `JobTracker` — history copy + deferred untrack

**Files:**
- Modify: `web/src/components/job-tracker.tsx` (the terminal effect, lines 25-79)
- Modify: `web/src/components/job-tracker.test.tsx`

**Interfaces:**
- Consumes: `HistoryItem.related` (Task 9); `UrlState.related/related_status` (Task 9/10).
- Produces: completed URLs' `related` copied into their `HistoryItem`; `removeQueries` stays at 1.5 s; `untrackJob` deferred to a flat 10 s when any completed URL is still `"pending"` at terminal.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/components/job-tracker.test.tsx` (uses the existing `completed()` factory; extend it inline via spreads):

```tsx
const RELATED = [{
  id: "n1", title: "Song", artist: "Artist", platform: "youtube" as const,
  webpage_url: "https://www.youtube.com/watch?v=n1", duration: 60, thumb_id: null,
}];

describe("JobTracker related persistence", () => {
  it("copies a completed URL's related items onto its history record", async () => {
    // This is also the tracker-side half of the back-to-back race fix
    // (Codex P2 on spec PR #52): when url_completed + url_related apply
    // synchronously BEFORE React flushes this effect, the snapshot the
    // effect reads is already patched — exactly what this test feeds it.
    // (The other half — a late url_related AFTER the history write —
    // is covered by the use-history updateItem and use-job-events
    // missing-record upsert tests.)
    const snap = completed();
    snap.urls[0].related_status = "ready";
    snap.urls[0].related = RELATED;
    const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
    act(() => {
      queryClient.setQueryData(["job", "job-1"], snap);
    });
    await screen.findByText(/added to library/i);
    const stored = JSON.parse(localStorage.getItem("audio_dl_history")!);
    expect(stored.items[0].url).toBe("https://a");
    expect(stored.items[0].related).toEqual(RELATED);
  });

  it("defers untrackJob to 10s when a completed URL is still pending, removeQueries still at 1.5s", async () => {
    vi.useFakeTimers();
    try {
      const snap = completed();
      snap.urls[0].related_status = "pending";
      const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
      act(() => {
        queryClient.setQueryData(["job", "job-1"], snap);
      });
      // Let the effect run.
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      const { useTrackedJobs, trackJob } = await import("@/lib/tracked-jobs");
      trackJob("job-1");
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      // Query record gone at 1.5s…
      expect(queryClient.getQueryData(["job", "job-1"])).toBeUndefined();
      // …but the job is still tracked (EventSource hook still mounted).
      const { result } = renderHook(() => useTrackedJobs());
      expect(result.current).toContain("job-1");
      await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
      expect(result.current).not.toContain("job-1");
    } finally {
      vi.useRealTimers();
    }
  });

  it("untracks at 1.5s when nothing is pending (unchanged behavior)", async () => {
    vi.useFakeTimers();
    try {
      const { trackJob, useTrackedJobs } = await import("@/lib/tracked-jobs");
      trackJob("job-1");
      const { queryClient } = renderWithToaster(<JobTracker jobId="job-1" />);
      act(() => {
        queryClient.setQueryData(["job", "job-1"], completed());
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      const { result } = renderHook(() => useTrackedJobs());
      expect(result.current).not.toContain("job-1");
    } finally {
      vi.useRealTimers();
    }
  });
});
```

Add the missing imports at the top of the file: `renderHook` from `@testing-library/react` (extend the existing import line) and `resetTrackedJobs` — and call `resetTrackedJobs()` inside the existing `beforeEach`:

```tsx
import { act, screen, waitFor, renderHook } from "@testing-library/react";
import { resetTrackedJobs } from "@/lib/tracked-jobs";
// in beforeEach:
  resetTrackedJobs();
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/components/job-tracker.test.tsx`
Expected: new tests FAIL (`related` missing from stored history; untrack fires at 1.5 s regardless).

- [ ] **Step 3: Implement**

In `web/src/components/job-tracker.tsx`:

(a) In the completed branch's `addItem` call (lines 27-35), add the `related` copy:

```ts
        addItem({
          url: u.url,
          title: u.title,
          artist: u.uploader,
          media_format: u.media_format,
          paths: u.paths,
          thumb_id: u.thumb_id,
          added_at: Date.now(),
          related: u.related?.length ? u.related : undefined,
        });
```

(b) Replace the single teardown timeout (lines 76-79) with the split version:

```ts
    // Visual teardown is unchanged: the card leaves the Now screen at 1.5s.
    setTimeout(() => {
      queryClient.removeQueries({ queryKey: ["job", jobId] });
    }, 1500);
    // untrackJob unmounts useJobEvents (closing its socket). When a completed
    // URL's discovery is still pending, defer to a flat 10s — matching the
    // server linger cap — so the late url_related can arrive and upsert.
    // No early-exit drain: the tracker has no channel to observe event
    // arrivals (the hook owns the socket, and late events route to history,
    // not this query), and a lingering headless component costs nothing.
    const hasPendingRelated = data.urls.some(
      (u) => u.state === "completed" && u.related_status === "pending"
    );
    setTimeout(() => {
      untrackJob(jobId);
    }, hasPendingRelated ? 10_000 : 1500);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/components/job-tracker.test.tsx && npx tsc -b`
Expected: PASS (all, including pre-existing toast tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/job-tracker.tsx web/src/components/job-tracker.test.tsx
git commit -m "feat(web): persist related items to history; defer untrack while discovery pending"
```

---

### Task 13: `RelatedStrip` component

**Files:**
- Create: `web/src/components/related-strip.tsx`
- Create: `web/src/components/related-strip.test.tsx`

**Interfaces:**
- Consumes: `RelatedItem` (Task 9); `AlbumArt` (`{thumbId, size}` props); `Button`; `postJobs`/`describeError`; `trackJob`; `useSettings().settings.default_format`; `toast`.
- Produces: `RelatedStrip({ items }: { items: RelatedItem[] })` → `null` when empty. Tiles: `data-testid="related-tile"`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/related-strip.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithToaster } from "@/test-utils/render";
import { resetToastStore } from "@/lib/toast-store";
import { resetTrackedJobs, useTrackedJobs } from "@/lib/tracked-jobs";
import { renderHook } from "@testing-library/react";
import { RelatedStrip } from "./related-strip";
import type { RelatedItem } from "@/lib/types";

vi.mock("@/lib/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/api")>();
  return { ...mod, postJobs: vi.fn(async () => ({ job_id: "job-new" })) };
});
import { postJobs } from "@/lib/api";

beforeEach(() => {
  resetToastStore();
  resetTrackedJobs();
  localStorage.clear();
  vi.mocked(postJobs).mockClear();
});

function items(n: number): RelatedItem[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `n${i}`,
    title: `Song ${i}`,
    artist: "Artist",
    platform: i % 2 ? ("soundcloud" as const) : ("youtube" as const),
    webpage_url: `https://example-platform/${i}`,
    duration: 60,
    thumb_id: null,
  }));
}

describe("RelatedStrip", () => {
  it("renders null when empty", () => {
    renderWithToaster(<RelatedStrip items={[]} />);
    expect(screen.queryByLabelText("Related music")).toBeNull();
    expect(screen.queryByText(/more like this/i)).toBeNull();
  });

  it("renders one tile per item with heading, platform label, and safe link attrs", () => {
    renderWithToaster(<RelatedStrip items={items(3)} />);
    expect(screen.getByText(/more like this/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("related-tile")).toHaveLength(3);
    expect(screen.getAllByText(/·\s*YouTube/)).not.toHaveLength(0);
    const link = screen.getAllByRole("link")[0];
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("href", "https://example-platform/0");
  });

  it("queue button posts the item URL in the default format and tracks the job", async () => {
    const user = userEvent.setup();
    renderWithToaster(<RelatedStrip items={items(1)} />);
    await user.click(screen.getByRole("button", { name: /download song 0/i }));
    await waitFor(() =>
      expect(postJobs).toHaveBeenCalledWith([
        { url: "https://example-platform/0", format: "m4a" },
      ])
    );
    const { result } = renderHook(() => useTrackedJobs());
    expect(result.current).toContain("job-new");
    expect(await screen.findByText(/queued/i)).toBeInTheDocument();
  });

  it("queue failure surfaces an error toast", async () => {
    vi.mocked(postJobs).mockRejectedValueOnce(new TypeError("net down"));
    const user = userEvent.setup();
    renderWithToaster(<RelatedStrip items={items(1)} />);
    await user.click(screen.getByRole("button", { name: /download song 0/i }));
    expect(await screen.findByText(/can't reach audio-dl/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/components/related-strip.test.tsx`
Expected: FAIL (`Cannot find module './related-strip'`)

- [ ] **Step 3: Implement `web/src/components/related-strip.tsx`**

```tsx
import { Download } from "lucide-react";
import { AlbumArt } from "./album-art";
import { Button } from "./ui/button";
import { postJobs, describeError } from "@/lib/api";
import { trackJob } from "@/lib/tracked-jobs";
import { useSettings } from "@/hooks/use-settings";
import { toast } from "@/lib/toast-store";
import type { RelatedItem } from "@/lib/types";

const PLATFORM_LABEL: Record<RelatedItem["platform"], string> = {
  youtube: "YouTube",
  soundcloud: "SoundCloud",
};

export function RelatedStrip({ items }: { items: RelatedItem[] }) {
  const { settings } = useSettings();
  if (items.length === 0) return null;

  async function queue(item: RelatedItem) {
    try {
      const r = await postJobs([
        { url: item.webpage_url, format: settings.default_format },
      ]);
      trackJob(r.job_id);
      toast.success("Queued", { description: item.title });
    } catch (err) {
      const { title, description } = describeError(err, "Couldn't queue download");
      toast.error(title, { description });
    }
  }

  return (
    <section aria-label="Related music" className="mx-8 mt-7 enter-fade">
      <div className="text-xs text-[var(--text-3)] font-medium mb-2">
        More like this
      </div>
      <div className="flex gap-3 overflow-x-auto pb-1">
        {items.map((item) => (
          <div
            key={`${item.platform}-${item.id}`}
            data-testid="related-tile"
            className="group relative w-[132px] flex-shrink-0"
          >
            <a
              href={item.webpage_url}
              target="_blank"
              rel="noopener noreferrer"
              className="block focus-ring rounded-[var(--radius-md)]"
            >
              <AlbumArt thumbId={item.thumb_id} size={120} />
              <div className="text-xs font-medium truncate mt-1.5">
                {item.title}
              </div>
              <div className="text-[11px] text-[var(--text-3)] truncate">
                {item.artist ? `${item.artist} · ` : ""}
                {PLATFORM_LABEL[item.platform]}
              </div>
            </a>
            {/* Sibling of the anchor, never nested inside it — nested
                interactive elements are invalid HTML. */}
            <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Download ${item.title}`}
                className="h-7 w-7 bg-[var(--surface)]/80 backdrop-blur-sm focus-ring"
                onClick={() => queue(item)}
              >
                <Download size={14} />
              </Button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/components/related-strip.test.tsx && npx tsc -b`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/related-strip.tsx web/src/components/related-strip.test.tsx
git commit -m "feat(web): RelatedStrip — thumbnail tiles with link-out and one-click queue"
```

---

### Task 14: Mount points — Now screen + idle stage

**Files:**
- Modify: `web/src/routes/index.tsx` (lines 29-35)
- Modify: `web/src/components/empty-stage.tsx`
- Modify: `web/src/components/empty-stage.test.tsx`

**Interfaces:**
- Consumes: `RelatedStrip` (Task 13); `UrlState.related` / `HistoryItem.related` (Task 9).
- Produces: strip under `HeroStage` for the staged job's `urls[0]`; strip on `EmptyStage` for `latest.related`.

- [ ] **Step 1: Write the failing test**

Append to `web/src/components/empty-stage.test.tsx`. Ensure these imports exist at the top of the file (add any that are missing — the file already tests `<EmptyStage latest={...} />` directly):

```tsx
import { screen } from "@testing-library/react";
import { renderWithToaster } from "@/test-utils/render";
import { EmptyStage } from "./empty-stage";
```

```tsx
  it("renders a related strip when the latest history item carries one", () => {
    renderWithToaster(
      <EmptyStage
        latest={{
          url: "https://a", title: "T", artist: "U", media_format: "m4a",
          paths: [], thumb_id: null, added_at: 1,
          related: [{
            id: "n1", title: "Song", artist: "Artist",
            platform: "youtube", webpage_url: "https://w",
            duration: 60, thumb_id: null,
          }],
        }}
      />
    );
    expect(screen.getByText(/more like this/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("related-tile")).toHaveLength(1);
  });

  it("renders no strip for pre-feature history records", () => {
    renderWithToaster(
      <EmptyStage
        latest={{
          url: "https://a", title: "T", artist: "U", media_format: "m4a",
          paths: [], thumb_id: null, added_at: 1,
        }}
      />
    );
    expect(screen.queryByText(/more like this/i)).toBeNull();
  });
```

If the existing file uses bare `render` from `@testing-library/react`, switch these two tests to `renderWithToaster` from `@/test-utils/render` (the strip's queue button needs the settings/toast environment only on click, but staying consistent with one helper avoids surprises).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/components/empty-stage.test.tsx`
Expected: the new tests FAIL (`more like this` not found).

- [ ] **Step 3: Implement**

`web/src/components/empty-stage.tsx` — add ONE new import (`AlbumArt` and `HistoryItem` are already imported at lines 1-2; duplicating them is a TS2300 error):

```tsx
import { RelatedStrip } from "./related-strip";
```

and change the non-null return to:

```tsx
  return (
    <>
      <div className="grid place-items-center px-8 pt-7 pb-4">
        <AlbumArt thumbId={latest.thumb_id} size={240} />
        <div className="text-center mt-6">
          <div className="text-[11px] uppercase tracking-[0.06em] font-bold text-[var(--text-2)] mb-2">
            Last added
          </div>
          <h2 className="text-[22px] font-bold tracking-[-0.02em] truncate max-w-[80vw] mx-auto">
            {latest.title ?? latest.url}
          </h2>
          {latest.artist && <p className="text-[var(--text-2)] text-sm mt-1">{latest.artist}</p>}
        </div>
      </div>
      <RelatedStrip items={latest.related ?? []} />
    </>
  );
```

`web/src/routes/index.tsx` — import `RelatedStrip` and mount inside the stage-keyed `enter-fade` wrapper (lines 29-35):

```tsx
import { RelatedStrip } from "@/components/related-strip";
```

```tsx
      {stageJob ? (
        <div key={stageJob.job_id} className="enter-fade">
          <HeroStage
            snapshot={stageJob}
            activeCount={activeJobs.filter((j) => j.state === "running").length}
          />
          <RelatedStrip items={stageJob.urls[0].related ?? []} />
        </div>
      ) : (
```

- [ ] **Step 4: Run the full web suite + build**

Run: `cd web && npm test && npm run build`
Expected: all tests PASS; `tsc -b && vite build` clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/index.tsx web/src/components/empty-stage.tsx web/src/components/empty-stage.test.tsx
git commit -m "feat(web): mount RelatedStrip under the hero stage and on the idle stage"
```

---

### Task 15: Version bump, CHANGELOG, CLAUDE.md, full verification

**Files:**
- Modify: `audio_dl.py` (`__version__` line only)
- Modify: `pyproject.toml` (`version`)
- Modify: `CHANGELOG.md`
- Modify: `CLAUDE.md` (Layout section + deep-dive links)

- [ ] **Step 1: Bump versions**

In `audio_dl.py`: `__version__ = "2.4.0"`. In `pyproject.toml`: `version = "2.4.0"`. (Dual-sourced by convention; `/release-helper` checks both. Originally targeted 2.3.0, but v2.3.0 shipped on 2026-07-03 as the landing-page/CSRF release — amended 2026-07-04.)

- [ ] **Step 2: CHANGELOG entry**

Add at the top of `CHANGELOG.md`:

```markdown
## v2.4 — Related-content discovery ("More like this")

- While a download runs, the web UI now discovers related tracks on
  YouTube (Mix radio) and SoundCloud (recommended + cross-platform artist
  search) via yt-dlp — no API keys, no new dependencies — and shows them
  as a thumbnail strip under the player with link-out and one-click queue.
- Results persist onto library history, so the idle screen keeps showing
  "More like this" for the latest download; late-arriving results are
  delivered through a short SSE linger and upserted.
- New `--no-related` flag disables all discovery egress.
```

- [ ] **Step 3: CLAUDE.md updates**

In the Layout section's `audio_dl_ui` bullet, add a sentence: "`audio_dl_ui/related.py` holds the pure related-content discovery logic (providers, normalization, selection); the trigger/executor/SSE glue stays in `__init__.py`." Add the spec to the deep-dive links list: `[related-content discovery](docs/superpowers/specs/2026-07-01-related-content-discovery-design.md)`.

- [ ] **Step 4: Full verification**

```bash
pytest -q                          # CLI + UI + related suites
pylint $(git ls-files '*.py')      # 10.00 required
cd web && npm test && npm run build && cd ..
```

Expected: everything green.

- [ ] **Step 5: Commit**

```bash
git add audio_dl.py pyproject.toml CHANGELOG.md CLAUDE.md
git commit -m "chore: v2.4.0 — related-content discovery release notes + docs"
```

---

## Execution notes

- **Task order is dependency order** — do not reorder. Tasks 1-8 are backend (Python), 9-14 frontend, 15 release chores. Backend and frontend halves are independent AFTER Task 8; a second worker could run Tasks 9-14 in parallel with review of 1-8 if desired.
- **Only Task 2 touches the network.** If it must run offline, take Branch B and leave a follow-up.
- The implementation PR must contain ONLY these commits (spec/plan docs are already on main). After squash-merge, sync local main with `git fetch origin && git reset --hard origin/main`.
