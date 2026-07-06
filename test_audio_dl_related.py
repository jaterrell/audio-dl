# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
# pylint: disable=protected-access,import-outside-toplevel
"""Tests for audio_dl_ui.related — pure discovery logic, no network."""
from unittest.mock import patch

import pytest

# Later tasks EXTEND this import block in place — never append a new
# module-level import after code below (pylint C0413 wrong-import-position).
from audio_dl_ui.related import (
    resolve_artist,
    is_allowed_thumb_url,
    _pick_thumbnail_url,
    build_native_query,
    build_search_query,
    normalize_entry,
    select_items,
    discover,
    SC_NATIVE_PATH_ENABLED,
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


# ---------------------------------------------------------------------------
# Fixtures captured from live yt-dlp probes (2026-07-01 and this task's probe).
# These are REAL flat-extraction entry shapes — do not invent fields.
#
# 2026-07-03 probe of https://soundcloud.com/daftpunkofficialmusic/
# one-more-time/recommended (yt-dlp 2026.03.17, extract_flat=True): the
# network call succeeded (6 entries returned) but each entry came back as a
# bare url-reference stub — only `_type`, `ie_key`, `id`, `title`, `url`
# (the `url` here is a soundcloud.com permalink, not the api.soundcloud.com
# track URL `scsearch` entries carry). No `webpage_url`, `uploader`,
# `artists`, `duration`, or `thumbnails` — does not match the `scsearch`
# shape the native path needs. Per the spec's gating rule, the SoundCloud
# native path ships disabled; see "Open follow-ups" in the design spec.
# ---------------------------------------------------------------------------

SC_NATIVE_ENABLED = False  # /recommended probe returned shallow url-stub
# entries (no webpage_url); native path deferred — see spec follow-ups.

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

# Native path gated off (SC_NATIVE_ENABLED = False) — placeholder so imports
# resolve; nothing consumes this as a real /recommended shape.
SC_RECOMMENDED_ENTRY = SC_SEARCH_ENTRY


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
