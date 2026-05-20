# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
# pylint: disable=import-outside-toplevel,reimported,redefined-outer-name,protected-access,unused-argument
# pylint: disable=too-many-lines
"""Tests for audio_dl_ui.py — validation, SSE, cancel, reveal, throttle."""
import collections
import json
import os
import queue
import re
import threading
import time
from pathlib import Path

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from audio_dl_ui import (
    app,
    JOBS,
    _should_keep_log,
    _pick_thumbnail_url,
    UrlState,
    _make_url_logger,
    JobState,
)

# Set a known CSRF token at module load so all tests share the same value.
app.state.csrf_token = "test-token"


@pytest.fixture(autouse=True)
def _reset_csrf_token():
    """Restore the test CSRF token before every test.

    Tests that call ``ui.main()`` (e.g. TestBindGuard) overwrite app.state.csrf_token
    with a fresh random value. Without this fixture, any later test using
    _csrf_headers() would get 403.
    """
    app.state.csrf_token = "test-token"


client = TestClient(app)


def _csrf_headers():
    return {"X-Audio-DL-Token": "test-token"}


def _csrf_query():
    return "?token=test-token"


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
        "urls": [{"url": "https://youtu.be/dQw4w9WgXcQ", "format": "mp3"}],
        "output_dir": "/tmp/audio-dl-test",
        "playlist": False,
        "force": False,
        "fragments": 4,
    }
    body.update(overrides)
    return body


class TestPostJobsShapeV1_9:  # pylint: disable=invalid-name
    """v1.9 POST shape: per-URL format. Legacy shape returns 422."""

    def test_new_shape_accepts_per_url_format(self, tmp_path):
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [
            {"url": "https://youtu.be/AAA", "format": "m4a"},
            {"url": "https://youtu.be/BBB", "format": "mp4"},
        ]
        with patch("audio_dl_ui._run_one"):
            r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        job = JOBS[job_id]
        assert job.url_states["https://youtu.be/AAA"].media_format == "m4a"
        assert job.url_states["https://youtu.be/BBB"].media_format == "mp4"

    def test_legacy_shape_rejected(self):
        body = {
            "urls": "https://youtu.be/dQw4w9WgXcQ",  # old: string
            "format": "mp3",                          # old: top-level
            "output_dir": "/tmp/audio-dl-test",
        }
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 422  # Pydantic shape mismatch

    def test_empty_urls_list_returns_400(self):
        body = _valid_body()
        body["urls"] = []
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 400
        assert "url" in r.json()["detail"].lower()

    def test_unknown_format_in_urlspec_returns_400(self):
        body = _valid_body()
        body["urls"] = [{"url": "https://youtu.be/CCC", "format": "mp3x"}]
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "mp3x" in detail
        assert "https://youtu.be/CCC" in detail


class TestPostJobsBatchFormats:
    """End-to-end exercise of what the JS paste handler would POST."""

    def test_mixed_format_batch_accepted(self, tmp_path):
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [
            {"url": "https://yt.com/abc",  "format": "m4a"},
            {"url": "https://yt.com/abc2", "format": "mp3"},
            {"url": "https://yt.com/abc3", "format": "mp4"},
        ]
        with patch("audio_dl_ui._run_one"):
            r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 200
        job = JOBS[r.json()["job_id"]]
        assert job.url_states["https://yt.com/abc"].media_format  == "m4a"
        assert job.url_states["https://yt.com/abc2"].media_format == "mp3"
        assert job.url_states["https://yt.com/abc3"].media_format == "mp4"


class TestPostJobsValidation:
    def test_fragments_too_low_400(self):
        r = client.post("/jobs", json=_valid_body(fragments=0), headers=_csrf_headers())
        assert r.status_code == 400

    def test_fragments_too_high_400(self):
        r = client.post("/jobs", json=_valid_body(fragments=17), headers=_csrf_headers())
        assert r.status_code == 400

    def test_output_dir_unwritable_400(self):
        r = client.post("/jobs", json=_valid_body(output_dir="/dev/null/cant-make-this"),
                        headers=_csrf_headers())
        assert r.status_code == 400
        assert "writable" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /jobs — happy path (registers JobState)
# ---------------------------------------------------------------------------

class TestPostJobsHappyPath:
    def test_returns_job_id(self, tmp_path, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "download_media", lambda *a, **kw: [])
        body = _valid_body(output_dir=str(tmp_path))
        r = client.post("/jobs", json=body, headers=_csrf_headers())
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

        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [
            {"url": "https://youtu.be/AAA", "format": "mp3"},
            {"url": "https://youtu.be/BBB", "format": "mp3"},
        ]
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        job_id = r.json()["job_id"]
        job = JOBS[job_id]
        assert job.media_format == "mp3"
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
        from audio_dl_ui import JobState, UrlState
        url = "https://youtu.be/AAA"
        job = JobState(
            id="job-test",
            media_format="mp3",
            output_dir="/tmp",
            playlist=False,
            force=False,
            fragments=4,
            url_states={url: UrlState(url=url, media_format="mp3")},
        )
        return job, job.url_states[url]

    def _attach_subscriber(self, job):
        """Register a test subscriber so we can read emitted events.

        v1.3 broadcast architecture: events flow to per-subscriber queues
        rather than a single shared job.queue. Tests that want to assert
        emission behavior register their own subscriber queue.
        """
        import queue as _q
        sub = _q.Queue(maxsize=128)
        with job.lock:
            job.subscribers.append(sub)
        return sub

    def test_throttle_caps_event_rate(self, monkeypatch):
        from audio_dl_ui import _make_progress_hook
        import audio_dl_ui

        job, url_state = self._make_job()
        sub = self._attach_subscriber(job)
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
        emitted = [sub.get_nowait() for _ in range(sub.qsize())]
        assert 4 <= len(emitted) <= 6, f"got {len(emitted)} events"
        assert all(e["type"] == "progress" for e in emitted)

    def test_non_downloading_status_ignored(self):
        from audio_dl_ui import _make_progress_hook
        job, url_state = self._make_job()
        sub = self._attach_subscriber(job)
        hook = _make_progress_hook(job, url_state)
        # "finished" now emits a postprocessing progress event (not ignored)
        hook({"status": "finished", "downloaded_bytes": 1000, "total_bytes": 1000,
              "filename": "/tmp/x.m4a.part"})
        assert not sub.empty()
        ev = sub.get_nowait()
        assert ev["type"] == "progress"
        assert ev["phase"] == "postprocessing"
        # other statuses (e.g. "error") are still ignored
        hook({"status": "error"})
        assert sub.empty()

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
    # pylint: disable=too-many-locals
    def test_sse_event_sequence(self, tmp_path, monkeypatch):
        """
        Mock download_media to emit 2 fake progress events into the hook,
        then return a synthetic path. Open POST /jobs, then GET
        /jobs/{id}/events, and assert the event order over SSE.

        v1.3 broadcast: events emitted before the SSE subscriber registers
        are NOT buffered (the snapshot covers cumulative state instead).
        The test uses a gate to ensure the subscriber is registered before
        fake_download fires its events, so the assertion of full live event
        sequence is deterministic.
        """
        import audio_dl_ui as ui

        fake_path = str(tmp_path / "song.mp3")
        # Pre-create the file so the worker's path bookkeeping is realistic.
        (tmp_path / "song.mp3").write_bytes(b"x")

        # Gate the worker until the SSE subscriber has registered. Set by the
        # test after it reads the snapshot from the stream — at which point
        # _events_iter has appended to job.subscribers under job.lock.
        sse_ready = threading.Event()

        # sanitize_url is called BEFORE url_started is emitted by _run_one;
        # gating it (rather than download_media) blocks the worker before
        # ANY events fire, so the test's SSE subscriber catches all of them.
        original_sanitize = ui.sanitize_url
        def gated_sanitize(url):
            sse_ready.wait(timeout=5)
            return original_sanitize(url)
        monkeypatch.setattr(ui, "sanitize_url", gated_sanitize)

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

        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/AAA", "format": "mp3"}]
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        job_id = r.json()["job_id"]

        # Drain SSE stream synchronously; TestClient yields chunks.
        with client.stream("GET", f"/jobs/{job_id}/events{_csrf_query()}", timeout=10) as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if not line or line.startswith(": "):  # blank lines + keepalives
                    continue
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                    # Release the worker once we've seen the snapshot, so
                    # subsequent live events deterministically arrive.
                    if events[-1].get("type") == "job_snapshot":
                        sse_ready.set()
                if events and events[-1].get("type") == "job_completed":
                    break

        types = [e["type"] for e in events]
        # v1.3: every SSE connection gets a job_snapshot first so a reconnecting
        # browser can resync. job_started was dropped — snapshot conveys the
        # initial URL list. Live events follow.
        assert types[0] == "job_snapshot"
        assert events[0]["complete"] is False
        assert {u["url"] for u in events[0]["urls"]} == {"https://youtu.be/AAA"}
        assert "url_started" in types
        assert "url_completed" in types
        assert types[-1] == "job_completed"
        assert "job_started" not in types
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

# ---------------------------------------------------------------------------
# v1.3 SSE broadcast — multi-subscriber, late-connect replay, snapshot
# ---------------------------------------------------------------------------

