# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
"""Tests for audio_dl_ui.py — validation, SSE, cancel, reveal, throttle."""
from fastapi.testclient import TestClient

from audio_dl_ui import app, JOBS


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


# ---------------------------------------------------------------------------
# POST /jobs — happy path (registers JobState)
# ---------------------------------------------------------------------------

class TestPostJobsHappyPath:
    def test_returns_job_id(self, tmp_path):
        body = _valid_body(output_dir=str(tmp_path))
        r = client.post("/jobs", json=body)
        assert r.status_code == 200
        data = r.json()
        assert "job_id" in data
        assert isinstance(data["job_id"], str) and len(data["job_id"]) >= 16

    def test_registers_in_jobs_dict(self, tmp_path):
        body = _valid_body(
            urls="https://youtu.be/AAA https://youtu.be/BBB",
            output_dir=str(tmp_path),
            jobs=2,
        )
        r = client.post("/jobs", json=body)
        job_id = r.json()["job_id"]
        job = JOBS[job_id]
        assert job.media_format == "mp3"
        assert job.jobs == 2
        assert set(job.url_states.keys()) == {"https://youtu.be/AAA", "https://youtu.be/BBB"}
        for state in job.url_states.values():
            assert state.status == "pending"


# ---------------------------------------------------------------------------
# Progress hook — throttle + cancel
# ---------------------------------------------------------------------------

class TestProgressHook:
    def _make_job(self):
        import queue as _q
        from audio_dl_ui import JobState, UrlState
        url = "https://youtu.be/AAA"
        job = JobState(
            id="job-test",
            media_format="mp3",
            output_dir="/tmp",
            playlist=False,
            force=False,
            fragments=4,
            jobs=1,
            url_states={url: UrlState(url=url)},
            queue=_q.Queue(),
        )
        return job, job.url_states[url]

    def test_throttle_caps_event_rate(self, monkeypatch):
        from audio_dl_ui import _make_progress_hook
        import audio_dl_ui

        job, url_state = self._make_job()
        # Fake clock: each call advances by 0.001s (1ms). 1000 ticks => 1s elapsed.
        ticks = [0.0]
        def fake_monotonic():
            ticks[0] += 0.001
            return ticks[0]
        monkeypatch.setattr(audio_dl_ui.time, "monotonic", fake_monotonic)

        hook = _make_progress_hook(job, url_state)
        for _ in range(1000):
            hook({
                "status": "downloading",
                "downloaded_bytes": 100,
                "total_bytes": 1000,
                "speed": 1024,
                "eta": 5,
                "filename": "x.mp3",
            })
        # 1 second of 1ms ticks; throttle is 200ms => ~5 events, ±1.
        emitted = [job.queue.get_nowait() for _ in range(job.queue.qsize())]
        assert 4 <= len(emitted) <= 6, f"got {len(emitted)} events"
        assert all(e["type"] == "progress" for e in emitted)

    def test_non_downloading_status_ignored(self):
        from audio_dl_ui import _make_progress_hook
        job, url_state = self._make_job()
        hook = _make_progress_hook(job, url_state)
        hook({"status": "finished", "downloaded_bytes": 0})
        assert job.queue.empty()

    def test_cancel_flag_raises(self):
        from audio_dl_ui import _make_progress_hook, _Cancelled
        job, url_state = self._make_job()
        hook = _make_progress_hook(job, url_state)
        job.cancelled = True
        import pytest
        with pytest.raises(_Cancelled):
            hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 100})
