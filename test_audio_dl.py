# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
# pylint: disable=import-outside-toplevel,protected-access
"""Tests for audio_dl.py — sanitize_url, detect_platform, _build_ydl_opts,
_check_dependencies."""
import pytest

from audio_dl import (
    ALL_FORMATS,
    AUDIO_FORMATS,
    VIDEO_FORMATS,
    _build_ydl_opts,
    _check_dependencies,
    check_dependencies,
    detect_platform,
    sanitize_url,
)


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

    def test_lookalike_domain_not_youtube(self):
        # 'evilyoutube.com' contains 'youtube.com' as a substring but is not
        # a subdomain — must return unknown
        assert detect_platform("https://evilyoutube.com/watch?v=abc") == "unknown"

    def test_subdomain_spoof_not_youtube(self):
        # 'youtube.com.evil.test' has youtube.com as a substring of a
        # different hostname — must return unknown
        assert detect_platform("https://youtube.com.evil.test/watch?v=abc") == "unknown"

    def test_youtu_be_lookalike_not_youtube(self):
        # 'evilyoutu.be' contains 'youtu.be' as a substring — must return unknown
        assert detect_platform("https://evilyoutu.be/abc") == "unknown"

    def test_lookalike_domain_not_soundcloud(self):
        # 'evilsoundcloud.com' contains 'soundcloud.com' as a substring but
        # is not a subdomain — must return unknown
        assert detect_platform("https://evilsoundcloud.com/artist/track") == "unknown"

    def test_subdomain_spoof_not_soundcloud(self):
        # 'soundcloud.com.evil.test' has soundcloud.com as a substring of a
        # different hostname — must return unknown
        assert detect_platform("https://soundcloud.com.evil.test/artist/track") == "unknown"


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

    def test_youtube_subdomain_spoof_not_sanitized(self):
        # youtube.com.evil.test must pass through unchanged, not enter the YouTube branch
        url = "https://youtube.com.evil.test/watch?v=abc&utm=1"
        assert sanitize_url(url) == url

    def test_youtu_be_subdomain_spoof_not_sanitized(self):
        # youtu.be.evil.test must pass through unchanged
        url = "https://youtu.be.evil.test/abc?utm=1"
        assert sanitize_url(url) == url


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

    def test_soundcloud_subdomain_spoof_not_sanitized(self):
        # soundcloud.com.evil.test must pass through unchanged, not enter the SoundCloud branch
        url = "https://soundcloud.com.evil.test/artist/track?utm=1"
        assert sanitize_url(url) == url


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


# ---------------------------------------------------------------------------
# _build_ydl_opts — option-dict construction is the critical seam between
# our config and yt-dlp. These tests pin down the exact behavior expected
# from the post-processing pipeline so a regression in branching logic
# fails loudly without needing a live yt-dlp call.
# ---------------------------------------------------------------------------

DEFAULT_OPTS = {
    "output_dir": ".",
    "playlist": False,
    "force": False,
    "concurrent_fragments": 4,
    "platform": "youtube",
}


def _pp_keys(opts):
    """Return the postprocessor keys in order."""
    return [pp["key"] for pp in opts["postprocessors"]]


def _extract_audio_pp(opts):
    """Pull the FFmpegExtractAudio postprocessor out of opts (or None)."""
    for pp in opts["postprocessors"]:
        if pp["key"] == "FFmpegExtractAudio":
            return pp
    return None


class TestFormatConstants:
    def test_audio_and_video_formats_disjoint(self):
        assert set(AUDIO_FORMATS).isdisjoint(set(VIDEO_FORMATS))

    def test_all_formats_is_union(self):
        assert set(ALL_FORMATS) == set(AUDIO_FORMATS) | set(VIDEO_FORMATS)


