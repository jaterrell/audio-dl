# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
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


# ---------------------------------------------------------------------------
# POST /jobs — validation
# ---------------------------------------------------------------------------

def _valid_body(**overrides):
    body = {
        "urls": "https://youtu.be/dQw4w9WgXcQ",
        "format": "mp3",
        "output_dir": "/tmp/audio-dl-test",
        "playlist": False,
        "force": False,
        "fragments": 4,
        "jobs": 1,
    }
    body.update(overrides)
    return body


class TestPostJobsValidation:
    def test_empty_urls_400(self):
        r = client.post("/jobs", json=_valid_body(urls=""))
        assert r.status_code == 400
        assert "url" in r.json()["detail"].lower()

    def test_whitespace_only_urls_400(self):
        r = client.post("/jobs", json=_valid_body(urls="   \n  \t  "))
        assert r.status_code == 400

    def test_bad_format_400(self):
        r = client.post("/jobs", json=_valid_body(format="ogg"))
        assert r.status_code == 400
        assert "format" in r.json()["detail"].lower()

    def test_jobs_too_low_400(self):
        r = client.post("/jobs", json=_valid_body(jobs=0))
        assert r.status_code == 400

    def test_jobs_too_high_400(self):
        r = client.post("/jobs", json=_valid_body(jobs=9))
        assert r.status_code == 400

    def test_fragments_too_low_400(self):
        r = client.post("/jobs", json=_valid_body(fragments=0))
        assert r.status_code == 400

    def test_fragments_too_high_400(self):
        r = client.post("/jobs", json=_valid_body(fragments=17))
        assert r.status_code == 400

    def test_unwritable_output_dir_400(self):
        # /dev/null/foo will fail os.makedirs with NotADirectoryError on macOS/Linux
        r = client.post("/jobs", json=_valid_body(output_dir="/dev/null/cant-make-this"))
        assert r.status_code == 400
        assert "output" in r.json()["detail"].lower()
