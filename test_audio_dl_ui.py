# pylint: disable=missing-function-docstring,missing-class-docstring
"""Tests for audio_dl_ui.py — validation, SSE, cancel, reveal, throttle."""
from fastapi.testclient import TestClient

from audio_dl_ui import app


client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestIndex:
    def test_returns_html(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "audio-dl" in r.text