class TestBuildYdlOptsAudio:
    def test_mp3_uses_320_quality_and_extract_audio(self):
        opts = _build_ydl_opts(media_format="mp3", **DEFAULT_OPTS)
        assert opts["format"] == "bestaudio/best"
        assert "merge_output_format" not in opts
        pp = _extract_audio_pp(opts)
        assert pp is not None
        assert pp["preferredcodec"] == "mp3"
        assert pp["preferredquality"] == "320"

    def test_m4a_uses_256_quality(self):
        opts = _build_ydl_opts(media_format="m4a", **DEFAULT_OPTS)
        pp = _extract_audio_pp(opts)
        assert pp["preferredcodec"] == "m4a"
        assert pp["preferredquality"] == "256"

    def test_flac_no_quality_param(self):
        # Lossless: yt-dlp shouldn't be told a target bitrate.
        opts = _build_ydl_opts(media_format="flac", **DEFAULT_OPTS)
        pp = _extract_audio_pp(opts)
        assert pp["preferredcodec"] == "flac"
        assert "preferredquality" not in pp

    def test_alac_codec_passed_through(self):
        opts = _build_ydl_opts(media_format="alac", **DEFAULT_OPTS)
        pp = _extract_audio_pp(opts)
        assert pp["preferredcodec"] == "alac"
        assert "preferredquality" not in pp

    def test_opus_no_quality_and_embeds_thumbnail(self):
        opts = _build_ydl_opts(media_format="opus", **DEFAULT_OPTS)
        pp = _extract_audio_pp(opts)
        assert pp["preferredcodec"] == "opus"
        assert "preferredquality" not in pp
        assert "EmbedThumbnail" in _pp_keys(opts)
        assert opts["writethumbnail"] is True

    def test_wav_skips_thumbnail_pipeline(self):
        # WAV containers don't support embedded artwork; confirm the
        # entire thumbnail pipeline is disabled, not just the embed step.
        opts = _build_ydl_opts(media_format="wav", **DEFAULT_OPTS)
        assert "EmbedThumbnail" not in _pp_keys(opts)
        assert opts["writethumbnail"] is False

    def test_metadata_postprocessor_always_present(self):
        for fmt in AUDIO_FORMATS:
            opts = _build_ydl_opts(media_format=fmt, **DEFAULT_OPTS)
            assert "FFmpegMetadata" in _pp_keys(opts), f"missing for {fmt}"


class TestBuildYdlOptsVideo:
    def test_mp4_uses_video_format_string(self):
        opts = _build_ydl_opts(media_format="mp4", **DEFAULT_OPTS)
        assert opts["format"] == "bestvideo*+bestaudio/best"

    def test_mp4_sets_merge_output_format(self):
        opts = _build_ydl_opts(media_format="mp4", **DEFAULT_OPTS)
        assert opts["merge_output_format"] == "mp4"

    def test_mp4_does_not_extract_audio(self):
        # Critical: the FFmpegExtractAudio postprocessor would strip
        # the video stream. It must not appear in video mode.
        opts = _build_ydl_opts(media_format="mp4", **DEFAULT_OPTS)
        assert _extract_audio_pp(opts) is None
        assert "FFmpegExtractAudio" not in _pp_keys(opts)

    def test_mp4_keeps_metadata_and_thumbnail(self):
        opts = _build_ydl_opts(media_format="mp4", **DEFAULT_OPTS)
        keys = _pp_keys(opts)
        assert "FFmpegMetadata" in keys
        assert "EmbedThumbnail" in keys
        assert opts["writethumbnail"] is True


class TestBuildYdlOptsCommon:
    def test_force_sets_overwrites(self):
        opts = _build_ydl_opts(
            media_format="mp3",
            output_dir=".",
            playlist=False,
            force=True,
            concurrent_fragments=4,
            platform="youtube",
        )
        assert opts["overwrites"] is True

    def test_no_force_omits_overwrites(self):
        opts = _build_ydl_opts(media_format="mp3", **DEFAULT_OPTS)
        assert "overwrites" not in opts

    def test_playlist_changes_outtmpl(self):
        opts = _build_ydl_opts(
            media_format="mp3",
            output_dir="/tmp/out",
            playlist=True,
            force=False,
            concurrent_fragments=4,
            platform="youtube",
        )
        assert "%(playlist_title)s" in opts["outtmpl"]
        assert opts["noplaylist"] is False

    def test_single_track_uses_flat_outtmpl(self):
        opts = _build_ydl_opts(
            media_format="mp3",
            output_dir="/tmp/out",
            playlist=False,
            force=False,
            concurrent_fragments=4,
            platform="youtube",
        )
        assert "%(playlist_title)s" not in opts["outtmpl"]
        assert opts["noplaylist"] is True

    def test_sc_auth_only_applied_for_soundcloud(self):
        opts = _build_ydl_opts(
            media_format="mp3", sc_auth="tok123",
            output_dir=".", playlist=False, force=False,
            concurrent_fragments=4, platform="youtube",
        )
        assert "http_headers" not in opts

        opts = _build_ydl_opts(
            media_format="mp3", sc_auth="tok123",
            output_dir=".", playlist=False, force=False,
            concurrent_fragments=4, platform="soundcloud",
        )
        assert opts["http_headers"]["Authorization"] == "OAuth tok123"

    def test_cookies_file_passed_through(self):
        opts = _build_ydl_opts(
            media_format="mp3", cookies="/tmp/c.txt",
            output_dir=".", playlist=False, force=False,
            concurrent_fragments=4, platform="youtube",
        )
        assert opts["cookiefile"] == "/tmp/c.txt"

    def test_cookies_from_browser_passed_as_tuple(self):
        # yt-dlp expects cookiesfrombrowser as a tuple, not a bare string.
        opts = _build_ydl_opts(
            media_format="mp3", cookies_from_browser="chrome",
            output_dir=".", playlist=False, force=False,
            concurrent_fragments=4, platform="youtube",
        )
        assert opts["cookiesfrombrowser"] == ("chrome",)

    def test_concurrent_fragments_passed_through(self):
        opts = _build_ydl_opts(
            media_format="mp3",
            output_dir=".", playlist=False, force=False,
            concurrent_fragments=8, platform="youtube",
        )
        assert opts["concurrent_fragment_downloads"] == 8