class TestSseBroadcast:
    """The v1.3 fix for the deferred-from-v1.2.1 SSE single-consumer-queue bug.

    Each subscriber registers a per-connection queue; _emit fans events to all
    of them. Late subscribers get a snapshot + replay of the event log so a
    browser reconnect mid-job doesn't lose events or split them between the
    old (zombie) and new connections.
    """

    def _make_job(self):
        from audio_dl_ui import JobState, UrlState
        url = "https://youtu.be/AAA"
        job = JobState(
            id="bc", media_format="mp3", output_dir="/tmp",
            playlist=False, force=False, fragments=4,
            url_states={url: UrlState(url=url, media_format="mp3")},
        )
        return job

    def test_multiple_subscribers_each_get_all_events(self):
        import queue as _q
        from audio_dl_ui import _emit
        job = self._make_job()
        sub_a = _q.Queue(maxsize=128)
        sub_b = _q.Queue(maxsize=128)
        with job.lock:
            job.subscribers.append(sub_a)
            job.subscribers.append(sub_b)

        _emit(job, {"type": "url_started", "url": "https://youtu.be/AAA"})
        _emit(job, {"type": "progress", "url": "https://youtu.be/AAA", "percent": 50.0})
        _emit(job, {"type": "url_completed", "url": "https://youtu.be/AAA",
                    "paths": ["/tmp/song.mp3"]})

        def drain(q):
            events = []
            while not q.empty():
                events.append(q.get_nowait())
            return [e["type"] for e in events]

        # Both subscribers see the exact same event sequence.
        seq_a = drain(sub_a)
        seq_b = drain(sub_b)
        assert seq_a == ["url_started", "progress", "url_completed"]
        assert seq_a == seq_b

    def test_late_subscriber_after_completion_gets_snapshot_only(self, tmp_path, monkeypatch):
        """A subscriber connecting AFTER job_completed sees a snapshot with
        complete=True + a populated summary, and the stream then closes.
        No replay of historical events — the snapshot is everything the
        client needs to render the final state."""
        import audio_dl_ui as ui

        fake_path = str(tmp_path / "song.mp3")
        (tmp_path / "song.mp3").write_bytes(b"x")

        def fake_download(_url, *, progress_hooks=None, **_kw):
            assert progress_hooks
            progress_hooks[0]({"status": "downloading", "downloaded_bytes": 50,
                               "total_bytes": 100, "speed": 1024, "eta": 1,
                               "filename": fake_path})
            return [fake_path]

        monkeypatch.setattr(ui, "download_media", fake_download)
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/AAA", "format": "mp3"}]
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        job_id = r.json()["job_id"]

        # Wait for the job to actually complete before opening the SSE stream,
        # so we exercise the "subscriber connects after job is done" path.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if JOBS[job_id].completed:
                break
            time.sleep(0.02)
        assert JOBS[job_id].completed, "job did not complete in time"

        with client.stream("GET", f"/jobs/{job_id}/events{_csrf_query()}", timeout=5) as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if not line or line.startswith(": "):
                    continue
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                # No job_completed will arrive — stream closes after snapshot
                # when the job is already complete. Loop ends naturally.

        # Exactly one event: the snapshot with complete=True.
        assert len(events) == 1, f"got {len(events)} events: {[e['type'] for e in events]}"
        snap = events[0]
        assert snap["type"] == "job_snapshot"
        assert snap["complete"] is True
        assert snap["summary"]["completed"] == 1
        assert snap["summary"]["failed"] == 0
        assert snap["urls"][0]["status"] == "completed"
        assert snap["urls"][0]["paths"] == [fake_path]

    def test_subscriber_unregistered_on_disconnect(self):
        """Closing the SSE generator removes the subscriber so dead queues
        don't leak. Tested at the generator level (TestClient's streaming
        teardown is harder to drive deterministically from sync code, but
        the generator's finally block is the contract we care about)."""
        import asyncio
        from audio_dl_ui import _events_iter
        job = self._make_job()
        JOBS[job.id] = job
        try:
            async def open_and_close():
                gen = _events_iter(job.id)
                # Consume the snapshot to force subscriber registration.
                first = await gen.__anext__()
                assert "job_snapshot" in first
                assert len(job.subscribers) == 1, "snapshot should have registered a subscriber"
                # Close the generator — runs the finally block.
                await gen.aclose()
            asyncio.run(open_and_close())
            assert len(job.subscribers) == 0, (
                f"subscriber not unregistered after generator close: {len(job.subscribers)}"
            )
        finally:
            JOBS.pop(job.id, None)

    def test_emit_with_no_subscribers_is_a_noop(self):
        """Events emitted before any subscriber connects (worker race) are
        intentionally dropped on the floor — the snapshot a future subscriber
        receives covers their cumulative state, so there is no event log to
        replay and no buffer to grow."""
        from audio_dl_ui import _emit
        job = self._make_job()
        for i in range(50):
            _emit(job, {"type": "progress", "n": i})
        # No subscribers means no queues to put events into; nothing to assert
        # beyond "did not raise". The fact that the test reaches this line is
        # the assertion.
        assert not job.subscribers


class TestCancel:
    def test_unknown_job_404(self):
        r = client.post("/jobs/does-not-exist/cancel", headers=_csrf_headers())
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

        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/AAA", "format": "mp3"}]
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        job_id = r.json()["job_id"]

        # Wait for worker to start, then cancel.
        assert started.wait(timeout=2.0), "fake_download never started"
        r2 = client.post(f"/jobs/{job_id}/cancel", headers=_csrf_headers())
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
    def test_unknown_path_outside_roots_403(self, monkeypatch):
        """v1.8: paths outside the allow-listed roots are 403 (forbidden),
        not 400. JOBS is empty and no default_output_dir is set, so /etc/passwd
        can't be inside any allowed root."""
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, app as _app

        called = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda *a, **kw: called.append((a, kw)) or None,
        )
        original_default = getattr(_app.state, "default_output_dir", None)
        if hasattr(_app.state, "default_output_dir"):
            delattr(_app.state, "default_output_dir")
        JOBS.clear()
        try:
            r = client.post("/reveal", json={"path": "/etc/passwd"}, headers=_csrf_headers())
            # /etc/passwd usually exists → 403 (outside roots).
            # If it doesn't exist on a hardened container, 404 is also fine —
            # either way the subprocess must not fire.
            assert r.status_code in (403, 404)
            assert not called, "subprocess.run must not be invoked for unknown paths"
        finally:
            if original_default is not None:
                _app.state.default_output_dir = original_default

    def test_known_path_calls_open_dash_r(self, tmp_path, monkeypatch):
        """Register a path in a fake job, then reveal it."""
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, JobState, UrlState

        path = str(tmp_path / "song.mp3")
        (tmp_path / "song.mp3").write_bytes(b"x")

        job = JobState(
            id="manual", media_format="mp3", output_dir=str(tmp_path),
            playlist=False, force=False, fragments=4,
            url_states={
                "u": UrlState(
                    url="u", media_format="mp3", paths=[path], status="completed",
                ),
            },
        )
        JOBS["manual"] = job

        try:
            called = []
            monkeypatch.setattr(
                ui.subprocess, "run",
                lambda *a, **kw: called.append((a, kw)) or None,
            )
            r = client.post("/reveal", json={"path": path}, headers=_csrf_headers())
            assert r.status_code == 200
            assert r.json() == {"ok": True}
            # v1.8: path is resolved before being passed to open -R.
            assert called and called[0][0][0][:2] == ["open", "-R"]
            assert called[0][0][0][2] == str(Path(path).resolve())
        finally:
            del JOBS["manual"]


# ---------------------------------------------------------------------------
# GET /jobs/{id}/events — 404
# ---------------------------------------------------------------------------

