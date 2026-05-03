# pylint: disable=missing-function-docstring,missing-class-docstring
"""Tests for audio_dl.py — sanitize_url and detect_platform."""
from audio_dl import detect_platform, sanitize_url


# ---------------------------------------------------------------------------
# detect_platform
# ---------------------------------------------------------------------------

class TestDetectPlatform:
    def test_youtube_dot_com(self):
        assert detect_platform("https://www.youtube.com/watch?v=abc123") == "youtube"

    def test_youtu_be_short(self):
        assert detect_platform("https://youtu.be/abc123") == "youtube"

    def test_soundcloud(self):
        assert detect_platform("https://soundcloud.com/artist/track") == "soundcloud"

    def test_bunnystream_player_subdomain(self):
        assert detect_platform(
            "https://player.mediadelivery.net/embed/577374/60efdfe2-66fa-4a72-bc6a-cabc1c1704d6"
        ) == "bunnystream"

    def test_bunnystream_iframe_subdomain(self):
        assert detect_platform(
            "https://iframe.mediadelivery.net/embed/12345/some-guid"
        ) == "bunnystream"

    def test_unknown(self):
        assert detect_platform("https://example.com/audio.mp3") == "unknown"

    def test_lookalike_domain_not_bunnystream(self):
        # 'evilmediadelivery.net' contains 'mediadelivery.net' as a substring
        # but is not a subdomain of it — must return unknown
        assert detect_platform("https://evilmediadelivery.net/embed/1/2") == "unknown"

    def test_subdomain_spoof_not_bunnystream(self):
        # 'mediadelivery.net.evil.com' has mediadelivery.net as a sub-string
        # of a different hostname — must return unknown
        assert detect_platform("https://mediadelivery.net.evil.com/embed/1/2") == "unknown"


# ---------------------------------------------------------------------------
# sanitize_url — YouTube
# ---------------------------------------------------------------------------

class TestSanitizeUrlYouTube:
    def test_watch_url_stripped_to_video_id_only(self):
        result = sanitize_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share&si=abc"
        )
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_watch_url_preserves_t_param(self):
        result = sanitize_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42&feature=share"
        )
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42"

    def test_youtu_be_short_link(self):
        result = sanitize_url("https://youtu.be/dQw4w9WgXcQ")
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_shorts_url(self):
        result = sanitize_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_backslash_escapes_removed(self):
        result = sanitize_url(r"https://youtu.be/dQw4w9WgXcQ\?si\=abc")
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# ---------------------------------------------------------------------------
# sanitize_url — SoundCloud
# ---------------------------------------------------------------------------

class TestSanitizeUrlSoundCloud:
    def test_tracking_params_stripped(self):
        result = sanitize_url(
            "https://soundcloud.com/artist/track?utm_source=clipboard&utm_medium=text"
        )
        assert result == "https://soundcloud.com/artist/track"

    def test_secret_token_preserved(self):
        result = sanitize_url(
            "https://soundcloud.com/artist/private?secret_token=s-abc123&utm_source=x"
        )
        assert result == "https://soundcloud.com/artist/private?secret_token=s-abc123"


# ---------------------------------------------------------------------------
# sanitize_url — Bunny Stream
# ---------------------------------------------------------------------------

class TestSanitizeUrlBunnyStream:
    EMBED_URL = (
        "https://player.mediadelivery.net/embed/577374/"
        "60efdfe2-66fa-4a72-bc6a-cabc1c1704d6"
    )

    def test_player_ui_params_stripped(self):
        url_with_params = (
            self.EMBED_URL
            + "?autoplay=true&loop=false&muted=false&preload=false&responsive=true"
        )
        assert sanitize_url(url_with_params) == self.EMBED_URL

    def test_clean_embed_url_unchanged(self):
        assert sanitize_url(self.EMBED_URL) == self.EMBED_URL

    def test_iframe_subdomain_preserved(self):
        url = "https://iframe.mediadelivery.net/embed/12345/some-guid?autoplay=true"
        assert sanitize_url(url) == "https://iframe.mediadelivery.net/embed/12345/some-guid"

    def test_token_auth_params_preserved(self):
        # Access-controlled Bunny Stream videos require token + expires params
        url = self.EMBED_URL + "?token=abc123&expires=9999999999&autoplay=true"
        assert sanitize_url(url) == self.EMBED_URL + "?token=abc123&expires=9999999999"

    def test_credentials_not_leaked_in_output(self):
        # parsed.netloc includes user:pass@ — must not appear in sanitized URL
        url = "https://user:pass@player.mediadelivery.net/embed/577374/some-guid"
        result = sanitize_url(url)
        assert "user" not in result
        assert "pass" not in result
        assert result == "https://player.mediadelivery.net/embed/577374/some-guid"

    def test_lookalike_domain_not_sanitized(self):
        # evilmediadelivery.net should pass through unchanged, not enter the Bunny branch
        url = "https://evilmediadelivery.net/embed/1/2?autoplay=true"
        assert sanitize_url(url) == url


# ---------------------------------------------------------------------------
# sanitize_url — unknown / passthrough
# ---------------------------------------------------------------------------

class TestSanitizeUrlUnknown:
    def test_unknown_url_with_params_returned_unchanged(self):
        url = "https://example.com/audio.mp3?token=xyz"
        assert sanitize_url(url) == url

    def test_unknown_url_no_params_returned_unchanged(self):
        url = "https://example.com/audio.mp3"
        assert sanitize_url(url) == url