# ---------------------------------------------------------------------------
# _build_ydl_opts — progress_hooks
# ---------------------------------------------------------------------------

class TestBuildYdlOptsProgressHooks:
    def _opts(self, **kwargs):
        defaults = {
            "media_format": "mp3",
            "output_dir": ".",
            "playlist": False,
            "force": False,
            "concurrent_fragments": 4,
            "platform": "youtube",
        }
        defaults.update(kwargs)
        return _build_ydl_opts(**defaults)

    def test_progress_hooks_passed_through(self):
        def hook(_d):
            pass
        opts = self._opts(progress_hooks=[hook])
        assert opts["progress_hooks"] == [hook]

    def test_progress_hooks_absent_when_none(self):
        opts = self._opts(progress_hooks=None)
        assert "progress_hooks" not in opts

    def test_progress_hooks_omitted_default(self):
        opts = self._opts()
        assert "progress_hooks" not in opts


# ---------------------------------------------------------------------------
# _check_dependencies  (pure function used by both CLI and the .app bundle UI)
# ---------------------------------------------------------------------------

class TestCheckDependencies:
    def test_empty_when_all_present(self, monkeypatch):
        monkeypatch.setattr("audio_dl.shutil.which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr("audio_dl.importlib.util.find_spec", lambda _mod: object())
        assert not _check_dependencies()

    def test_reports_missing_ffmpeg(self, monkeypatch):
        monkeypatch.setattr("audio_dl.shutil.which", lambda _name: None)
        monkeypatch.setattr("audio_dl.importlib.util.find_spec", lambda _mod: object())
        problems = _check_dependencies()
        assert problems, "expected at least one problem line"
        assert any("ffmpeg is not installed" in line for line in problems)
        assert any("brew install ffmpeg" in line for line in problems)

    def test_reports_missing_yt_dlp(self, monkeypatch):
        monkeypatch.setattr("audio_dl.shutil.which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr("audio_dl.importlib.util.find_spec", lambda _mod: None)
        problems = _check_dependencies()
        assert any("yt-dlp is not installed" in line for line in problems)
        assert any("pip install yt-dlp" in line for line in problems)

    def test_reports_both_when_both_missing(self, monkeypatch):
        monkeypatch.setattr("audio_dl.shutil.which", lambda _name: None)
        monkeypatch.setattr("audio_dl.importlib.util.find_spec", lambda _mod: None)
        problems = _check_dependencies()
        assert any("ffmpeg" in line for line in problems)
        assert any("yt-dlp" in line for line in problems)

    def test_indented_lines_for_install_hints(self, monkeypatch):
        # Install-hint lines must be indented so callers can distinguish them
        # from summary lines (CLI prefixes only summaries with "ERROR: ").
        monkeypatch.setattr("audio_dl.shutil.which", lambda _name: None)
        monkeypatch.setattr("audio_dl.importlib.util.find_spec", lambda _mod: object())
        problems = _check_dependencies()
        hint_lines = [line for line in problems if "brew install" in line
                      or "apt install" in line or "ffmpeg.org" in line]
        assert hint_lines
        assert all(line.startswith(" ") for line in hint_lines)


class TestCheckDependenciesCliWrapper:
    def test_returns_silently_when_all_present(self, monkeypatch, capsys):
        monkeypatch.setattr("audio_dl.shutil.which", lambda _name: "/usr/bin/ffmpeg")
        monkeypatch.setattr("audio_dl.importlib.util.find_spec", lambda _mod: object())
        check_dependencies()
        assert capsys.readouterr().out == ""

    def test_prints_error_prefix_and_exits_when_missing(self, monkeypatch, capsys):
        monkeypatch.setattr("audio_dl.shutil.which", lambda _name: None)
        monkeypatch.setattr("audio_dl.importlib.util.find_spec", lambda _mod: object())
        with pytest.raises(SystemExit) as excinfo:
            check_dependencies()
        assert excinfo.value.code == 1
        out = capsys.readouterr().out
        assert out.startswith("ERROR: ffmpeg")
        assert "  macOS:   brew install ffmpeg" in out


# ---------------------------------------------------------------------------
# Bundle entry shim and PyInstaller spec
# ---------------------------------------------------------------------------

class TestAppEntry:
    def test_imports_without_side_effects(self):
        """``import _app_entry`` must not call main() or alter sys.argv."""
        import sys
        import importlib
        original_argv = list(sys.argv)
        try:
            sys.modules.pop("_app_entry", None)
            mod = importlib.import_module("_app_entry")
        finally:
            sys.argv = original_argv
        assert callable(getattr(mod, "_main", None))

    def test_strips_argv_before_delegating(self, monkeypatch):
        """_main() must clear Finder-injected argv before calling audio_dl_ui.main."""
        import sys
        import importlib
        mod = importlib.import_module("_app_entry")
        captured: dict[str, list[str]] = {}

        def fake_main():
            captured["argv"] = list(sys.argv)

        monkeypatch.setattr("audio_dl_ui.main", fake_main)
        monkeypatch.setattr(sys, "argv", ["audio-dl", "-psn_0_12345", "garbage"])
        mod._main()
        assert captured["argv"] == ["audio-dl"]


class TestAppEntryHomebrewPathBootstrap:
    """codex review-1 REQUIRED #1: Finder-launched .app does not inherit shell PATH,
    so Homebrew prefixes are missing and ffmpeg appears absent. The shim must
    prepend the Homebrew prefixes before audio_dl_ui imports."""

    def test_prepends_apple_silicon_and_intel_prefixes_when_missing(self):
        import importlib
        mod = importlib.import_module("_app_entry")
        env = {"PATH": "/usr/bin:/bin"}
        mod._bootstrap_homebrew_path(env)
        parts = env["PATH"].split(":")
        assert "/opt/homebrew/bin" in parts
        assert "/usr/local/bin" in parts
        # Apple Silicon (priority) must come before Intel.
        assert parts.index("/opt/homebrew/bin") < parts.index("/usr/local/bin")
        # User's existing entries must be preserved.
        assert "/usr/bin" in parts
        assert "/bin" in parts

    def test_idempotent_when_prefixes_already_present(self):
        import importlib
        mod = importlib.import_module("_app_entry")
        env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin"}
        before = env["PATH"]
        mod._bootstrap_homebrew_path(env)
        # No duplicate entries, no reorder of existing ones.
        assert env["PATH"] == before

    def test_handles_empty_path(self):
        import importlib
        mod = importlib.import_module("_app_entry")
        env: dict[str, str] = {}
        mod._bootstrap_homebrew_path(env)
        parts = env["PATH"].split(":")
        assert "/opt/homebrew/bin" in parts
        assert "/usr/local/bin" in parts

    def test_main_calls_bootstrap_before_audio_dl_ui_import(self, monkeypatch):
        """The bootstrap must run before audio_dl_ui.main is invoked so the
        dependency check inside main() sees the updated PATH."""
        import sys
        import importlib
        mod = importlib.import_module("_app_entry")
        order: list[str] = []

        original_bootstrap = mod._bootstrap_homebrew_path
        def traced_bootstrap(env=None):
            order.append("bootstrap")
            original_bootstrap(env)
        monkeypatch.setattr(mod, "_bootstrap_homebrew_path", traced_bootstrap)

        def fake_main():
            order.append("ui_main")
        monkeypatch.setattr("audio_dl_ui.main", fake_main)
        monkeypatch.setattr(sys, "argv", ["audio-dl"])
        mod._main()
        assert order == ["bootstrap", "ui_main"], order


class TestPyInstallerSpec:
    def test_spec_file_is_valid_python(self):
        """audio-dl.spec must compile — PyInstaller globals are injected at run time."""
        import pathlib
        import py_compile
        import tempfile
        spec = pathlib.Path(__file__).parent / "audio-dl.spec"
        assert spec.exists(), "audio-dl.spec missing"
        with tempfile.NamedTemporaryFile(suffix=".pyc", delete=True) as tmp:
            # ``doraise=True`` raises py_compile.PyCompileError on syntax errors.
            py_compile.compile(str(spec), cfile=tmp.name, doraise=True)

    def test_spec_references_version_source(self):
        """Spec must read __version__ from audio_dl.py — single source of truth."""
        import pathlib
        spec_text = (pathlib.Path(__file__).parent / "audio-dl.spec").read_text()
        # The regex-read mechanism keeps the bundle version in sync with the
        # CLI version without a third place to bump.
        assert "audio_dl.py" in spec_text
        assert "__version__" in spec_text

    def test_spec_targets_app_entry_shim(self):
        """Spec must analyse _app_entry.py, not audio_dl_ui.py directly."""
        import pathlib
        spec_text = (pathlib.Path(__file__).parent / "audio-dl.spec").read_text()
        assert "_app_entry.py" in spec_text