class TestSseUnknownJob:
    def test_unknown_job_404(self):
        r = client.get(f"/jobs/does-not-exist/events{_csrf_query()}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------

class TestCsrfProtection:
    def _token(self):
        # Force a known token onto app.state so we can test against it.
        from audio_dl_ui import app  # pylint: disable=redefined-outer-name
        app.state.csrf_token = "test-token"
        return "test-token"

    def test_post_jobs_without_token_403(self, tmp_path):
        self._token()
        body = _valid_body(output_dir=str(tmp_path))
        r = client.post("/jobs", json=body)
        assert r.status_code == 403

    def test_post_jobs_with_valid_token_200(self, tmp_path, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "download_media", lambda *a, **kw: [])
        token = self._token()
        body = _valid_body(output_dir=str(tmp_path))
        r = client.post("/jobs", json=body, headers={"X-Audio-DL-Token": token})
        assert r.status_code == 200

    def test_post_jobs_with_invalid_token_403(self, tmp_path):
        self._token()
        body = _valid_body(output_dir=str(tmp_path))
        r = client.post("/jobs", json=body, headers={"X-Audio-DL-Token": "wrong"})
        assert r.status_code == 403

    def test_cancel_without_token_403(self):
        self._token()
        r = client.post("/jobs/doesnt-matter/cancel")
        assert r.status_code == 403

    def test_reveal_without_token_403(self):
        self._token()
        r = client.post("/reveal", json={"path": "/tmp/anything"})
        assert r.status_code == 403

    def test_events_without_token_403(self):
        self._token()
        r = client.get("/jobs/anything/events")
        assert r.status_code == 403

    def test_events_with_valid_token_query_200_or_404(self, tmp_path, monkeypatch):
        # 404 if job doesn't exist, 200 if it does — either passes the auth gate.
        # We just want to confirm 403 is NOT returned for a valid token.
        token = self._token()
        r = client.get(f"/jobs/unknown-job/events?token={token}")
        assert r.status_code in (200, 404), f"got {r.status_code}, expected 200 or 404"

    def test_events_with_invalid_token_query_403(self):
        self._token()
        r = client.get("/jobs/anything/events?token=wrong")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Bind guard (--allow-remote)
# ---------------------------------------------------------------------------

class TestBindGuard:
    def test_loopback_bind_allowed(self, monkeypatch):
        import audio_dl_ui as ui
        import sys
        # Stub the actual server start so main() doesn't block
        monkeypatch.setattr(ui, "uvicorn", type("X", (), {"run": lambda *a, **kw: None})())
        monkeypatch.setattr(ui, "_check_dependencies_gui", lambda: None)
        monkeypatch.setattr(sys, "argv", ["audio-dl-ui", "--host", "127.0.0.1", "--no-browser"])
        # Should NOT raise SystemExit
        ui.main()

    def test_nonloopback_bind_without_allow_remote_exits(self, monkeypatch):
        import audio_dl_ui as ui
        import sys
        import pytest
        monkeypatch.setattr(ui, "uvicorn", type("X", (), {"run": lambda *a, **kw: None})())
        monkeypatch.setattr(sys, "argv", ["audio-dl-ui", "--host", "0.0.0.0", "--no-browser"])
        with pytest.raises(SystemExit) as exc:
            ui.main()
        assert exc.value.code == 1

    def test_nonloopback_bind_with_allow_remote_allowed(self, monkeypatch):
        import audio_dl_ui as ui
        import sys
        monkeypatch.setattr(ui, "uvicorn", type("X", (), {"run": lambda *a, **kw: None})())
        monkeypatch.setattr(ui, "_check_dependencies_gui", lambda: None)
        monkeypatch.setattr(sys, "argv",
                            ["audio-dl-ui", "--host", "0.0.0.0", "--allow-remote", "--no-browser"])
        ui.main()  # should not raise


class TestMaxParallelValidation:
    """`--max-parallel` rejects non-positive / out-of-range values at argparse
    time, rather than crashing later inside ThreadPoolExecutor."""

    @pytest.mark.parametrize("bad", ["0", "-1", "65", "abc"])
    def test_rejects_invalid(self, monkeypatch, bad):
        import audio_dl_ui as ui
        import sys
        monkeypatch.setattr(ui, "uvicorn", type("X", (), {"run": lambda *a, **kw: None})())
        monkeypatch.setattr(sys, "argv",
                            ["audio-dl-ui", "--no-browser", "--max-parallel", bad])
        with pytest.raises(SystemExit) as exc:
            ui.main()
        assert exc.value.code == 2  # argparse uses exit code 2 for arg errors

    def test_accepts_valid(self, monkeypatch):
        import audio_dl_ui as ui
        import sys
        monkeypatch.setattr(ui, "uvicorn", type("X", (), {"run": lambda *a, **kw: None})())
        monkeypatch.setattr(ui, "_check_dependencies_gui", lambda: None)
        monkeypatch.setattr(sys, "argv",
                            ["audio-dl-ui", "--no-browser", "--max-parallel", "8"])
        ui.main()  # should not raise


# ---------------------------------------------------------------------------
# sanitize_url exception handling in _run_one
# ---------------------------------------------------------------------------

class TestRunOneSanitizeError:
    def test_sanitize_url_exception_surfaces_in_snapshot(self, tmp_path, monkeypatch):
        """If sanitize_url raises, _run_one emits url_failed → job_completed.
        v1.3 broadcast: the test connects SSE AFTER the job completes (the
        sanitize error is synchronous), so the snapshot is the source of truth
        for the failure surface. Assert the snapshot reflects status=failed +
        error text, and that summary.failed==1."""
        import audio_dl_ui as ui

        def boom(_url):
            raise ValueError("intentional sanitize_url failure")

        monkeypatch.setattr(ui, "sanitize_url", boom)
        # download_media shouldn't be reached (sanitize error fires first)
        monkeypatch.setattr(ui, "download_media", lambda *a, **kw: [])

        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [{"url": "https://youtu.be/AAA", "format": "mp3"}]
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 200, f"POST /jobs failed with {r.status_code}: {r.text}"
        job_id = r.json()["job_id"]

        # Wait for job to complete before opening SSE — sanitize error
        # propagates synchronously through the worker.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if JOBS[job_id].completed:
                break
            time.sleep(0.02)
        assert JOBS[job_id].completed, "job did not complete in time"

        with client.stream("GET", f"/jobs/{job_id}/events?token=test-token", timeout=5) as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if not line or line.startswith(": "):
                    continue
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                # No live events arrive — stream closes after the snapshot
                # because the job is already complete.

        # Single snapshot event with the failure surface fully described.
        assert len(events) == 1
        snap = events[0]
        assert snap["type"] == "job_snapshot"
        assert snap["complete"] is True
        assert snap["summary"]["failed"] == 1
        assert snap["urls"][0]["status"] == "failed"
        err = snap["urls"][0]["error"]
        assert err and ("intentional sanitize_url failure" in err or "sanitize" in err.lower())


class TestRunOnePerUrlFormat:
    def test_run_one_uses_url_state_format_not_job_default(self, tmp_path):
        """v1.9: _run_one reads url_state.media_format, not job.media_format."""
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [
            {"url": "https://youtu.be/AAA", "format": "m4a"},
            {"url": "https://youtu.be/BBB", "format": "mp4"},
        ]
        captured_formats = {}

        def fake_download(clean_url, *, media_format, **_kw):
            captured_formats[clean_url] = media_format
            return [str(tmp_path / f"{media_format}.{media_format}")]

        with patch("audio_dl_ui.download_media", side_effect=fake_download):
            r = client.post("/jobs", json=body, headers=_csrf_headers())
            assert r.status_code == 200
            job_id = r.json()["job_id"]
            # Wait for the supervisor to mark the job completed.
            # `JobState.completed` is set in `_supervise` after wait(futures);
            # the established pattern (see TestSseBroadcast line 434 and
            # TestRunOneSanitizeError line 768) is a 50x 0.05s poll = 2.5s
            # ceiling, which is plenty for two stub downloads.
            for _ in range(50):
                if JOBS[job_id].completed:
                    break
                time.sleep(0.05)
            assert JOBS[job_id].completed, "job did not complete in time"

        # captured_formats is keyed by clean (sanitized) URL — sanitize_url
        # normalizes youtu.be/X -> www.youtube.com/watch?v=X.
        assert captured_formats["https://www.youtube.com/watch?v=AAA"] == "m4a"
        assert captured_formats["https://www.youtube.com/watch?v=BBB"] == "mp4"


# ---------------------------------------------------------------------------
# /reveal dict-mutation race (Codex [P2])
# ---------------------------------------------------------------------------

class TestRevealSnapshotsJobs:
    """The /reveal handler must snapshot JOBS before iterating, otherwise a
    concurrent POST /jobs can mutate it mid-iteration and trigger
    RuntimeError: dictionary changed size during iteration. v1.8 moved the
    JOBS read into ``_reveal_allowed_roots`` which still iterates JOBS; the
    snapshot-list pattern keeps that read crash-safe."""

    def test_reveal_survives_concurrent_jobs_mutation(self, tmp_path, monkeypatch):
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, JobState

        # Use a dict subclass whose .values() mutates JOBS as a side-effect.
        # If _reveal_allowed_roots fails to snapshot JOBS.values() into a list
        # before iterating, the mutation triggers RuntimeError → 500.
        class _MutatingStates(dict):
            def values(self):  # type: ignore[override]
                JOBS[f"mid-iter-{len(JOBS)}"] = JOBS["racer"]
                return super().values()

        racer = JobState(
            id="racer", media_format="mp3", output_dir=str(tmp_path),
            playlist=False, force=False, fragments=4,
            url_states=_MutatingStates(),
        )

        JOBS.clear()
        JOBS["racer"] = racer

        called = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda *a, **kw: called.append((a, kw)) or None,
        )
        try:
            # The request itself must not 500. v1.8 status codes: 404 if the
            # path doesn't exist, 403 if outside allow-list, 200 if accepted.
            r = client.post("/reveal", json={"path": "/anything"}, headers=_csrf_headers())
            assert r.status_code != 500, f"got 500: {r.text}"
            assert r.status_code in (200, 403, 404)
        finally:
            JOBS.clear()


# ---------------------------------------------------------------------------
# Bounded SSE queue (Codex [P2])
# ---------------------------------------------------------------------------

class TestQueueBound:
    """Per-subscriber queues are bounded at 128 (v1.3 broadcast). Progress events
    drop on Full; terminal events still get through, with overflow eviction
    of the oldest event if necessary."""

    def _make_job_with_full_subscriber(self, maxsize=128):
        import queue as _q
        from audio_dl_ui import JobState, UrlState
        url = "https://youtu.be/AAA"
        job = JobState(
            id="qb", media_format="mp3", output_dir="/tmp",
            playlist=False, force=False, fragments=4,
            url_states={url: UrlState(url=url, media_format="mp3")},
        )
        sub = _q.Queue(maxsize=maxsize)
        with job.lock:
            job.subscribers.append(sub)
        # Pre-fill with progress events to saturate the queue.
        for i in range(maxsize):
            sub.put({"type": "progress", "n": i})
        assert sub.full()
        return job, sub

    def test_progress_events_dropped_when_full(self):
        from audio_dl_ui import _emit
        job, sub = self._make_job_with_full_subscriber()
        # Pushing more progress events must NOT block and must NOT raise.
        for _ in range(50):
            _emit(job, {"type": "progress", "extra": True})
        # Queue size is still capped.
        assert sub.qsize() == 128

    def test_terminal_events_get_through_when_full(self):
        from audio_dl_ui import _emit
        job, sub = self._make_job_with_full_subscriber()
        _emit(job, {"type": "job_completed", "job_id": "qb",
                    "summary": {"completed": 0, "failed": 1, "cancelled": 0}})
        # Drain everything and verify job_completed is present.
        events = []
        while not sub.empty():
            events.append(sub.get_nowait())
        types = [e["type"] for e in events]
        assert "job_completed" in types

    def test_post_jobs_initializes_empty_subscribers(self, tmp_path, monkeypatch):
        # v1.3: there's no single job.queue anymore. POST /jobs creates a
        # JobState with no subscribers — each SSE connection registers its own.
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "download_media", lambda *a, **kw: [])
        body = _valid_body(output_dir=str(tmp_path))
        r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        assert JOBS[job_id].subscribers == []


# ---------------------------------------------------------------------------
# P3 trio: HTML escape, btoa Unicode, 0.0.0.0 browser rewrite
# ---------------------------------------------------------------------------

class TestDefaultOutputDirEscaped:
    """default_output_dir is templated into an HTML attribute. Crafted
    values like '"><script>alert(1)</script>' must be escaped."""

    def test_html_escape(self):
        from audio_dl_ui import app as _app
        original = getattr(_app.state, "default_output_dir", None)
        try:
            _app.state.default_output_dir = '"><script>alert(1)</script>'
            r = client.get("/")
            assert r.status_code == 200
            body = r.text
            assert "<script>alert(1)</script>" not in body
            # html.escape with quote=True produces &lt;script&gt; and &quot;
            assert "&lt;script&gt;" in body or "&amp;lt;script&amp;gt;" in body
        finally:
            if original is None:
                if hasattr(_app.state, "default_output_dir"):
                    delattr(_app.state, "default_output_dir")
            else:
                _app.state.default_output_dir = original



