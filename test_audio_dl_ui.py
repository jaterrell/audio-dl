# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
# pylint: disable=import-outside-toplevel,reimported,redefined-outer-name,protected-access,unused-argument
"""Tests for audio_dl_ui.py — validation, SSE, cancel, reveal, throttle."""
import json
import threading
import time

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
        assert "${url}" not in r.text


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
    def test_returns_job_id(self, tmp_path, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "download_media", lambda *a, **kw: [])
        body = _valid_body(output_dir=str(tmp_path))
        r = client.post("/jobs", json=body)
        assert r.status_code == 200
        data = r.json()
        assert "job_id" in data
        assert isinstance(data["job_id"], str) and len(data["job_id"]) >= 16

    def test_registers_in_jobs_dict(self, tmp_path, monkeypatch):
        import audio_dl_ui as ui
        # Block download_media so we can inspect state before it transitions.
        import threading as _threading
        gate = _threading.Event()

        def _blocking_download(*_args, **_kwargs):
            gate.wait()  # hold until the test releases
            return []

        monkeypatch.setattr(ui, "download_media", _blocking_download)

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
        # All URLs should be in a known valid state (pending or downloading).
        valid_initial = {"pending", "downloading"}
        for state in job.url_states.values():
            assert state.status in valid_initial
        gate.set()  # release the blocked workers


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


# ---------------------------------------------------------------------------
# End-to-end: SSE happy path with mocked download_media
# ---------------------------------------------------------------------------

class TestSseHappyPath:
    def test_sse_event_sequence(self, tmp_path, monkeypatch):
        """
        Mock download_media to emit 2 fake progress events into the hook,
        then return a synthetic path. Open POST /jobs, then GET
        /jobs/{id}/events, and assert the event order over SSE.
        """
        import audio_dl_ui as ui

        fake_path = str(tmp_path / "song.mp3")
        # Pre-create the file so the worker's path bookkeeping is realistic.
        (tmp_path / "song.mp3").write_bytes(b"x")

        def fake_download(_url, *, progress_hooks=None, **_kwargs):
            assert progress_hooks, "worker must wire in a hook"
            hook = progress_hooks[0]
            hook({"status": "downloading", "downloaded_bytes": 50,
                  "total_bytes": 100, "speed": 1024, "eta": 1,
                  "filename": fake_path})
            # Force a clock advance past the throttle window so the second
            # progress event actually emits.
            time.sleep(0.25)
            hook({"status": "downloading", "downloaded_bytes": 100,
                  "total_bytes": 100, "speed": 1024, "eta": 0,
                  "filename": fake_path})
            return [fake_path]

        monkeypatch.setattr(ui, "download_media", fake_download)

        body = _valid_body(
            urls="https://youtu.be/AAA",
            output_dir=str(tmp_path),
        )
        r = client.post("/jobs", json=body)
        job_id = r.json()["job_id"]

        # Drain SSE stream synchronously; TestClient yields chunks.
        with client.stream("GET", f"/jobs/{job_id}/events", timeout=10) as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if not line or line.startswith(": "):  # blank lines + keepalives
                    continue
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                if events and events[-1].get("type") == "job_completed":
                    break

        types = [e["type"] for e in events]
        assert types[0] == "job_started"
        assert "url_started" in types
        assert "url_completed" in types
        assert types[-1] == "job_completed"
        # Find the url_completed event and check the path.
        completed = next(e for e in events if e["type"] == "url_completed")
        assert completed["paths"] == [fake_path]
        # Summary in job_completed.
        last = events[-1]
        assert last["summary"]["completed"] == 1
        assert last["summary"]["failed"] == 0


# ---------------------------------------------------------------------------
# POST /jobs/{id}/cancel
# ---------------------------------------------------------------------------

class TestCancel:
    def test_unknown_job_404(self):
        r = client.post("/jobs/does-not-exist/cancel")
        assert r.status_code == 404

    def test_sets_flag_and_calls_shutdown(self, tmp_path, monkeypatch):
        import audio_dl_ui as ui

        # Mock download_media to block until cancelled.
        started = threading.Event()
        cancelled = threading.Event()

        def fake_download(url, *, progress_hooks=None, **_kw):
            started.set()
            # Poll the hook repeatedly until it raises _Cancelled or 5s elapses.
            hook = progress_hooks[0]
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    hook({"status": "downloading", "downloaded_bytes": 1,
                          "total_bytes": 100})
                except ui._Cancelled:
                    cancelled.set()
                    raise
                time.sleep(0.05)
            return ["/never"]

        monkeypatch.setattr(ui, "download_media", fake_download)

        body = _valid_body(urls="https://youtu.be/AAA", output_dir=str(tmp_path))
        r = client.post("/jobs", json=body)
        job_id = r.json()["job_id"]

        # Wait for worker to start, then cancel.
        assert started.wait(timeout=2.0), "fake_download never started"
        r2 = client.post(f"/jobs/{job_id}/cancel")
        assert r2.status_code == 200
        assert r2.json() == {"ok": True}

        # The hook should raise _Cancelled within a tick.
        assert cancelled.wait(timeout=2.0), "hook never raised _Cancelled"

        # JOBS[job_id].cancelled is True.
        from audio_dl_ui import JOBS
        assert JOBS[job_id].cancelled is True


# ---------------------------------------------------------------------------
# POST /reveal
# ---------------------------------------------------------------------------

class TestReveal:
    def test_unknown_path_400(self, monkeypatch):
        import audio_dl_ui as ui
        called = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda *a, **kw: called.append((a, kw)) or None,
        )
        r = client.post("/reveal", json={"path": "/etc/passwd"})
        assert r.status_code == 400
        assert not called, "subprocess.run must not be invoked for unknown paths"

    def test_known_path_calls_open_dash_r(self, tmp_path, monkeypatch):
        """Register a path in a fake job, then reveal it."""
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, JobState, UrlState
        import queue as _q

        path = str(tmp_path / "song.mp3")
        (tmp_path / "song.mp3").write_bytes(b"x")

        job = JobState(
            id="manual", media_format="mp3", output_dir=str(tmp_path),
            playlist=False, force=False, fragments=4, jobs=1,
            url_states={"u": UrlState(url="u", paths=[path], status="completed")},
            queue=_q.Queue(),
        )
        JOBS["manual"] = job

        try:
            called = []
            monkeypatch.setattr(
                ui.subprocess, "run",
                lambda *a, **kw: called.append((a, kw)) or None,
            )
            r = client.post("/reveal", json={"path": path})
            assert r.status_code == 200
            assert r.json() == {"ok": True}
            assert called == [((["open", "-R", path],), {"check": False})]
        finally:
            del JOBS["manual"]


# ---------------------------------------------------------------------------
# GET /jobs/{id}/events — 404
# ---------------------------------------------------------------------------

class TestSseUnknownJob:
    def test_unknown_job_404(self):
        r = client.get("/jobs/does-not-exist/events")
        assert r.status_code == 404
