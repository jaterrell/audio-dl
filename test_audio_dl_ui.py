# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods
# pylint: disable=import-outside-toplevel,reimported,redefined-outer-name,protected-access,unused-argument
# pylint: disable=too-many-lines
"""Tests for audio_dl_ui.py — validation, SSE, cancel, reveal, throttle."""
import json
import re
import threading
import time

import pytest
from fastapi.testclient import TestClient

from audio_dl_ui import app, JOBS

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
        r = client.post("/jobs", json=_valid_body(urls=""), headers=_csrf_headers())
        assert r.status_code == 400
        assert "url" in r.json()["detail"].lower()

    def test_whitespace_only_urls_400(self):
        r = client.post("/jobs", json=_valid_body(urls="   \n  \t  "), headers=_csrf_headers())
        assert r.status_code == 400

    def test_bad_format_400(self):
        r = client.post("/jobs", json=_valid_body(format="ogg"), headers=_csrf_headers())
        assert r.status_code == 400
        assert "format" in r.json()["detail"].lower()

    def test_jobs_too_low_400(self):
        r = client.post("/jobs", json=_valid_body(jobs=0), headers=_csrf_headers())
        assert r.status_code == 400

    def test_jobs_too_high_400(self):
        r = client.post("/jobs", json=_valid_body(jobs=9), headers=_csrf_headers())
        assert r.status_code == 400

    def test_fragments_too_low_400(self):
        r = client.post("/jobs", json=_valid_body(fragments=0), headers=_csrf_headers())
        assert r.status_code == 400

    def test_fragments_too_high_400(self):
        r = client.post("/jobs", json=_valid_body(fragments=17), headers=_csrf_headers())
        assert r.status_code == 400

    def test_unwritable_output_dir_400(self):
        # /dev/null/foo will fail os.makedirs with NotADirectoryError on macOS/Linux
        r = client.post("/jobs", json=_valid_body(output_dir="/dev/null/cant-make-this"),
                        headers=_csrf_headers())
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

        body = _valid_body(
            urls="https://youtu.be/AAA https://youtu.be/BBB",
            output_dir=str(tmp_path),
            jobs=2,
        )
        r = client.post("/jobs", json=body, headers=_csrf_headers())
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
        hook({"status": "finished", "downloaded_bytes": 0})
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

        body = _valid_body(
            urls="https://youtu.be/AAA",
            output_dir=str(tmp_path),
        )
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
            playlist=False, force=False, fragments=4, jobs=1,
            url_states={url: UrlState(url=url)},
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
        body = _valid_body(urls="https://youtu.be/AAA", output_dir=str(tmp_path))
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

        body = _valid_body(urls="https://youtu.be/AAA", output_dir=str(tmp_path))
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
    def test_unknown_path_400(self, monkeypatch):
        import audio_dl_ui as ui
        called = []
        monkeypatch.setattr(
            ui.subprocess, "run",
            lambda *a, **kw: called.append((a, kw)) or None,
        )
        r = client.post("/reveal", json={"path": "/etc/passwd"}, headers=_csrf_headers())
        assert r.status_code == 400
        assert not called, "subprocess.run must not be invoked for unknown paths"

    def test_known_path_calls_open_dash_r(self, tmp_path, monkeypatch):
        """Register a path in a fake job, then reveal it."""
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, JobState, UrlState

        path = str(tmp_path / "song.mp3")
        (tmp_path / "song.mp3").write_bytes(b"x")

        job = JobState(
            id="manual", media_format="mp3", output_dir=str(tmp_path),
            playlist=False, force=False, fragments=4, jobs=1,
            url_states={"u": UrlState(url="u", paths=[path], status="completed")},
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
            assert called == [((["open", "-R", path],), {"check": False})]
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

        body = _valid_body(urls="https://youtu.be/AAA", output_dir=str(tmp_path))
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


# ---------------------------------------------------------------------------
# /reveal dict-mutation race (Codex [P2])
# ---------------------------------------------------------------------------

class TestRevealSnapshotsJobs:
    """The /reveal handler must snapshot JOBS before iterating, otherwise a
    concurrent POST /jobs can mutate it mid-iteration and trigger
    RuntimeError: dictionary changed size during iteration. The behavior we
    care about is "no crash" — paths added DURING the iteration aren't
    visible (that's the snapshot tradeoff, and it's acceptable; the client
    can retry)."""

    def test_reveal_survives_concurrent_jobs_mutation(self, tmp_path, monkeypatch):
        import audio_dl_ui as ui
        from audio_dl_ui import JOBS, JobState

        # A job whose url_states.values() mutates JOBS mid-iteration.
        # Without snapshotting outer JOBS.values(), this would raise
        # RuntimeError: dictionary changed size during iteration.
        class _MutatingStates(dict):
            def values(self):  # type: ignore[override]
                JOBS[f"mid-iter-{len(JOBS)}"] = JOBS["racer"]
                return super().values()

        racer = JobState(
            id="racer", media_format="mp3", output_dir=str(tmp_path),
            playlist=False, force=False, fragments=4, jobs=1,
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
            # The request itself must not 500; 400 (path not in known set)
            # is acceptable. Pre-fix, this raises RuntimeError → 500.
            r = client.post("/reveal", json={"path": "/anything"}, headers=_csrf_headers())
            assert r.status_code != 500, f"got 500: {r.text}"
            assert r.status_code in (200, 400)
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
            playlist=False, force=False, fragments=4, jobs=1,
            url_states={url: UrlState(url=url)},
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


class TestBtoaUnicodeSafe:
    """The rowFor() JS uses btoa for row ids. Raw btoa throws on non-ASCII;
    wrapping with unescape(encodeURIComponent(...)) makes it UTF-8 safe."""

    def test_js_uses_utf8_safe_btoa(self):
        # Structural assertion on the embedded JS (post-refactor: was _INDEX_HTML).
        from audio_dl_ui import _INDEX_JS
        assert "btoa(unescape(encodeURIComponent(url)))" in _INDEX_JS
        # No remaining raw btoa(url) without the wrap.
        assert "btoa(url)" not in _INDEX_JS


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
        """_INDEX_CSS_THEMES contains exactly 10 :root[data-theme="<slug>"] selectors,
        in the same order as the JS THEMES registry (Task 3)."""
        from audio_dl_ui import _INDEX_CSS_THEMES
        found = re.findall(r':root\[data-theme="([^"]+)"\]', _INDEX_CSS_THEMES)
        assert found == self.EXPECTED_SLUGS, (
            f"Expected {self.EXPECTED_SLUGS}, found {found}"
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