class TestBrowserHostRewrite:
    """When --host is a bind-all address (0.0.0.0 or ::), the auto-opened
    browser URL must rewrite to 127.0.0.1 since 0.0.0.0 doesn't route in
    most browsers."""

    def test_zero_zero_zero_zero_rewrites(self, monkeypatch):
        import audio_dl_ui as ui
        import sys
        called = []

        def fake_timer(_delay, fn):
            class _T:
                def start(self):
                    fn()
            return _T()

        monkeypatch.setattr(ui.threading, "Timer", fake_timer)
        monkeypatch.setattr(ui, "webbrowser",
                            type("X", (), {"open": lambda self, url: called.append(url)})())
        monkeypatch.setattr(ui, "uvicorn",
                            type("X", (), {"run": lambda *a, **kw: None})())
        monkeypatch.setattr(ui, "_check_dependencies_gui", lambda: None)
        monkeypatch.setattr(
            sys, "argv",
            ["audio-dl-ui", "--host", "0.0.0.0", "--allow-remote", "--port", "8765"],
        )
        ui.main()
        assert called == ["http://127.0.0.1:8765"], called

    def test_loopback_passes_through(self, monkeypatch):
        import audio_dl_ui as ui
        import sys
        called = []

        def fake_timer(_delay, fn):
            class _T:
                def start(self):
                    fn()
            return _T()

        monkeypatch.setattr(ui.threading, "Timer", fake_timer)
        monkeypatch.setattr(ui, "webbrowser",
                            type("X", (), {"open": lambda self, url: called.append(url)})())
        monkeypatch.setattr(ui, "uvicorn",
                            type("X", (), {"run": lambda *a, **kw: None})())
        monkeypatch.setattr(ui, "_check_dependencies_gui", lambda: None)
        monkeypatch.setattr(sys, "argv",
                            ["audio-dl-ui", "--host", "127.0.0.1", "--port", "9000"])
        ui.main()
        assert called == ["http://127.0.0.1:9000"], called


# ---------------------------------------------------------------------------
# _check_dependencies_gui — GUI-aware dependency pre-flight
# ---------------------------------------------------------------------------

class TestCheckDependenciesGui:
    def test_returns_silently_when_all_present(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "_check_dependencies", lambda: [])
        # Should not raise, should not exit.
        ui._check_dependencies_gui()

    def test_no_tty_on_darwin_shows_dialog(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "_check_dependencies",
                            lambda: ["ffmpeg is not installed or not on PATH.",
                                     "  macOS:   brew install ffmpeg"])
        monkeypatch.setattr(ui.sys, "platform", "darwin")

        # Force no-TTY.
        class _FakeStderr:
            def isatty(self):
                return False
            def write(self, _s):
                pass
            def flush(self):
                pass
        monkeypatch.setattr(ui.sys, "stderr", _FakeStderr())

        captured = {}
        def fake_dialog(title, message):
            captured["title"] = title
            captured["message"] = message
            return True
        monkeypatch.setattr(ui, "_show_macos_dialog", fake_dialog)

        with pytest.raises(SystemExit) as excinfo:
            ui._check_dependencies_gui()
        assert excinfo.value.code == 1
        assert "audio-dl" in captured["title"]
        assert "ffmpeg" in captured["message"]
        assert "brew install ffmpeg" in captured["message"]

    def test_tty_attached_prints_to_stderr(self, monkeypatch):
        import io
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "_check_dependencies",
                            lambda: ["ffmpeg is not installed or not on PATH.",
                                     "  macOS:   brew install ffmpeg"])

        class _FakeStderr(io.StringIO):
            def isatty(self):
                return True

        fake_stderr = _FakeStderr()
        monkeypatch.setattr(ui.sys, "stderr", fake_stderr)

        # Dialog must NOT fire on TTY-attached runs.
        def boom(_t, _m):
            raise AssertionError("dialog should not be shown when stderr is a TTY")
        monkeypatch.setattr(ui, "_show_macos_dialog", boom)

        with pytest.raises(SystemExit) as excinfo:
            ui._check_dependencies_gui()
        assert excinfo.value.code == 1
        out = fake_stderr.getvalue()
        assert "ERROR: ffmpeg" in out
        assert "  macOS:   brew install ffmpeg" in out

    def test_no_tty_darwin_dialog_failed_falls_through_to_stderr(self, monkeypatch):
        # If osascript is unavailable / rejected the script, _show_macos_dialog
        # returns False. We must still write the problem to stderr so a system
        # log captures the cause — not exit silently.
        import io
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "_check_dependencies",
                            lambda: ["ffmpeg is not installed or not on PATH."])
        monkeypatch.setattr(ui.sys, "platform", "darwin")

        class _FakeStderr(io.StringIO):
            def isatty(self):
                return False

        fake_stderr = _FakeStderr()
        monkeypatch.setattr(ui.sys, "stderr", fake_stderr)
        monkeypatch.setattr(ui, "_show_macos_dialog", lambda _t, _m: False)

        with pytest.raises(SystemExit) as excinfo:
            ui._check_dependencies_gui()
        assert excinfo.value.code == 1
        assert "ERROR: ffmpeg" in fake_stderr.getvalue()

    def test_non_darwin_falls_back_to_stderr(self, monkeypatch):
        import io
        import audio_dl_ui as ui
        monkeypatch.setattr(ui, "_check_dependencies",
                            lambda: ["yt-dlp is not installed."])
        monkeypatch.setattr(ui.sys, "platform", "linux")

        class _FakeStderr(io.StringIO):
            def isatty(self):
                return False

        monkeypatch.setattr(ui.sys, "stderr", _FakeStderr())

        def boom(_t, _m):
            raise AssertionError("dialog should not be shown off macOS")
        monkeypatch.setattr(ui, "_show_macos_dialog", boom)

        with pytest.raises(SystemExit):
            ui._check_dependencies_gui()


class TestShowMacosDialog:
    def test_returns_false_off_darwin(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui.sys, "platform", "linux")
        assert ui._show_macos_dialog("t", "m") is False

    def test_calls_osascript_on_darwin(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui.sys, "platform", "darwin")
        calls = []

        class _FakeRun:
            returncode = 0

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _FakeRun()

        monkeypatch.setattr(ui.subprocess, "run", fake_run)
        assert ui._show_macos_dialog("Title", "Body") is True
        assert calls and calls[0][0] == "osascript"
        # Title and body must appear in the AppleScript payload.
        joined = " ".join(calls[0][1:])
        assert "Title" in joined
        assert "Body" in joined

    def test_escapes_quotes_and_backslashes(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui.sys, "platform", "darwin")
        calls = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0})(),
        )
        ui._show_macos_dialog('a"b\\c', 'x"y\\z')
        script = calls[0][-1]
        # AppleScript string literals: " → \", \ → \\.
        assert 'a\\"b\\\\c' in script
        assert 'x\\"y\\\\z' in script

    def test_returns_false_when_osascript_missing(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui.sys, "platform", "darwin")
        def raise_fnf(*_a, **_k):
            raise FileNotFoundError("no osascript")
        monkeypatch.setattr(ui.subprocess, "run", raise_fnf)
        assert ui._show_macos_dialog("t", "m") is False

    def test_returns_false_on_nonzero_returncode(self, monkeypatch):
        # codex review-1 REQUIRED #2: osascript rejecting the AppleScript
        # source (syntax error, unknown keyword) exits non-zero. Without this
        # check, _check_dependencies_gui would silently exit before reaching
        # the stderr fallthrough path.
        import audio_dl_ui as ui
        monkeypatch.setattr(ui.sys, "platform", "darwin")
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda cmd, **kw: type("R", (), {"returncode": 1})(),
        )
        assert ui._show_macos_dialog("t", "m") is False

    def test_timeout_returns_false(self, monkeypatch):
        import audio_dl_ui as ui
        monkeypatch.setattr(ui.sys, "platform", "darwin")
        def raise_timeout(*_a, **_k):
            raise ui.subprocess.TimeoutExpired(cmd="osascript", timeout=60)
        monkeypatch.setattr(ui.subprocess, "run", raise_timeout)
        assert ui._show_macos_dialog("t", "m") is False


# ---------------------------------------------------------------------------
# v1.5 theme system — CSS cascade + JS registry tests
# ---------------------------------------------------------------------------

class TestThemeRendering:
    """Theme cascade is 10 :root[data-theme="<slug>"] blocks. The JS THEMES
    registry must enumerate the same 10 slugs in the same order. Drift between
    the two would silently break the picker."""

    EXPECTED_SLUGS = [
        "phosphor", "rose", "moon", "dawn", "amber",
        "solarized", "gruvbox", "tokyo", "atom", "claude",
    ]

    def test_all_ten_theme_blocks_present(self):
        """_INDEX_CSS_THEMES contains :root[data-theme="<slug>"] selectors for all
        10 themes, in the same order as the JS THEMES registry. Each slug may appear
        multiple times (once for the var block, additional times for scoped descendant
        override rules) — we check the first-occurrence order only."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        found = re.findall(r':root\[data-theme="([^"]+)"\]', _INDEX_CSS_THEMES)
        # Deduplicate while preserving first-occurrence order (dict insertion order).
        unique_ordered = list(dict.fromkeys(found))
        assert unique_ordered == self.EXPECTED_SLUGS, (
            f"Expected {self.EXPECTED_SLUGS}, found unique-ordered {unique_ordered}"
        )

    def test_js_themes_registry_matches_css_slugs(self):
        """JS THEMES array's slugs appear in the same order as the CSS blocks."""
        from audio_dl_ui import _INDEX_JS
        slugs = re.findall(r"slug:\s*'([^']+)'", _INDEX_JS)
        assert slugs == self.EXPECTED_SLUGS, (
            f"JS slugs {slugs} drift from CSS slugs {self.EXPECTED_SLUGS}"
        )

    def test_js_default_theme_is_phosphor(self):
        """Exactly one theme entry has default: true, and it's phosphor."""
        from audio_dl_ui import _INDEX_JS
        # Match a registry entry where default: true follows the slug.
        # Allow any chars except 'slug:' between slug and default within the entry.
        defaults = re.findall(
            r"slug:\s*'([^']+)'[^}]*default:\s*true",
            _INDEX_JS,
        )
        assert defaults == ['phosphor'], (
            f"Expected exactly ['phosphor'] as default, got {defaults}"
        )


# ---------------------------------------------------------------------------
# Per-theme card structural variations (v1.7)
# ---------------------------------------------------------------------------

class TestCardClusterOverrides:
    """v1.7 extends the v1.6 per-theme override pattern to .card selectors.
    Cluster CSS lives at the tail of _INDEX_CSS_THEMES as grouped selectors
    per cluster. Phosphor stays byte-identical to v1.6 (no .card override)."""

    def test_phosphor_has_no_card_override(self):
        """Phosphor cards stay byte-identical to v1.6 — there is no
        `[data-theme="phosphor"] .card` rule anywhere."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        assert re.search(
            r'\[data-theme="phosphor"\]\s*\.card', _INDEX_CSS_THEMES
        ) is None, "Phosphor must remain the v1.6 reference (no .card override)"

    def test_vintage_cluster_card_block_present(self):
        """Vintage cluster (amber/solarized/gruvbox) has a grouped .card
        selector — exactly three themes grouped together."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        pattern = (
            r'\[data-theme="amber"\]\s*\.card,\s*'
            r'\[data-theme="solarized"\]\s*\.card,\s*'
            r'\[data-theme="gruvbox"\]\s*\.card'
        )
        assert re.search(pattern, _INDEX_CSS_THEMES) is not None, (
            "Vintage cluster grouped .card selector missing"
        )

    def test_editorial_cluster_card_block_present(self):
        """Editorial cluster (rose/moon/dawn) has a grouped .card selector."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        pattern = (
            r'\[data-theme="rose"\]\s*\.card,\s*'
            r'\[data-theme="moon"\]\s*\.card,\s*'
            r'\[data-theme="dawn"\]\s*\.card'
        )
        assert re.search(pattern, _INDEX_CSS_THEMES) is not None, (
            "Editorial cluster grouped .card selector missing"
        )

    def test_dawn_card_thumb_hidden(self):
        """Dawn (editorial light) hides .card-thumb entirely."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        pattern = (
            r'\[data-theme="dawn"\]\s*\.card-thumb\s*\{[^}]*display:\s*none'
        )
        assert re.search(pattern, _INDEX_CSS_THEMES) is not None, (
            "Dawn must hide .card-thumb (display: none)"
        )

    def test_dawn_card_grid_collapses_to_single_column(self):
        """When the thumb is hidden, the card grid must collapse to 1fr
        to avoid a phantom thumbnail column."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        pattern = (
            r'\[data-theme="dawn"\]\s*\.card\s*\{[^}]*grid-template-columns:\s*1fr'
        )
        assert re.search(pattern, _INDEX_CSS_THEMES) is not None, (
            "Dawn .card must override grid-template-columns to 1fr"
        )

    def test_modern_cluster_card_block_present(self):
        """Modern cluster (tokyo/atom/claude) has a grouped .card selector."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        pattern = (
            r'\[data-theme="tokyo"\]\s*\.card,\s*'
            r'\[data-theme="atom"\]\s*\.card,\s*'
            r'\[data-theme="claude"\]\s*\.card'
        )
        assert re.search(pattern, _INDEX_CSS_THEMES) is not None, (
            "Modern cluster grouped .card selector missing"
        )

    def test_modern_cluster_has_duration_overlay(self):
        """Modern cluster renders duration via .card-thumb::after with
        attr(data-duration). Look for the ::after rule on at least one of
        the three modern themes — the spec uses a grouped selector covering
        all three, but a per-theme split is also acceptable."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        pattern = r'\[data-theme="(?:tokyo|atom|claude)"\]\s*\.card-thumb::after'
        matches = re.findall(pattern, _INDEX_CSS_THEMES)
        assert len(matches) >= 3, (
            f"Expected modern cluster .card-thumb::after on tokyo, atom, claude — "
            f"found {len(matches)} match(es): {matches}"
        )
        # Verify attr(data-duration) is the content
        assert re.search(
            r'\.card-thumb::after[^}]*content:\s*attr\(data-duration\)',
            _INDEX_CSS_THEMES,
        ) is not None, "::after rule should use content: attr(data-duration)"

    def test_modern_cluster_meta_above_title_via_grid(self):
        """Modern cluster lifts .card-meta above .card-title by switching
        .card-head from flex to CSS grid and placing meta on row 1, title
        on row 2. An earlier attempt used `order: -1` on .card-meta alone;
        that does NOT work because the base .card-head is a single-row
        display:flex container — `order` only reshuffles inline, it does
        not promote a child to its own row. Grid placement does. (P2
        codex review finding on PR #19.)"""
        from audio_dl_ui import _INDEX_CSS_THEMES
        # .card-head switches to display: grid for all 3 modern themes
        assert re.search(
            r'\[data-theme="tokyo"\]\s*\.card-head,\s*'
            r'\[data-theme="atom"\]\s*\.card-head,\s*'
            r'\[data-theme="claude"\]\s*\.card-head\s*\{[^}]*display:\s*grid',
            _INDEX_CSS_THEMES,
        ) is not None, "Modern cluster .card-head must use display: grid"
        # .card-meta placed on grid-row: 1 (top)
        assert re.search(
            r'\[data-theme="tokyo"\]\s*\.card-meta,\s*'
            r'\[data-theme="atom"\]\s*\.card-meta,\s*'
            r'\[data-theme="claude"\]\s*\.card-meta\s*\{[^}]*grid-row:\s*1',
            _INDEX_CSS_THEMES,
        ) is not None, "Modern cluster .card-meta must be placed on grid-row: 1"
        # .card-title placed on grid-row: 2 (below meta)
        assert re.search(
            r'\[data-theme="tokyo"\]\s*\.card-title,\s*'
            r'\[data-theme="atom"\]\s*\.card-title,\s*'
            r'\[data-theme="claude"\]\s*\.card-title\s*\{[^}]*grid-row:\s*2',
            _INDEX_CSS_THEMES,
        ) is not None, "Modern cluster .card-title must be placed on grid-row: 2"

    def test_render_card_sets_data_duration_attribute(self):
        """renderCard must set data-duration on .card-thumb so the modern
        cluster's ::after overlay can read it via attr(). Accept either
        single- or double-quoted attribute name."""
        from audio_dl_ui import _INDEX_JS
        assert (
            "setAttribute('data-duration'" in _INDEX_JS
            or 'setAttribute("data-duration"' in _INDEX_JS
        ), "renderCard must call setAttribute('data-duration', ...) on .card-thumb"

    def test_cluster_css_does_not_touch_state_managed_display(self):
        """Cluster CSS must not assign `display:` on .card-progress or
        .card-log children — those rules are owned by base state CSS:
            .card[data-state="queued"] .card-progress { display: none; }
            .card[data-state="resolving"] .card-log    { display: none; }
        Overriding at the cluster level would break the show/hide invariant
        for the queued/resolving lifecycle phases."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        forbidden = re.findall(
            r'\[data-theme="[^"]+"\]\s*\.card-(?:progress|log|log-line)\s*'
            r'\{[^}]*display\s*:',
            _INDEX_CSS_THEMES,
        )
        assert not forbidden, (
            "Cluster CSS must not set `display` on state-managed card children. "
            f"Offending rules: {forbidden}"
        )

    def test_cluster_css_does_not_override_badge_state_colors(self):
        """Cluster CSS must not assign `color:` on .card-badge — those rules
        are owned by base state CSS for the complete (--ok) and failed
        (--err) states. Override at the cluster level would silently break
        success/failure signaling."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        forbidden = re.findall(
            r'\[data-theme="[^"]+"\]\s*\.card-badge\s*\{[^}]*color\s*:',
            _INDEX_CSS_THEMES,
        )
        assert not forbidden, (
            "Cluster CSS must not set `color` on .card-badge. "
            f"Offending rules: {forbidden}"
        )

    def test_cluster_css_does_not_override_badge_animation(self):
        """Cluster CSS must not assign animation properties on .card-badge or
        .card-badge::after — the resolving phase pulse animation is owned by
        base CSS. Override at the cluster level would silently disable or
        replace the active-card pulse."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        forbidden = re.findall(
            r'\[data-theme="[^"]+"\]\s*\.card-badge(?:::after)?\s*'
            r'\{[^}]*animation(?:-name|-duration|-timing-function|-delay'
            r'|-iteration-count|-direction|-fill-mode|-play-state)?\s*:',
            _INDEX_CSS_THEMES,
        )
        assert not forbidden, (
            "Cluster CSS must not set animation on .card-badge / ::after. "
            f"Offending rules: {forbidden}"
        )


# ---------------------------------------------------------------------------
# _should_keep_log — pure filter for yt-dlp log lines
# ---------------------------------------------------------------------------

class TestShouldKeepLog:
    @pytest.mark.parametrize("level,text,expected", [
        # Always keep warning + error
        ("warning", "anything at all", True),
        ("warning", "", True),
        ("error", "boom", True),

        # Drop all debug regardless of text
        ("debug", "[debug] anything", False),
        ("debug", "[hls] downloading fragment 1/2", False),

        # info: keep the phase markers
        ("info", "[hls] downloading fragment 12/45", True),
        ("info", "[ffmpeg] Merging into mp4", True),
        ("info", "[ffmpeg] Adding metadata", True),
        ("info", "[ExtractAudio] Destination: foo.m4a", True),
        ("info", "[EmbedThumbnail] adding thumbnail to foo.m4a", True),
        ("info", "[Metadata] Embedding metadata", True),

        # info: drop chatter
        ("info", "[download] Destination: foo.m4a.part", False),
        ("info", "[info] Writing video thumbnail", False),
        ("info", "[youtube] Extracting URL: https://...", False),
        ("info", "Plain text with no tag", False),
        ("info", "", False),

        # Unknown / novel levels behave like info (prefix-gated)
        ("verbose", "[ffmpeg] Merging", True),
        ("verbose", "[youtube] chatter", False),
    ])
    def test_filter(self, level, text, expected):
        assert _should_keep_log(level, text) is expected


class TestPickThumbnailUrl:
    def test_prefers_width_le_480_among_options(self):
        info = {"thumbnails": [
            {"url": "huge.jpg", "width": 1920},
            {"url": "medium.jpg", "width": 480},
            {"url": "small.jpg", "width": 120},
        ]}
        # Largest width that is still <= 480
        assert _pick_thumbnail_url(info) == "medium.jpg"

    def test_falls_back_to_smallest_when_none_le_480(self):
        info = {"thumbnails": [
            {"url": "huge.jpg", "width": 1920},
            {"url": "large.jpg", "width": 1080},
            {"url": "still-large.jpg", "width": 720},
        ]}
        # Smallest available
        assert _pick_thumbnail_url(info) == "still-large.jpg"

    def test_handles_missing_width(self):
        # Some extractors omit width; those should not crash and should
        # fall through to the unsized fallback.
        info = {"thumbnails": [
            {"url": "unknown.jpg"},
            {"url": "sized.jpg", "width": 320},
        ]}
        assert _pick_thumbnail_url(info) == "sized.jpg"

    def test_only_unsized_returns_first(self):
        info = {"thumbnails": [
            {"url": "a.jpg"},
            {"url": "b.jpg"},
        ]}
        assert _pick_thumbnail_url(info) == "a.jpg"

    def test_falls_back_to_singular_thumbnail_field(self):
        info = {"thumbnail": "single.jpg"}
        assert _pick_thumbnail_url(info) == "single.jpg"

    def test_returns_none_when_no_thumbnails(self):
        assert _pick_thumbnail_url({}) is None
        assert _pick_thumbnail_url({"thumbnails": []}) is None
        assert _pick_thumbnail_url({"thumbnail": None}) is None


class TestUrlStateNewFields:
    def test_defaults(self):
        s = UrlState(url="https://example/x", media_format="mp3")
        assert s.title is None
        assert s.uploader is None
        assert s.duration is None
        assert s.thumbnail_ready is False
        assert s.phase is None
        assert isinstance(s.log, collections.deque)
        assert s.log.maxlen == 50
        assert len(s.log) == 0

    def test_log_independence_across_instances(self):
        # Regression guard: mutable default would share one deque across
        # all UrlState instances. Use field(default_factory=...).
        a = UrlState(url="https://example/a", media_format="mp3")
        b = UrlState(url="https://example/b", media_format="mp3")
        a.log.append({"ts": 1.0, "level": "info", "text": "hello"})
        assert len(b.log) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_job(url: str = "https://example/x") -> JobState:
    job = JobState(
        id="j1", media_format="mp3", output_dir="/tmp",
        playlist=False, force=False, fragments=4,
        url_states={url: UrlState(url=url, media_format="mp3")},
    )
    return job


# ---------------------------------------------------------------------------
# _YDLLogger / _make_url_logger
# ---------------------------------------------------------------------------

class TestYDLLogger:
    def test_keeps_phase_lines_at_info(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        logger = _make_url_logger(job, urlst)

        logger.info("[hls] downloading fragment 5/10")

        ev = q.get_nowait()
        assert ev["type"] == "url_log"
        assert ev["level"] == "info"
        assert ev["text"] == "[hls] downloading fragment 5/10"
        assert ev["url"] == urlst.url
        assert "ts" in ev
        # also appended to the URL's bounded log deque
        assert len(urlst.log) == 1
        assert urlst.log[0]["text"] == "[hls] downloading fragment 5/10"

    def test_drops_filtered_info(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        logger = _make_url_logger(job, urlst)

        logger.info("[download] Destination: foo.m4a.part")

        assert q.empty()
        assert len(urlst.log) == 0

    def test_drops_all_debug(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        logger = _make_url_logger(job, urlst)

        logger.debug("[hls] downloading fragment 1/1")  # would pass info filter

        assert q.empty()
        assert len(urlst.log) == 0

    def test_always_keeps_warning_and_error(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        logger = _make_url_logger(job, urlst)

        logger.warning("Slow connection detected")
        logger.error("HTTP 403")

        ev1 = q.get_nowait()
        ev2 = q.get_nowait()
        assert (ev1["level"], ev2["level"]) == ("warning", "error")
        assert len(urlst.log) == 2

    def test_coerces_non_string(self):
        # yt-dlp sometimes passes objects (Exceptions). Must not crash.
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        logger = _make_url_logger(job, urlst)
        logger.error(RuntimeError("boom"))
        assert urlst.log[-1]["text"] == "boom"

    def test_deque_bounded_at_50(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        logger = _make_url_logger(job, urlst)
        for i in range(75):
            logger.warning(f"line {i}")
        assert len(urlst.log) == 50
        # Oldest is dropped
        assert urlst.log[0]["text"] == "line 25"
        assert urlst.log[-1]["text"] == "line 74"


class TestRunOneWiresLogger:
    def test_logger_passed_to_download_media(self):
        from audio_dl_ui import _run_one, JOBS

        job = _fresh_job()
        JOBS[job.id] = job
        try:
            captured = {}

            def fake_download(url, **kwargs):
                captured["logger"] = kwargs.get("logger")
                return ["/tmp/out.mp3"]

            with patch("audio_dl_ui.download_media", side_effect=fake_download), \
                 patch("audio_dl_ui.sanitize_url", side_effect=lambda u: u):
                _run_one(job, list(job.url_states.keys())[0])

            assert captured["logger"] is not None
            assert hasattr(captured["logger"], "warning")
            assert hasattr(captured["logger"], "error")
        finally:
            JOBS.pop(job.id, None)


# ---------------------------------------------------------------------------
# _make_progress_hook — url_metadata SSE event
# ---------------------------------------------------------------------------

class TestUrlMetadataEvent:
    def test_first_info_dict_emits_metadata_event(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        from audio_dl_ui import _make_progress_hook
        hook = _make_progress_hook(job, urlst)

        info = {
            "title": "Wandered into the Day",
            "uploader": "Geotic",
            "duration": 251,
            "thumbnails": [{"url": "x.jpg", "width": 320}],
            "thumbnail": "x.jpg",
        }
        # First hook tick with status=downloading and info_dict present
        hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000,
              "info_dict": info})

        # Drain queue; expect url_metadata event among emissions
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        meta = [e for e in events if e["type"] == "url_metadata"]
        assert len(meta) == 1
        assert meta[0]["title"] == "Wandered into the Day"
        assert meta[0]["uploader"] == "Geotic"
        assert meta[0]["duration"] == 251
        assert meta[0]["thumbnail_ready"] is False
        assert meta[0]["url"] == urlst.url
        # UrlState is populated
        assert urlst.title == "Wandered into the Day"
        assert urlst.metadata_emitted is True

    def test_subsequent_ticks_dont_re_emit_metadata(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        from audio_dl_ui import _make_progress_hook
        hook = _make_progress_hook(job, urlst)

        info = {"title": "T", "uploader": "U", "duration": 1}
        # Two ticks > throttle window apart
        hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000,
              "info_dict": info})
        time.sleep(0.25)
        hook({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000,
              "info_dict": info})

        meta = [
            e for e in (q.get_nowait() for _ in range(q.qsize()))
            if e["type"] == "url_metadata"
        ]
        assert len(meta) == 1

    def test_missing_title_uses_none(self):
        # Real yt-dlp always sends a populated info_dict — but it may lack
        # title/uploader/duration for some sites. Use a minimally-populated
        # info_dict so the (truthy) check fires.
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        from audio_dl_ui import _make_progress_hook
        hook = _make_progress_hook(job, urlst)

        hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000,
              "info_dict": {"extractor": "youtube"}})

        meta = [
            e for e in (q.get_nowait() for _ in range(q.qsize()))
            if e["type"] == "url_metadata"
        ]
        assert len(meta) == 1
        assert meta[0]["title"] is None
        assert meta[0]["uploader"] is None
        assert meta[0]["duration"] is None


# ---------------------------------------------------------------------------
# _make_progress_hook — phase field on progress events (Task 8)
# ---------------------------------------------------------------------------

class TestRunOnePhaseTransitions:
    def test_phases_resolving_then_complete(self):
        from audio_dl_ui import _run_one, JOBS
        job = _fresh_job()
        JOBS[job.id] = job
        urlst = list(job.url_states.values())[0]
        try:
            with patch("audio_dl_ui.download_media", return_value=["/tmp/x.mp3"]), \
                 patch("audio_dl_ui.sanitize_url", side_effect=lambda u: u):
                _run_one(job, urlst.url)
            assert urlst.phase == "complete"

        finally:
            JOBS.pop(job.id, None)

    def test_phase_failed_on_error(self):
        from audio_dl_ui import _run_one, JOBS
        job = _fresh_job()
        JOBS[job.id] = job
        urlst = list(job.url_states.values())[0]
        try:
            with patch("audio_dl_ui.download_media", side_effect=RuntimeError("bad")), \
                 patch("audio_dl_ui.sanitize_url", side_effect=lambda u: u):
                _run_one(job, urlst.url)
            assert urlst.phase == "failed"
        finally:
            JOBS.pop(job.id, None)

    def test_resolving_set_before_sanitize(self):
        # When sanitize raises, phase is still "resolving" then transitions
        # to "failed". Easier to assert: resolving is set as the first phase.
        from audio_dl_ui import _run_one, JOBS
        job = _fresh_job()
        JOBS[job.id] = job
        urlst = list(job.url_states.values())[0]
        captured = {"phase_at_sanitize": None}

        def fake_sanitize(u):
            captured["phase_at_sanitize"] = urlst.phase
            return u

        try:
            with patch("audio_dl_ui.download_media", return_value=["/tmp/x.mp3"]), \
                 patch("audio_dl_ui.sanitize_url", side_effect=fake_sanitize):
                _run_one(job, urlst.url)
            assert captured["phase_at_sanitize"] == "resolving"
        finally:
            JOBS.pop(job.id, None)


class TestPhaseField:
    def test_downloading_tick_carries_phase(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        from audio_dl_ui import _make_progress_hook
        hook = _make_progress_hook(job, urlst)

        hook({"status": "downloading", "downloaded_bytes": 100, "total_bytes": 1000})

        events = [q.get_nowait() for _ in range(q.qsize())]
        progress = [e for e in events if e["type"] == "progress"]
        assert progress and progress[-1]["phase"] == "downloading"
        assert urlst.phase == "downloading"

    def test_finished_tick_moves_to_postprocessing(self):
        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        from audio_dl_ui import _make_progress_hook
        hook = _make_progress_hook(job, urlst)

        hook({"status": "finished", "downloaded_bytes": 1000, "total_bytes": 1000,
              "filename": "/tmp/x.m4a.part"})

        events = [q.get_nowait() for _ in range(q.qsize())]
        progress = [e for e in events if e["type"] == "progress"]
        assert progress and progress[-1]["phase"] == "postprocessing"
        assert urlst.phase == "postprocessing"


def _mock_httpx_stream(status_code=200, content=b"x" * 100):
    """Return a context-manager mock matching httpx.stream's interface."""
    resp = MagicMock(status_code=status_code)
    resp.iter_bytes = lambda: iter([content])
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=resp)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestThumbnailFetcher:
    def test_writes_file_on_success(self, tmp_path, monkeypatch):
        from audio_dl_ui import _fetch_thumbnail, _thumb_dir
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        with patch("audio_dl_ui.httpx.stream",
                   return_value=_mock_httpx_stream(content=b"\xff\xd8\xff\xe0fakejpeg")):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is True
        expected = os.path.join(_thumb_dir("job1"), "0.jpg")
        assert os.path.exists(expected)
        with open(expected, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0fakejpeg"

    def test_non_200_returns_false(self, tmp_path, monkeypatch):
        from audio_dl_ui import _fetch_thumbnail
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        with patch("audio_dl_ui.httpx.stream",
                   return_value=_mock_httpx_stream(status_code=404)):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is False

    def test_exception_returns_false(self, tmp_path, monkeypatch):
        from audio_dl_ui import _fetch_thumbnail
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        with patch("audio_dl_ui.httpx.stream", side_effect=Exception("boom")):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is False

    def test_atomic_write(self, tmp_path, monkeypatch):
        """Failure mid-write must not leave a partial file at the target path."""
        from audio_dl_ui import _fetch_thumbnail, _thumb_dir
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        with patch("audio_dl_ui.httpx.stream",
                   return_value=_mock_httpx_stream(content=b"x" * 100)), \
             patch("audio_dl_ui.os.replace", side_effect=OSError("disk full")):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is False
        assert not os.path.exists(os.path.join(_thumb_dir("job1"), "0.jpg"))

    def test_size_cap_returns_false_and_no_partial_file(self, tmp_path, monkeypatch):
        """A hostile/huge response is aborted; no partial file remains."""
        from audio_dl_ui import _fetch_thumbnail, _thumb_dir, _THUMB_MAX_BYTES
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        # Mock httpx.stream to emit chunks totaling more than the cap
        class FakeStreamResp:
            status_code = 200
            def iter_bytes(self):
                # Emit 6MB in 1MB chunks — exceeds the 5MB cap
                chunk = b"x" * (1024 * 1024)
                for _ in range(6):
                    yield chunk

        class FakeStreamCtx:
            def __enter__(self):
                return FakeStreamResp()
            def __exit__(self, *args):
                return False

        with patch("audio_dl_ui.httpx.stream", return_value=FakeStreamCtx()):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is False
        assert not os.path.exists(os.path.join(_thumb_dir("job1"), "0.jpg"))


# ---------------------------------------------------------------------------
# _make_progress_hook — thumbnail fetcher wiring
# ---------------------------------------------------------------------------

class TestThumbnailFetcherWiring:
    def test_metadata_with_thumbnail_dispatches_fetch_and_re_emits(self, tmp_path, monkeypatch):
        from audio_dl_ui import _make_progress_hook
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)

        info = {
            "title": "T", "uploader": "U", "duration": 1,
            "thumbnails": [{"url": "https://img/x.jpg", "width": 320}],
        }
        with patch("audio_dl_ui.httpx.stream",
                   return_value=_mock_httpx_stream(content=b"\xff\xd8\xff\xe0fake")):
            hook = _make_progress_hook(job, urlst)
            hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000,
                  "info_dict": info})
            # Give the fetch thread a moment to complete
            time.sleep(0.5)

        events = [q.get_nowait() for _ in range(q.qsize())]
        meta = [e for e in events if e["type"] == "url_metadata"]
        # Two emissions: first thumbnail_ready=False, then True
        assert len(meta) >= 2
        assert meta[0]["thumbnail_ready"] is False
        assert meta[-1]["thumbnail_ready"] is True
        assert urlst.thumbnail_ready is True

    def test_no_thumbnails_only_one_metadata_event(self, tmp_path, monkeypatch):
        from audio_dl_ui import _make_progress_hook
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)

        info = {"title": "T", "uploader": "U", "duration": 1}  # no thumbs
        hook = _make_progress_hook(job, urlst)
        hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000,
              "info_dict": info})
        time.sleep(0.2)

        events = [q.get_nowait() for _ in range(q.qsize())]
        meta = [e for e in events if e["type"] == "url_metadata"]
        assert len(meta) == 1
        assert meta[0]["thumbnail_ready"] is False
        assert urlst.thumbnail_ready is False

    def test_fetch_failure_emits_thumbnail_ready_false_only(self, tmp_path, monkeypatch):
        from audio_dl_ui import _make_progress_hook
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)

        info = {"thumbnails": [{"url": "https://img/x.jpg", "width": 320}]}
        with patch("audio_dl_ui.httpx.stream", side_effect=Exception("network")):
            hook = _make_progress_hook(job, urlst)
            hook({"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000,
                  "info_dict": info})
            time.sleep(0.3)

        events = [q.get_nowait() for _ in range(q.qsize())]
        meta = [e for e in events if e["type"] == "url_metadata"]
        # Exactly one event (thumb_ready stays False; no re-emit on failure)
        assert len(meta) == 1
        assert meta[0]["thumbnail_ready"] is False
        assert urlst.thumbnail_ready is False


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/thumb/{url_idx}.jpg
# ---------------------------------------------------------------------------

class TestThumbnailEndpoint:
    def test_404_before_ready(self, tmp_path, monkeypatch):
        from audio_dl_ui import JOBS
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        job = _fresh_job()
        JOBS[job.id] = job
        try:
            r = client.get(f"/jobs/{job.id}/thumb/0.jpg{_csrf_query()}")
            assert r.status_code == 404
        finally:
            JOBS.pop(job.id, None)

    def test_200_after_file_exists(self, tmp_path, monkeypatch):
        from audio_dl_ui import JOBS, _thumb_dir
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        job = _fresh_job()
        JOBS[job.id] = job
        try:
            os.makedirs(_thumb_dir(job.id), exist_ok=True)
            with open(os.path.join(_thumb_dir(job.id), "0.jpg"), "wb") as f:
                f.write(b"\xff\xd8\xff\xe0jpeg-bytes")
            r = client.get(f"/jobs/{job.id}/thumb/0.jpg{_csrf_query()}")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("image/jpeg")
            assert r.content == b"\xff\xd8\xff\xe0jpeg-bytes"
        finally:
            JOBS.pop(job.id, None)

    def test_403_missing_token(self, tmp_path, monkeypatch):
        from audio_dl_ui import JOBS
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        job = _fresh_job()
        JOBS[job.id] = job
        try:
            r = client.get(f"/jobs/{job.id}/thumb/0.jpg")
            assert r.status_code == 403
        finally:
            JOBS.pop(job.id, None)

    def test_403_bad_token(self, tmp_path, monkeypatch):
        from audio_dl_ui import JOBS
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        job = _fresh_job()
        JOBS[job.id] = job
        try:
            r = client.get(f"/jobs/{job.id}/thumb/0.jpg?token=wrong")
            assert r.status_code == 403
        finally:
            JOBS.pop(job.id, None)

    def test_404_unknown_job(self):
        r = client.get(f"/jobs/nope/thumb/0.jpg{_csrf_query()}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# _build_snapshot — new rich card fields
# ---------------------------------------------------------------------------

class TestSnapshotNewFields:
    def test_snapshot_includes_card_fields(self):
        from audio_dl_ui import _build_snapshot

        job = _fresh_job()
        urlst = list(job.url_states.values())[0]
        urlst.title = "Some Title"
        urlst.uploader = "Some Uploader"
        urlst.duration = 240
        urlst.thumbnail_ready = True
        urlst.phase = "downloading"
        urlst.log.append({"ts": 1.0, "level": "info", "text": "[hls] fragment 1"})

        snap = _build_snapshot(job)
        u = snap["urls"][0]
        assert u["title"] == "Some Title"
        assert u["uploader"] == "Some Uploader"
        assert u["duration"] == 240
        assert u["thumbnail_ready"] is True
        assert u["phase"] == "downloading"
        assert u["log"] == [{"ts": 1.0, "level": "info", "text": "[hls] fragment 1"}]


class TestSnapshotPerUrlFormat:
    def test_snapshot_includes_per_url_media_format_and_default(self, tmp_path):
        body = _valid_body(output_dir=str(tmp_path))
        body["urls"] = [
            {"url": "https://youtu.be/AAA", "format": "m4a"},
            {"url": "https://youtu.be/BBB", "format": "mp4"},
        ]
        with patch("audio_dl_ui._run_one"):
            r = client.post("/jobs", json=body, headers=_csrf_headers())
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        from audio_dl_ui import _build_snapshot
        snap = _build_snapshot(JOBS[job_id])
        formats_by_url = {u["url"]: u["media_format"] for u in snap["urls"]}
        assert formats_by_url == {
            "https://youtu.be/AAA": "m4a",
            "https://youtu.be/BBB": "mp4",
        }
        assert snap["default_format"] == "m4a"  # first UrlSpec's format


class TestThumbCleanup:
    def test_thumb_dir_removed_after_completion_and_disconnect(self, tmp_path, monkeypatch):
        from audio_dl_ui import _supervise, _thumb_dir, JOBS
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        job = _fresh_job()
        JOBS[job.id] = job
        urlst = list(job.url_states.values())[0]
        urlst.status = "completed"
        os.makedirs(_thumb_dir(job.id), exist_ok=True)
        with open(os.path.join(_thumb_dir(job.id), "0.jpg"), "wb") as f:
            f.write(b"x")

        try:
            # No subscribers attached → cleanup runs immediately after _supervise
            from concurrent.futures import Future
            done: Future = Future()
            done.set_result(None)
            _supervise(job, [done])
            # Job is complete and no subscribers — thumbs cleaned
            assert not os.path.exists(_thumb_dir(job.id))
        finally:
            JOBS.pop(job.id, None)

    def test_thumb_dir_kept_while_subscribers_connected(self, tmp_path, monkeypatch):
        from audio_dl_ui import _supervise, _thumb_dir, JOBS
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        job = _fresh_job()
        JOBS[job.id] = job
        urlst = list(job.url_states.values())[0]
        urlst.status = "completed"
        os.makedirs(_thumb_dir(job.id), exist_ok=True)
        with open(os.path.join(_thumb_dir(job.id), "0.jpg"), "wb") as f:
            f.write(b"x")
        # Simulate a live subscriber
        q: queue.Queue = queue.Queue()
        with job.lock:
            job.subscribers.append(q)
        try:
            from concurrent.futures import Future
            done: Future = Future()
            done.set_result(None)
            _supervise(job, [done])
            # Subscriber still attached — dir NOT cleaned
            assert os.path.exists(_thumb_dir(job.id))
        finally:
            JOBS.pop(job.id, None)

    def test_cleanup_clears_thumbnail_ready_flags(self, tmp_path, monkeypatch):
        from audio_dl_ui import _cleanup_thumb_dir, _thumb_dir, JOBS
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        job = _fresh_job()
        JOBS[job.id] = job
        urlst = list(job.url_states.values())[0]
        urlst.thumbnail_ready = True
        os.makedirs(_thumb_dir(job.id), exist_ok=True)
        with open(os.path.join(_thumb_dir(job.id), "0.jpg"), "wb") as f:
            f.write(b"x")
        try:
            _cleanup_thumb_dir(job)
            assert not os.path.exists(_thumb_dir(job.id))
            assert urlst.thumbnail_ready is False
        finally:
            JOBS.pop(job.id, None)


class TestCardCss:
    def test_card_styles_present_in_rendered_html(self):
        r = client.get("/")
        assert r.status_code == 200
        # Sanity-check the new card style block is in the served HTML
        assert ".card {" in r.text
        assert ".card-thumb" in r.text
        assert ".card-progress" in r.text
        assert ".card-log" in r.text
        assert '[data-state="downloading"]' in r.text or '.card[data-state=' in r.text


class TestCardTemplate:
    def test_card_template_in_rendered_html(self):
        r = client.get("/")
        assert r.status_code == 200
        assert '<template id="card-template"' in r.text
        # Inner card markup elements
        assert "card-thumb" in r.text
        assert "card-title" in r.text
        assert "card-stats" in r.text
        assert "card-log" in r.text


class TestCardJs:
    def test_js_has_card_render_helpers(self):
        r = client.get("/")
        assert r.status_code == 200
        # Card rendering function names + handlers must be present
        assert "renderCard" in r.text or "upsertCard" in r.text
        assert "url_metadata" in r.text
        assert "url_log" in r.text
        # The thumbnail URL must include the CSRF token query
        assert "/thumb/" in r.text

    def test_reveal_button_in_card_template_and_js(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "card-reveal" in r.text
        assert "/reveal" in r.text  # at least somewhere in JS


# ---------------------------------------------------------------------------
# v1.8 — global executor concurrency cap
# ---------------------------------------------------------------------------

class TestGlobalExecutorCap:
    """v1.8: the process-wide _GLOBAL_EXECUTOR caps concurrent URL downloads
    across all submissions. POSTing two submissions of 2 URLs each with the
    pool capped at 2 workers must never run more than 2 simultaneously."""

    def test_max_parallel_enforced_across_submissions(self, tmp_path, monkeypatch):  # pylint: disable=too-many-locals
        import audio_dl_ui as ui
        from concurrent.futures import ThreadPoolExecutor

        active = {"count": 0, "peak": 0}
        lock = threading.Lock()

        def fake_download(*_args, **_kwargs):
            with lock:
                active["count"] += 1
                if active["count"] > active["peak"]:
                    active["peak"] = active["count"]
            try:
                # Sleep long enough that all four URLs queue up together —
                # any failure of the cap would push peak past 2.
                time.sleep(0.5)
            finally:
                with lock:
                    active["count"] -= 1
            return [str(tmp_path / "ok.mp3")]

        monkeypatch.setattr(ui, "download_media", fake_download)
        monkeypatch.setattr(ui, "sanitize_url", lambda u: u)

        # Replace the global executor with a 2-worker one for this test.
        # Save/restore so other tests aren't affected.
        original = ui._GLOBAL_EXECUTOR
        capped = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-cap")
        ui._GLOBAL_EXECUTOR = capped
        try:
            body_a = _valid_body(output_dir=str(tmp_path))
            body_a["urls"] = [
                {"url": "https://youtu.be/A1", "format": "mp3"},
                {"url": "https://youtu.be/A2", "format": "mp3"},
            ]
            body_b = _valid_body(output_dir=str(tmp_path))
            body_b["urls"] = [
                {"url": "https://youtu.be/B1", "format": "mp3"},
                {"url": "https://youtu.be/B2", "format": "mp3"},
            ]
            r_a = client.post("/jobs", json=body_a, headers=_csrf_headers())
            r_b = client.post("/jobs", json=body_b, headers=_csrf_headers())
            assert r_a.status_code == 200
            assert r_b.status_code == 200
            job_a = r_a.json()["job_id"]
            job_b = r_b.json()["job_id"]

            # Wait for both jobs to complete.
            deadline = time.time() + 15.0
            while time.time() < deadline:
                if JOBS[job_a].completed and JOBS[job_b].completed:
                    break
                time.sleep(0.05)
            assert JOBS[job_a].completed, "job A did not complete in time"
            assert JOBS[job_b].completed, "job B did not complete in time"

            # Cap enforced — peak observed concurrency stays <= 2 even with
            # 4 URLs of demand across two submissions.
            assert active["peak"] <= 2, f"peak concurrency {active['peak']} exceeded cap of 2"
            # And the test actually exercised concurrency (sanity).
            assert active["peak"] >= 2, (
                f"peak concurrency {active['peak']} — test didn't actually overlap"
            )
        finally:
            capped.shutdown(wait=True)
            ui._GLOBAL_EXECUTOR = original
            JOBS.pop(job_a, None)
            JOBS.pop(job_b, None)


# ---------------------------------------------------------------------------
# v1.8 — /reveal allow-list semantics
# ---------------------------------------------------------------------------

class TestRevealAllowList:
    """v1.8: /reveal validates against the configured output_dir allow-list
    rather than a live JOBS path lookup, so history items can re-reveal
    after their originating job ages out of JOBS."""

    def test_reveal_accepts_on_disk_path_not_in_jobs(self, tmp_path, monkeypatch):
        """File exists, lives under the configured output_dir, no JOBS
        entry references it → 200."""
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, app as _app

        target = tmp_path / "song.mp3"
        target.write_bytes(b"x")

        # Configure allow-list root via the same surface main() uses.
        original_default = getattr(_app.state, "default_output_dir", None)
        _app.state.default_output_dir = str(tmp_path)
        JOBS.clear()

        called = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda *a, **kw: called.append((a, kw)) or None,
        )
        try:
            r = client.post(
                "/reveal", json={"path": str(target)}, headers=_csrf_headers()
            )
            assert r.status_code == 200, f"got {r.status_code}: {r.text}"
            assert r.json() == {"ok": True}
            assert called, "subprocess.run must be invoked for accepted path"
            assert called[0][0][0][:2] == ["open", "-R"]
        finally:
            if original_default is None:
                if hasattr(_app.state, "default_output_dir"):
                    delattr(_app.state, "default_output_dir")
            else:
                _app.state.default_output_dir = original_default

    def test_reveal_rejects_path_outside_allowlist(self, tmp_path, monkeypatch):
        """Path exists on disk but isn't inside any allow-listed root → 403."""
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, app as _app

        # Create a file outside tmp_path's allow-list root.
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_target = outside / "leak.txt"
        outside_target.write_bytes(b"y")

        # Configure a more restrictive root: a sibling subdir.
        restricted = tmp_path / "allowed"
        restricted.mkdir()

        original_default = getattr(_app.state, "default_output_dir", None)
        _app.state.default_output_dir = str(restricted)
        JOBS.clear()

        called = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda *a, **kw: called.append((a, kw)) or None,
        )
        try:
            r = client.post(
                "/reveal",
                json={"path": str(outside_target)},
                headers=_csrf_headers(),
            )
            assert r.status_code == 403, f"got {r.status_code}: {r.text}"
            assert not called, "subprocess.run must not fire for forbidden paths"
        finally:
            if original_default is None:
                if hasattr(_app.state, "default_output_dir"):
                    delattr(_app.state, "default_output_dir")
            else:
                _app.state.default_output_dir = original_default

    def test_reveal_rejects_path_traversal(self, tmp_path, monkeypatch):
        """A path that lexically begins inside the allow-list but resolves
        outside via .. must be rejected (403). Path.resolve() collapses the
        traversal before is_relative_to runs."""
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, app as _app

        # Restricted root + a sentinel file inside it (so the allow-list
        # has at least one valid entry).
        restricted = tmp_path / "allowed"
        restricted.mkdir()
        (restricted / "ok.mp3").write_bytes(b"z")

        # Construct a traversal that points outside restricted.
        evil = f"{restricted}/../../../etc/passwd"

        original_default = getattr(_app.state, "default_output_dir", None)
        _app.state.default_output_dir = str(restricted)
        JOBS.clear()

        called = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda *a, **kw: called.append((a, kw)) or None,
        )
        try:
            r = client.post("/reveal", json={"path": evil}, headers=_csrf_headers())
            # Either 403 (resolved outside allow-list) or 404 (resolved path
            # doesn't exist on this filesystem). 404 still satisfies the
            # safety property — subprocess never fires.
            assert r.status_code in (403, 404), f"got {r.status_code}: {r.text}"
            assert not called, "subprocess.run must not fire for traversal attempts"
        finally:
            if original_default is None:
                if hasattr(_app.state, "default_output_dir"):
                    delattr(_app.state, "default_output_dir")
            else:
                _app.state.default_output_dir = original_default
