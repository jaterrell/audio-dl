#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""
audio_dl_ui — One-page web UI for audio_dl.

Sibling package to audio_dl.py. Reuses download_media, sanitize_url, and
ALL_FORMATS. fastapi/uvicorn live behind the [ui] optional-dependency
extra so the CLI install stays minimal.

Usage:
    audio-dl-ui                          # bind 127.0.0.1:8000, open browser
    audio-dl-ui --port 9000              # custom port
    audio-dl-ui --output-dir ~/Music     # change default output dir
    audio-dl-ui --no-browser             # don't auto-open the browser
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import importlib.util
import json
import os
import queue
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from dataclasses import dataclass, field
from importlib.resources import files as _importlib_files
from pathlib import Path
from typing import Callable, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from audio_dl import (
    ALL_FORMATS,
    _check_dependencies,
    detect_platform,
    download_media,
    sanitize_url,
    __version__,
)
from audio_dl_ui.related import _pick_thumbnail_url
from audio_dl_ui import related as _related

# uvicorn is an optional dep (UI extra). Imported lazily in main() to avoid
# ImportError when the package is installed without [ui]. Exposed as a
# module-level name so tests can monkeypatch it before calling main().
uvicorn = None  # type: ignore[assignment]  # pylint: disable=invalid-name

_BUILD_ID = os.environ.get("AUDIO_DL_BUILD", "dev")
_DEV_MODE = os.environ.get("AUDIO_DL_DEV") == "1"
_LOOPBACK_HOSTS = frozenset(("127.0.0.1", "::1", "localhost"))


def _refresh_dev_mode() -> None:
    """Re-read AUDIO_DL_DEV. Used by tests to flip mode mid-process."""
    global _DEV_MODE  # pylint: disable=global-statement
    _DEV_MODE = os.environ.get("AUDIO_DL_DEV") == "1"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class _Cancelled(Exception):
    """Raised inside a yt-dlp progress hook to abort an in-flight download."""


@dataclass
class UrlState:  # pylint: disable=too-many-instance-attributes
    """Per-URL download state within a job, updated by progress hooks."""

    url: str
    media_format: str        # v1.9 — per-URL target format
    sanitized_url: str = ""
    status: Literal["pending", "downloading", "completed", "failed", "cancelled"] = "pending"
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
    filename: str | None = None
    paths: list[str] = field(default_factory=list)
    error: str | None = None
    last_progress_emit: float = 0.0
    # v1.6 — rich card fields
    title: str | None = None
    uploader: str | None = None
    duration: int | None = None
    thumbnail_ready: bool = False
    phase: str | None = None
    log: "collections.deque[dict]" = field(
        default_factory=lambda: collections.deque(maxlen=50)
    )
    # Tracks whether url_metadata has already been emitted (so we don't
    # re-emit on every hook tick — only on first info-dict and on
    # thumb-fetched).
    metadata_emitted: bool = False
    # v2.0 Task 6 — stable thumb_id written to the persistent cache on completion.
    thumb_id: str | None = None
    # Related-content discovery (spec 2026-07-01):
    # None       — never started (disabled, or failed before first metadata tick)
    # "pending"  — discovery task submitted, unresolved
    # "ready" | "none" | "error" | "unsupported" — resolved outcomes.
    # Every task exit path moves the status off "pending".
    related_status: str | None = None
    related_items: list[dict] = field(default_factory=list)


@dataclass
class JobState:  # pylint: disable=too-many-instance-attributes
    """Holds the entire state of a batch download job, including all URL states.

    Broadcast architecture (v1.3): every SSE subscriber registers its own
    ``queue.Queue`` and ``_emit`` fans events out to all of them, so a
    reconnect-during-job no longer races and splits events between connections.

    New subscribers receive a single ``job_snapshot`` event (cumulative
    state) on connect — they don't replay historical events. The UI is
    state-driven, not event-replay-driven; the snapshot captures everything
    a fresh subscriber needs to render the current state without ambiguity
    about which past events to apply.

    ``lock`` protects ``subscribers``; ``_emit`` snapshots the subscriber
    list under the lock before fanning out, so registration and broadcast
    can't race.
    """

    id: str
    media_format: str
    output_dir: str
    playlist: bool
    force: bool
    fragments: int
    url_states: dict[str, UrlState]
    subscribers: list["queue.Queue[dict]"] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancelled: bool = False
    completed: bool = False
    executor: ThreadPoolExecutor | None = None
    futures: list = field(default_factory=list)


JOBS: dict[str, JobState] = {}

# v1.8: process-wide worker pool shared across all submissions. Initialized
# by main() from --max-parallel. URLs from different submissions compete for
# the same workers, so the total concurrent-download cap is a single tuning
# knob rather than a per-submission setting. Tests may monkey-patch this
# directly with their own ThreadPoolExecutor.
_GLOBAL_EXECUTOR: ThreadPoolExecutor | None = None

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


def _submit_related_discovery(job: "JobState", url_state: "UrlState", seed: dict) -> None:
    """Hand the discovery task to the pool. Wrapped: called from the progress
    hook, which must never raise (it would abort the real download) — a
    submit failure just downgrades the status to "error"."""
    try:
        executor = _RELATED_EXECUTOR or _related_executor()
        executor.submit(_run_discovery, job, url_state, seed)
    except Exception:  # pylint: disable=broad-except
        url_state.related_status = "error"


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
            # Doomed result (cancelled mid-discover or download failed) —
            # don't spend CDN fetches; the suppression block below drops the
            # items anyway. Checked per-iteration, after the unconditional
            # pop, so _thumb_src is still stripped from every item.
            if job.cancelled or url_state.status in ("failed", "cancelled"):
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


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

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


def _put_with_overflow(q: "queue.Queue[dict]", event: dict) -> None:
    """Push one event onto one subscriber's queue with overflow handling.

    Guaranteed events take a small block-with-timeout so a momentarily-full
    queue still gets the lifecycle signal. If the timeout expires, drop the
    oldest event to make room — silently losing a guaranteed event would hang
    the client UI. Progress events use put_nowait and drop on Full.
    """
    if event.get("type") in _GUARANTEED_EVENT_TYPES:
        try:
            q.put(event, timeout=1.0)
            return
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # truly stuck; worst-case outcome
    else:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass  # drop excess progress


_LOG_KEEP_PREFIXES = (
    "[hls] downloading fragment",
    "[ffmpeg]",
    "[ExtractAudio]",
    "[EmbedThumbnail]",
    "[Metadata]",
)


def _should_keep_log(level: str, text: str) -> bool:
    """Filter yt-dlp log lines down to ones worth showing the user."""
    if level in ("warning", "error"):
        return True
    if level == "debug":
        return False
    # level == "info" (or anything else): keep only known phase markers
    return any(text.startswith(p) for p in _LOG_KEEP_PREFIXES)


_THUMB_ROOT = os.path.join(tempfile.gettempdir(), "audio-dl-thumbs")


def _thumb_dir(job_id: str) -> str:
    return os.path.join(_THUMB_ROOT, job_id)


def _cleanup_thumb_dir(job: "JobState") -> None:
    """Remove the job's thumb dir AND clear thumbnail_ready flags so any
    post-cleanup snapshot accurately reports the thumbs are gone.

    Idempotent and never raises.
    """
    path = _thumb_dir(job.id)
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # pylint: disable=broad-except
        pass
    # Clear flags so a late-connecting subscriber sees thumbnail_ready=False
    for st in job.url_states.values():
        st.thumbnail_ready = False


def _url_idx(job: "JobState", raw_url: str) -> int:
    """0-based position of the URL within the job's submission order."""
    for i, u in enumerate(job.url_states.keys()):
        if u == raw_url:
            return i
    return -1


_THUMB_MAX_BYTES = 5 * 1024 * 1024  # 5MB cap; real thumbs are <100KB


def _fetch_thumbnail(job_id: str, url_idx: int, src_url: str) -> bool:
    """Stream a thumbnail to {THUMB_ROOT}/{job_id}/{url_idx}.jpg.

    Returns True on success, False on any failure (timeout, non-200,
    write error, exceeds size cap). No retries. Never raises.
    """
    try:
        target_dir = _thumb_dir(job_id)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"{url_idx}.jpg")
        tmp_fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=".thumb-", suffix=".tmp")
        try:
            with httpx.stream(
                "GET", src_url, timeout=5.0, follow_redirects=True
            ) as resp:
                if resp.status_code != 200:
                    raise IOError("non-200")
                total = 0
                with os.fdopen(tmp_fd, "wb") as f:
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > _THUMB_MAX_BYTES:
                            raise IOError("exceeded size cap")
                        f.write(chunk)
            os.replace(tmp_path, target)
            return True
        except Exception:  # pylint: disable=broad-except
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False
    except Exception:  # pylint: disable=broad-except
        return False


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


class _YDLLogger:
    """yt-dlp-compatible logger that routes filtered lines into a URL's
    state deque and broadcasts each kept line as a ``url_log`` SSE event.

    yt-dlp invokes ``.debug``, ``.info``, ``.warning``, ``.error`` with
    a single string (sometimes an exception). We coerce, filter, append,
    emit. Never raises — a logger that crashes would break the download.
    """
    # pylint: disable=missing-function-docstring

    def __init__(self, job: "JobState", url_state: "UrlState") -> None:
        self._job = job
        self._url_state = url_state

    def _route(self, level: str, msg) -> None:
        try:
            text = str(msg)
        except Exception:  # pylint: disable=broad-except
            text = repr(msg)
        if not _should_keep_log(level, text):
            return
        entry = {"ts": time.time(), "level": level, "text": text}
        self._url_state.log.append(entry)
        _emit(self._job, {
            "type": "url_log",
            "job_id": self._job.id,
            "url": self._url_state.url,
            "level": level,
            "text": text,
            "ts": entry["ts"],
        })

    def debug(self, msg) -> None:
        self._route("debug", msg)

    def info(self, msg) -> None:
        self._route("info", msg)

    def warning(self, msg) -> None:
        self._route("warning", msg)

    def error(self, msg) -> None:
        self._route("error", msg)


def _make_url_logger(job: "JobState", url_state: "UrlState") -> _YDLLogger:
    """Factory — kept as a function for test seam parity with hooks."""
    return _YDLLogger(job, url_state)


def _emit(job: JobState, event: dict) -> None:
    """Broadcast an SSE event to every subscriber currently connected.

    Snapshots the subscriber list under the lock so register/unregister can't
    mutate it mid-iteration. The actual ``put`` happens without the lock so
    a slow consumer doesn't block emitters.
    """
    if event.get("type") == "job_completed":
        job.completed = True
    with job.lock:
        subs = list(job.subscribers)
    for q in subs:
        _put_with_overflow(q, event)


def _require_csrf(request: Request) -> str:
    """Verify CSRF token from X-Audio-DL-Token header OR ?token= query param."""
    expected = getattr(request.app.state, "csrf_token", None)
    if not expected:
        # Token not initialized (TestClient + no main() call). Block by default.
        raise HTTPException(403, "CSRF token not configured.")
    provided = request.headers.get("X-Audio-DL-Token") or request.query_params.get("token")
    if not provided:
        raise HTTPException(403, "Missing CSRF token.")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(403, "Invalid CSRF token.")
    return provided


def _make_progress_hook(job: JobState, url_state: UrlState) -> Callable[[dict], None]:
    """
    Build a yt-dlp progress hook bound to one URL.

    - Raises `_Cancelled` when `job.cancelled` is set (yt-dlp will surface
      this as a DownloadError, which `_run_one` catches).
    - Throttles to at most ~5 events/sec/URL.
    - On the first tick carrying an info_dict, emits url_metadata with
      thumbnail_ready=False and stores title/uploader/duration on UrlState.
    """
    def hook(d: dict) -> None:
        if job.cancelled:
            raise _Cancelled()

        info = d.get("info_dict") or {}
        if info and not url_state.metadata_emitted:
            url_state.title = info.get("title")
            url_state.uploader = info.get("uploader")
            url_state.duration = info.get("duration")
            url_state.metadata_emitted = True

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

            _emit(job, {
                "type": "url_metadata",
                "job_id": job.id,
                "url": url_state.url,
                "title": url_state.title,
                "uploader": url_state.uploader,
                "duration": url_state.duration,
                "thumbnail_ready": False,
                "related_status": url_state.related_status,
            })

            # Submit only now that url_metadata (carrying "pending") has been
            # emitted, so the worker thread can't race a url_related ahead of
            # it. related_seed is None unless the status resolved to "pending".
            if related_seed is not None:
                _submit_related_discovery(job, url_state, related_seed)

            thumb_src = _pick_thumbnail_url(info)
            if thumb_src:
                idx = _url_idx(job, url_state.url)

                def _do_fetch() -> None:
                    if _fetch_thumbnail(job.id, idx, thumb_src):
                        url_state.thumbnail_ready = True
                        _emit(job, {
                            "type": "url_metadata",
                            "job_id": job.id,
                            "url": url_state.url,
                            "title": url_state.title,
                            "uploader": url_state.uploader,
                            "duration": url_state.duration,
                            "thumbnail_ready": True,
                            "related_status": url_state.related_status,
                        })

                threading.Thread(target=_do_fetch, daemon=True).start()

        status = d.get("status")
        if status == "finished":
            # yt-dlp signals download-complete; postprocessing begins now.
            url_state.phase = "postprocessing"
            _emit(job, {
                "type": "progress",
                "job_id": job.id,
                "url": url_state.url,
                "percent": 100.0,
                "downloaded_bytes": d.get("downloaded_bytes") or url_state.downloaded_bytes,
                "total_bytes": d.get("total_bytes") or url_state.total_bytes,
                "speed": None,
                "eta": None,
                "filename": d.get("filename") or url_state.filename,
                "phase": "postprocessing",
            })
            return

        if status != "downloading":
            return

        now = time.monotonic()
        if now - url_state.last_progress_emit < 0.2:
            return
        url_state.last_progress_emit = now

        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes") or 0
        percent = (downloaded / total * 100) if total else 0.0

        url_state.percent = percent
        url_state.downloaded_bytes = downloaded
        url_state.total_bytes = total
        url_state.speed = d.get("speed")
        url_state.eta = d.get("eta")
        url_state.filename = d.get("filename")
        url_state.phase = "downloading"

        _emit(job, {
            "type": "progress",
            "job_id": job.id,
            "url": url_state.url,
            "percent": percent,
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "speed": d.get("speed"),
            "eta": d.get("eta"),
            "filename": d.get("filename"),
            "phase": "downloading",
        })

    return hook


def _run_one(job: JobState, raw_url: str) -> None:
    """One unit of work for the executor: sanitize, download, emit events."""
    url_state = job.url_states[raw_url]

    # Cancel-before-start: handles the race where a future is scheduled
    # but hadn't started running when cancel was hit.
    if job.cancelled:
        url_state.status = "cancelled"
        url_state.phase = "failed"
        url_state.error = "Cancelled"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Cancelled"})
        return

    hook = _make_progress_hook(job, url_state)
    try:
        url_state.phase = "resolving"
        clean = sanitize_url(raw_url)
        url_state.sanitized_url = clean
        url_state.status = "downloading"
        _emit(job, {"type": "url_started", "job_id": job.id,
                    "url": raw_url, "sanitized_url": clean})

        paths = download_media(
            clean,
            media_format=url_state.media_format,
            output_dir=job.output_dir,
            playlist=job.playlist,
            force=job.force,
            concurrent_fragments=job.fragments,
            progress_hooks=[hook],
            logger=_make_url_logger(job, url_state),
        )
    except _Cancelled:
        url_state.status = "cancelled"
        url_state.phase = "failed"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Cancelled"})
        return
    except Exception as e:  # pylint: disable=broad-except
        # yt-dlp may wrap _Cancelled in DownloadError — detect by chained cause.
        if isinstance(e.__cause__, _Cancelled) or "Cancelled" in str(e):
            url_state.status = "cancelled"
            url_state.phase = "failed"
            _emit(job, {"type": "url_failed", "job_id": job.id,
                        "url": raw_url, "error": "Cancelled"})
            return
        url_state.status = "failed"
        url_state.phase = "failed"
        url_state.error = str(e)
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": str(e)})
        return

    if not paths:
        url_state.status = "failed"
        url_state.phase = "failed"
        url_state.error = "Download failed"
        _emit(job, {"type": "url_failed", "job_id": job.id,
                    "url": raw_url, "error": "Download failed"})
        return

    url_state.status = "completed"
    url_state.phase = "complete"
    url_state.paths = paths

    # Persist the live thumbnail (fetched in the metadata callback by
    # _fetch_thumbnail) into the stable on-disk thumb cache so the Library
    # view can serve it via /thumbs/{thumb_id}.jpg long after the job
    # expires. Earlier v2.0 code looked for a sibling .jpg next to the audio
    # file; that only existed if yt-dlp didn't run EmbedThumbnail, which
    # we do for every audio format. The live thumb path is the only
    # reliable source post-postprocessing.
    idx = _url_idx(job, raw_url)
    live_thumb = Path(_thumb_dir(job.id)) / f"{idx}.jpg"
    # The background fetcher runs in a daemon thread; on fast downloads it
    # may not have finished by the time we get here. Briefly wait — the
    # fetch itself has a 5s timeout, so up to ~1.5s of polling is safe.
    for _ in range(15):
        if live_thumb.exists():
            break
        time.sleep(0.1)
    if live_thumb.exists():
        try:
            url_state.thumb_id = _persist_thumb(raw_url, live_thumb.read_bytes())
        except OSError:
            pass  # Persisting a thumbnail must never break the job.

    _emit(job, {"type": "url_completed", "job_id": job.id,
                "url": raw_url, "paths": paths,
                "thumb_id": url_state.thumb_id})


def _supervise(job: JobState, futures: list) -> None:
    """Wait for all futures, then emit job_completed and clean up."""
    wait(futures, return_when=ALL_COMPLETED)
    # Futures cancelled by the executor (cancel_futures=True path) never
    # ran _run_one, so their url_states are still 'pending'. Reclassify
    # them as 'cancelled' and emit the matching url_failed event so the
    # UI shows the right state.
    if job.cancelled:
        for st in job.url_states.values():
            if st.status in ("pending", "downloading"):
                st.status = "cancelled"
                st.error = "Cancelled"
                _emit(job, {"type": "url_failed", "job_id": job.id,
                            "url": st.url, "error": "Cancelled"})
    summary = {"completed": 0, "failed": 0, "cancelled": 0}
    for st in job.url_states.values():
        if st.status == "completed":
            summary["completed"] += 1
        elif st.status == "cancelled":
            summary["cancelled"] += 1
        else:
            summary["failed"] += 1
    _emit(job, {"type": "job_completed", "job_id": job.id, "summary": summary})
    # v1.8: executor is the process-wide _GLOBAL_EXECUTOR, shared with other
    # jobs — do NOT shut it down here. Per-job teardown is just the thumb dir.
    # Best-effort cleanup of thumbnail tempdir. Only remove if no
    # subscribers are still streaming — otherwise reconnects in the next
    # second would 404 on thumbs that should still render.
    with job.lock:
        subs_remaining = len(job.subscribers)
    if subs_remaining == 0:
        _cleanup_thumb_dir(job)


def _start_job(job: JobState) -> None:
    """Spin up the executor and supervisor. Called from POST /jobs.

    v1.3: there is no ``job_started`` event anymore. The initial state of all
    URLs is conveyed via the ``job_snapshot`` event that every SSE subscriber
    receives on connect. This sidesteps the race where a subscriber connects
    after ``_start_job`` and would otherwise miss the original ``job_started``
    in a pure-broadcast model.

    v1.8: URLs are submitted to a process-wide ``_GLOBAL_EXECUTOR`` so the
    total concurrent-download cap is shared across all submissions. The job's
    ``executor`` attribute is set to the same global instance for backwards
    compatibility with code paths (cancel) that reach for it; supervisor
    does NOT shut it down on job_completed. If ``_GLOBAL_EXECUTOR`` is None
    (no ``main()`` call — typical in tests), one is created lazily using a
    conservative default so tests don't have to bootstrap it.
    """
    global _GLOBAL_EXECUTOR  # pylint: disable=global-statement
    if _GLOBAL_EXECUTOR is None:
        _GLOBAL_EXECUTOR = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="audio-dl-worker"
        )
    job.executor = _GLOBAL_EXECUTOR
    job.futures = [
        _GLOBAL_EXECUTOR.submit(_run_one, job, url)
        for url in job.url_states
    ]
    supervisor = threading.Thread(target=_supervise, args=(job, job.futures), daemon=True)
    supervisor.start()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="audio-dl-ui", version=__version__)


class UrlSpec(BaseModel):
    """One URL + the target format for that URL (v1.9 per-URL format)."""

    url: str
    format: str


class JobRequest(BaseModel):
    """Request body for POST /jobs (v1.9: per-URL format)."""

    urls: list[UrlSpec]
    output_dir: str | None = None  # default to launch-time --output-dir
    playlist: bool = False
    force: bool = False
    fragments: int = 4
    # NOTE: top-level `format` removed in v1.9 — each UrlSpec carries its own.
    # NOTE: `jobs` removed in v1.9 — vestigial since v1.8 (global executor).


@app.post("/jobs")
async def post_jobs(req: JobRequest, _csrf: str = Depends(_require_csrf)) -> dict:  # pylint: disable=unused-argument
    """Validate the request, register a JobState, return the job_id."""
    if not req.urls:
        raise HTTPException(400, "At least one URL is required.")
    seen_urls: set[str] = set()
    for spec in req.urls:
        if spec.format not in ALL_FORMATS:
            raise HTTPException(
                400,
                f"Unknown format: {spec.format!r} for {spec.url!r}. "
                f"Must be one of {ALL_FORMATS}.",
            )
        if spec.url in seen_urls:
            # Reject duplicates instead of silently dropping work via last-wins
            # dict insertion. The UI's cardState dedupe prevents this in
            # practice; API consumers get a clear error.
            raise HTTPException(
                400,
                f"Duplicate URL in submission: {spec.url!r}. "
                f"Each URL may appear at most once per request.",
            )
        seen_urls.add(spec.url)

    if not 1 <= req.fragments <= 16:
        raise HTTPException(400, "fragments must be in 1..16.")

    chosen_dir = req.output_dir or getattr(app.state, "default_output_dir", "")
    if not chosen_dir:
        raise HTTPException(400, "output_dir not configured and not provided.")
    output_dir = os.path.expanduser(chosen_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"output_dir not writable: {e}") from e

    job_id = uuid.uuid4().hex
    # Preserve order from the request. Duplicates were rejected above.
    url_states = {}
    for spec in req.urls:
        url_states[spec.url] = UrlState(url=spec.url, media_format=spec.format)
    job = JobState(
        id=job_id,
        # JobState.media_format keeps the submission's "default" — first spec's
        # format. Downloads no longer read this; only the snapshot's
        # default_format field does.
        media_format=req.urls[0].format,
        output_dir=output_dir,
        playlist=req.playlist,
        force=req.force,
        fragments=req.fragments,
        url_states=url_states,
    )
    JOBS[job_id] = job
    _start_job(job)
    return {"job_id": job_id}


def _build_snapshot(job: JobState) -> dict:
    """Build a ``job_snapshot`` event describing the job's current state.

    Sent as the first event to every new SSE subscriber so a reconnecting or
    late-joining browser can rebuild its UI without having received the
    original ``job_started``/``progress``/``url_completed`` sequence. Includes
    a ``complete`` flag so a subscriber that connects after ``job_completed``
    can still flip its UI to the terminal state.
    """
    summary: dict | None = None
    if job.completed:
        summary = {
            "completed": sum(1 for s in job.url_states.values() if s.status == "completed"),
            "failed": sum(
                1 for s in job.url_states.values()
                if s.status in ("failed", "cancelled")
            ),
        }
    return {
        "type": "job_snapshot",
        "job_id": job.id,
        "complete": job.completed,
        "summary": summary,
        "default_format": job.media_format,   # v1.9
        "urls": [
            {
                "url": s.url,
                "media_format": s.media_format,   # v1.9
                "status": s.status,
                "percent": s.percent,
                "downloaded_bytes": s.downloaded_bytes,
                "total_bytes": s.total_bytes,
                "speed": s.speed,
                "eta": s.eta,
                "filename": s.filename,
                "paths": list(s.paths),
                "error": s.error,
                # v1.6 — rich card fields
                "title": s.title,
                "uploader": s.uploader,
                "duration": s.duration,
                "thumbnail_ready": s.thumbnail_ready,
                "phase": s.phase,
                "log": list(s.log),
                "thumb_id": s.thumb_id,  # v2.0 Task 6
                "related_status": s.related_status,
                "related_items": list(s.related_items),
            }
            for s in job.url_states.values()
        ],
    }


# Late-results SSE linger cap (spec "Late results"). Module-level so tests
# can shrink it instead of waiting out the real window.
_RELATED_LINGER_CAP_SECONDS = 10.0


async def _events_iter(job_id: str):
    """SSE generator: register as a subscriber, yield snapshot, live-stream.

    Sequence:

    1. Register a per-connection ``queue.Queue`` in ``job.subscribers``
       under ``job.lock``.
    2. Yield a single ``job_snapshot`` event capturing cumulative state
       (URL list, per-URL status/percent, completion flag, summary). The
       UI is state-driven; the snapshot is everything a fresh subscriber
       needs to render correctly without trying to apply a historical
       event sequence (and without the duplicate-event semantics that a
       snapshot+replay design would create).
    3. If the job was already complete when the subscriber connected, the
       snapshot conveys that (``complete=True``, ``summary`` populated)
       and the generator returns immediately — no point keeping the
       connection open.
    4. Otherwise, live-stream events from the per-connection queue until
       ``job_completed`` or the client disconnects.

    The ``finally`` block removes this subscriber on generator close so
    dead subscribers don't leak (uvicorn cancels the task on client
    disconnect).
    """
    job = JOBS.get(job_id)
    if job is None:
        # get_events checks first, but be defensive.
        return
    sub_queue: "queue.Queue[dict]" = queue.Queue(maxsize=128)
    with job.lock:
        job.subscribers.append(sub_queue)
    try:
        yield f"data: {json.dumps(_build_snapshot(job))}\n\n"
        if job.completed:
            return
        last_keepalive = time.monotonic()
        while True:
            try:
                event = await asyncio.to_thread(sub_queue.get, True, 1.0)
            except queue.Empty:
                now = time.monotonic()
                if now - last_keepalive >= 30:
                    yield ": keepalive\n\n"
                    last_keepalive = now
                continue
            yield f"data: {json.dumps(event)}\n\n"
            last_keepalive = time.monotonic()
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
    finally:
        with job.lock:
            try:
                job.subscribers.remove(sub_queue)
            except ValueError:
                pass
            remaining = len(job.subscribers)
        if job.completed and remaining == 0:
            _cleanup_thumb_dir(job)


@app.get("/jobs/{job_id}/events")
async def get_events(job_id: str, _csrf: str = Depends(_require_csrf)) -> StreamingResponse:  # pylint: disable=unused-argument
    """Stream SSE events for a job."""
    if job_id not in JOBS:
        raise HTTPException(404, f"unknown job_id: {job_id}")
    return StreamingResponse(
        _events_iter(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, _csrf: str = Depends(_require_csrf)) -> dict:  # pylint: disable=unused-argument
    """Cancel a job: set flag and cancel any not-yet-started futures.

    v1.8: the executor is process-wide and shared with other jobs, so we
    can't shut it down here. Instead, set ``job.cancelled`` (which the
    progress hook and ``_run_one`` honor) and best-effort ``cancel()`` each
    pending future to free a worker slot for other submissions. Running
    futures will discover ``job.cancelled`` on their next progress tick.
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job_id: {job_id}")
    job.cancelled = True
    for fut in job.futures:
        fut.cancel()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Browser presence + auto-shutdown
#
# The server's lifetime is tied to the browser windows viewing it: the SPA
# holds one SSE connection to GET /presence per tab, and a watchdog thread
# (started by main() unless disabled) exits the server once every window has
# been closed for a grace period AND no downloads are running. Without this,
# closing the browser left uvicorn (or the whole .app) running forever and
# the next launch died on "address already in use".
# ---------------------------------------------------------------------------

# Seconds all browsers must stay disconnected before shutdown. Must comfortably
# exceed EventSource's auto-reconnect delay (~3s) so reloads, SPA navigations,
# and dev-server restarts never kill the server.
_SHUTDOWN_GRACE_SECONDS = 10.0


@dataclass
class _Presence:
    """Connected-browser bookkeeping for the auto-shutdown watchdog.

    ``ever_connected`` arms the watchdog: a ``--no-browser`` launch idles
    forever until a browser actually connects once. ``last_disconnect`` is
    ``time.monotonic()`` at the moment the count last hit zero — on macOS the
    monotonic clock pauses during sleep, so a closed laptop doesn't burn
    through the grace period.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    connected: int = 0
    ever_connected: bool = False
    last_disconnect: float = 0.0


_PRESENCE = _Presence()


def _presence_reset() -> None:
    """Fresh presence state. Called by main() so relaunches (and tests that
    invoke main()) never inherit an armed watchdog from earlier activity."""
    global _PRESENCE  # pylint: disable=global-statement
    _PRESENCE = _Presence()


def _presence_connect() -> None:
    with _PRESENCE.lock:
        _PRESENCE.connected += 1
        _PRESENCE.ever_connected = True


def _presence_disconnect() -> None:
    with _PRESENCE.lock:
        _PRESENCE.connected = max(0, _PRESENCE.connected - 1)
        if _PRESENCE.connected == 0:
            _PRESENCE.last_disconnect = time.monotonic()


def _jobs_active() -> bool:
    """True while any download job hasn't reached job_completed."""
    return any(not job.completed for job in JOBS.values())


def _should_auto_shutdown(now: float | None = None) -> bool:
    """Decision seam for the watchdog: shut down only when a browser has
    connected at least once, none are connected now, the grace period has
    fully elapsed, and no downloads are in flight (closing the browser
    mid-download lets the download finish, then exits)."""
    if now is None:
        now = time.monotonic()
    with _PRESENCE.lock:
        if not _PRESENCE.ever_connected or _PRESENCE.connected > 0:
            return False
        idle = now - _PRESENCE.last_disconnect
    if idle < _SHUTDOWN_GRACE_SECONDS:
        return False
    return not _jobs_active()


async def _presence_iter():
    """SSE generator whose open connection *is* the signal — no payload
    matters. Periodic keepalives flush through dead TCP connections (e.g.
    after system sleep) so the disconnect is noticed promptly."""
    _presence_connect()
    try:
        yield 'data: {"type": "presence"}\n\n'
        while True:
            await asyncio.sleep(15.0)
            yield ": keepalive\n\n"
    finally:
        _presence_disconnect()


@app.get("/presence")
async def presence(_csrf: str = Depends(_require_csrf)) -> StreamingResponse:  # pylint: disable=unused-argument
    """Browser-presence stream. Each open UI tab holds one of these; the
    auto-shutdown watchdog exits the server when all of them close."""
    return StreamingResponse(
        _presence_iter(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _shutdown_watchdog(
    stop: threading.Event,
    trigger: Callable[[], None],
    interval: float = 1.0,
) -> None:
    """Poll the shutdown decision until it fires or ``stop`` is set.

    ``stop`` is set by main() when the server loop returns, so stray watchdog
    threads (e.g. from tests that stub the server) can't outlive their launch
    and signal an unrelated process state.
    """
    while not stop.wait(interval):
        if _should_auto_shutdown():
            print(
                "audio-dl-ui: no browser connected for "
                f"{int(_SHUTDOWN_GRACE_SECONDS)}s and no active downloads — "
                "shutting down. Relaunch audio-dl-ui (or pass "
                "--no-auto-shutdown) to keep the server running."
            )
            trigger()
            return


def _auto_shutdown_enabled(no_auto_shutdown: bool, allow_remote: bool) -> bool:
    """Auto-shutdown is on by default for the local-app use case, off when:

    - ``--no-auto-shutdown`` asks for a long-lived server explicitly;
    - ``--allow-remote`` implies a shared/LAN server whose lifetime shouldn't
      track any single client's flaky connection;
    - dev mode (``AUDIO_DL_DEV=1``), where the Vite frontend restarts freely
      and the backend should stay up.
    """
    return not (no_auto_shutdown or allow_remote or _DEV_MODE)


@app.get("/jobs/{job_id}/thumb/{url_idx}.jpg")
async def get_thumbnail(
    job_id: str,
    url_idx: int,
    _csrf: str = Depends(_require_csrf),  # pylint: disable=unused-argument
) -> FileResponse:
    """Serve a per-URL thumbnail from the job-scoped temp dir.

    CSRF-guarded via ?token=... query param (image tags can't send custom
    headers). Returns 404 if job unknown, url_idx out of range, or thumb
    not yet on disk.
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"unknown job_id: {job_id}")
    if url_idx < 0 or url_idx >= len(job.url_states):
        raise HTTPException(404, "url_idx out of range")
    path = os.path.join(_thumb_dir(job_id), f"{url_idx}.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "thumbnail not ready")
    return FileResponse(path, media_type="image/jpeg")


class RevealRequest(BaseModel):
    """Request body for POST /reveal."""
    path: str


def _reveal_allowed_roots() -> set[Path]:
    """Return the set of directories that ``/reveal`` is allowed to expose.

    v1.8: history items live in the browser's localStorage and outlive the
    JOBS entries that produced them, so the previous "path must appear in
    some live JOBS[*].url_states[*].paths" gate no longer works. Instead,
    the allow-list is directory-based:

    * the server-wide default output dir (set at launch via --output-dir)
    * any per-job output_dir override still resident in JOBS

    Snapshotting JOBS first — concurrent POST /jobs can mutate it
    mid-iteration and raise RuntimeError otherwise.
    """
    roots: set[Path] = set()
    default_dir = getattr(app.state, "default_output_dir", None)
    if default_dir:
        try:
            roots.add(Path(default_dir).expanduser().resolve(strict=False))
        except (OSError, RuntimeError):
            pass
    for job in list(JOBS.values()):
        try:
            roots.add(Path(job.output_dir).expanduser().resolve(strict=False))
        except (OSError, RuntimeError):
            continue
    return roots


@app.post("/reveal")
async def reveal(req: RevealRequest, _csrf: str = Depends(_require_csrf)) -> dict:  # pylint: disable=unused-argument
    """Open the file in Finder.

    v1.8: validate by path canonicalization + directory allow-list instead
    of a live JOBS lookup. ``Path.resolve()`` collapses ``..`` so traversal
    attempts (``<allowed>/../../../etc/passwd``) end up outside any allowed
    root and are rejected with 403. Paths that don't exist on disk are
    rejected with 404 to distinguish the failure modes.
    """
    try:
        resolved = Path(req.path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise HTTPException(400, f"Invalid path: {e}") from e

    if not resolved.exists():
        raise HTTPException(404, "Path does not exist on disk.")

    roots = _reveal_allowed_roots()
    if not any(resolved.is_relative_to(root) for root in roots):
        raise HTTPException(403, "Path is not inside an allowed output directory.")

    subprocess.run(["open", "-R", str(resolved)], check=False)
    return {"ok": True}


@app.get("/api/version")
def api_version() -> dict:
    """Version + build identifier the front-end uses to sanity-check the backend."""
    return {
        "version": __version__,
        "build": _BUILD_ID,
    }


@app.get("/api/settings/defaults")
def api_settings_defaults() -> dict:
    """Launch-time settings the front-end needs to render correctly."""
    return {
        "output_dir": str(getattr(app.state, "default_output_dir", "")),
        "max_parallel": getattr(app.state, "max_parallel", 4),
        "available_formats": list(ALL_FORMATS),
    }


@app.get("/api/csrf")
def api_csrf(request: Request) -> dict:
    """Dev-only: hand the CSRF token to the Vite dev server.
    Refuses if not in dev mode or if the request is not from loopback."""
    if not _DEV_MODE:
        raise HTTPException(status_code=404)
    client_host = (request.client.host if request.client else "") or ""
    if client_host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=404)
    return {"token": getattr(app.state, "csrf_token", "")}


@app.get("/thumbs/{thumb_id}.jpg")
def serve_thumb(thumb_id: str) -> Response:
    """Serve a cached thumbnail by stable SHA-1 ID."""
    # Validate the ID format strictly to prevent path traversal.
    if not (len(thumb_id) == 40 and all(c in "0123456789abcdef" for c in thumb_id)):
        raise HTTPException(status_code=400, detail="invalid thumb_id")
    path = _thumb_cache_dir() / f"{thumb_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404)
    return Response(content=path.read_bytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ---------------------------------------------------------------------------
# Dependency pre-flight (GUI-aware)
# ---------------------------------------------------------------------------

def _show_macos_dialog(title: str, message: str) -> bool:
    """Display a native macOS dialog via ``osascript``.

    Used by the ``.app`` bundle path where stderr is invisible — without this
    the user double-clicks the app and sees nothing on missing dependencies.
    Returns True if the dialog was displayed; False on any failure (we're
    about to ``sys.exit`` anyway so the caller has nothing useful to do with
    the error).
    """
    if sys.platform != "darwin":
        return False

    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        f'display dialog "{_esc(message)}" with title "{_esc(title)}" '
        f'buttons {{"OK"}} default button "OK" with icon stop'
    )
    try:
        result = subprocess.run(["osascript", "-e", script], check=False, timeout=60)
        # osascript returns nonzero when AppleScript rejects the source (syntax
        # error, unknown keyword on an old macOS, etc.). Treat nonzero as a
        # failed display so the caller falls through to the stderr path.
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _thumb_cache_dir() -> Path:
    """Return the on-disk thumbnail cache directory, creating it if needed."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "audio-dl"
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        fallback = Path.home() / ".local" / "share"
        base = Path(xdg_data_home or fallback) / "audio-dl"
    cache = base / "thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _compute_thumb_id(url: str) -> str:
    """Stable SHA-1 hex for a source URL — used as the thumbnail cache key."""
    return hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()


def _persist_thumb(url: str, jpeg_bytes: bytes) -> str:
    """Write jpeg_bytes to the thumb cache keyed by URL. First write wins.
    Returns the thumb_id. Safe to call repeatedly."""
    thumb_id = _compute_thumb_id(url)
    path = _thumb_cache_dir() / f"{thumb_id}.jpg"
    if not path.exists():
        path.write_bytes(jpeg_bytes)
    return thumb_id


def _selfcheck_problems() -> list[str]:
    """Return problem lines for a frozen-bundle self-check (empty == healthy).

    Beyond :func:`_check_dependencies` (ffmpeg + yt-dlp), this asserts the
    pieces the DOWNLOAD path needs that a server-bind smoke test can't see:

    - **mutagen** — yt-dlp embeds m4a/mp3 cover art via mutagen when it's
      importable, else falls back to an ``ffprobe``+``ffmpeg`` path. The
      bundle ships ``ffmpeg`` but NOT ``ffprobe``, so a bundle without
      mutagen fails EVERY download at postprocess. This is the v2.1.2
      regression; the release smoke test must catch a recurrence.
    - **web UI** — an empty ``static/`` means the bundle serves no app.

    Pure function: no stdout/stderr, no ``sys.exit`` — same contract as
    :func:`_check_dependencies`, so the GUI/smoke-test callers decide how to
    surface failures.
    """
    problems = list(_check_dependencies())
    if importlib.util.find_spec("mutagen") is None:
        problems.append(
            "mutagen is not available — yt-dlp needs it to embed cover art. "
            "The bundle ships ffmpeg but not ffprobe, so without mutagen every "
            "download fails at postprocess. Add it to the [app] extra and the "
            "PyInstaller spec hiddenimports."
        )
    index = os.path.join(_STATIC_DIR, "index.html")
    if not os.path.isfile(index):
        problems.append(f"web UI bundle missing: {index} not found (run scripts/build-web.sh).")
    return problems


def _check_dependencies_gui() -> None:
    """Pre-flight dep check that surfaces failures sensibly for both shells and the ``.app``.

    Terminal users get CLI-parity stderr output. The bundled ``.app`` (no TTY)
    gets a native macOS dialog so a missing ffmpeg doesn't manifest as silent
    failure. If the dialog itself can't be shown (osascript missing on a
    Frankenstein system, syntax-rejected on a future macOS) we fall through
    to the stderr path — at least system-log capture will record the cause.
    Always exits non-zero on missing deps.
    """
    problems = _check_dependencies()
    if not problems:
        return

    no_tty = not (sys.stderr and sys.stderr.isatty())
    if no_tty and sys.platform == "darwin":
        message = "audio-dl can't start:\n\n" + "\n".join(problems)
        if _show_macos_dialog("audio-dl — missing dependency", message):
            sys.exit(1)
        # Dialog refused — fall through to stderr so the failure is at least
        # captured somewhere a developer can find it.

    for line in problems:
        print(line if line.startswith(" ") else f"ERROR: {line}", file=sys.stderr)
    sys.exit(1)


def _port_bind_error(host: str, port: int) -> str | None:
    """Pre-flight the server bind; return an error message if the port is taken.

    ``uvicorn.run`` binds the port itself, but by the time it raises the 0.8s
    browser-open timer has already fired and a Finder-launched user is staring
    at a broken tab that carries the *dead* instance's CSRF token while the old
    server keeps the port (issue #44). We probe the bind here — before the
    timer starts — so we can fail loudly and skip opening the browser.

    We set ``SO_REUSEADDR`` to match uvicorn's own socket options, so a stale
    ``TIME_WAIT`` socket doesn't produce a false "already running". A currently
    *listening* socket (a live prior instance) still yields ``EADDRINUSE`` on
    every platform, which is exactly the case we want to catch. Each probe
    socket is closed immediately, leaving the port free for uvicorn; a tiny
    TOCTOU window remains (another process could grab it in between), which
    uvicorn's own ``OSError`` handler in :func:`main` still covers.

    A host like ``localhost`` can resolve to BOTH ``::1`` and ``127.0.0.1``;
    asyncio/uvicorn binds a socket for EVERY address ``getaddrinfo`` returns.
    So we must probe them ALL and fail if ANY is taken — otherwise a prior
    instance holding just one family (e.g. IPv4) would slip past a probe that
    only tried the other (issue #44). We set ``IPV6_V6ONLY`` on the IPv6 probe
    (mirroring asyncio) so a ``::`` bind doesn't also cover IPv4 and mask a
    held v4 address.

    Returns ``None`` only when EVERY resolved address is bindable, else a
    human-readable reason for the first address that fails.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return f"cannot resolve host {host!r}: {exc}"

    seen: set = set()
    for family, socktype, proto, _canonname, sockaddr in infos:
        if sockaddr in seen:  # dedup identical (addr, port) tuples
            continue
        seen.add(sockaddr)
        sock = socket.socket(family, socktype, proto)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind(sockaddr)
        except OSError as exc:
            return f"cannot bind {host}:{port} — {exc}"
        finally:
            sock.close()

    return None  # every resolved address is bindable


def _preflight_or_exit(host: str, port: int) -> None:
    """Pre-flight the port bind and abort loudly (no browser tab) if it's taken.

    Called BEFORE ``main()`` arms the browser-open timer: if a prior audio-dl
    instance already holds the port, ``uvicorn.run`` would exit on bind but the
    timer would have opened a broken tab carrying this dead instance's CSRF
    token (issue #44). On failure we surface the reason the same way the
    missing-dependency pre-flight does — native dialog on a Finder-launched
    ``.app`` (no TTY), stderr elsewhere — then ``sys.exit(1)``. Returns normally
    when the port is bindable.
    """
    bind_error = _port_bind_error(host, port)
    if bind_error is None:
        return

    message = (
        "audio-dl can't start — the port is already in use:\n\n"
        f"{bind_error}\n\n"
        "audio-dl may already be running. Use the existing window, or quit "
        "the other instance before relaunching."
    )
    no_tty = not (sys.stderr and sys.stderr.isatty())
    if no_tty and sys.platform == "darwin" and _show_macos_dialog(
        "audio-dl — already running", message
    ):
        sys.exit(1)
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():  # pylint: disable=too-many-statements
    """Parse args and run the uvicorn server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--output-dir",
        default=os.path.expanduser("~/Downloads/audio-dl"),
        help="Default output directory shown in the form (default: ~/Downloads/audio-dl).",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser.")
    parser.add_argument(
        "--no-auto-shutdown", action="store_true",
        help="Keep the server running after every browser window closes. "
             "By default the server exits ~10s after the last UI tab "
             "disconnects (once downloads finish). Implied by --allow-remote "
             "and by dev mode (AUDIO_DL_DEV=1).",
    )
    parser.add_argument(
        "--selfcheck", action="store_true",
        help="Verify the bundle has everything downloads need (ffmpeg, yt-dlp, "
             "mutagen, web UI), print the result, and exit 0/1. Used by the "
             "release smoke test to catch packaging gaps before publish.",
    )
    parser.add_argument(
        "--allow-remote", action="store_true",
        help="Allow binding to non-loopback hosts (LAN/public). Default refuses for safety.",
    )
    parser.add_argument(
        "--no-related", action="store_true",
        help="Disable related-content discovery (no extra YouTube/SoundCloud "
             "queries or thumbnail fetches during downloads).",
    )
    def _max_parallel(value: str) -> int:
        try:
            n = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"--max-parallel expects an integer, got {value!r}"
            ) from exc
        if not 1 <= n <= 64:
            raise argparse.ArgumentTypeError(
                f"--max-parallel must be between 1 and 64, got {n}"
            )
        return n

    parser.add_argument(
        "--max-parallel", type=_max_parallel, default=4,
        help="Max URLs downloading simultaneously across all submissions "
             "(1-64, default: 4).",
    )
    args = parser.parse_args()

    # Self-check and exit (no server). Runs before any host/CSRF setup so it's
    # a pure "is this bundle healthy" probe for the release smoke test.
    if args.selfcheck:
        problems = _selfcheck_problems()
        if problems:
            print("selfcheck FAILED:", file=sys.stderr)
            for line in problems:
                print(f"  - {line}", file=sys.stderr)
            sys.exit(1)
        print("selfcheck OK: ffmpeg, yt-dlp, mutagen, and web UI all present.")
        sys.exit(0)

    # Refuse non-loopback bind without explicit opt-in.
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print(
            f"ERROR: --host {args.host!r} is not loopback. Add --allow-remote to bind to "
            "non-loopback addresses (LAN/public). Loopback: 127.0.0.1, localhost, ::1.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Generate per-launch CSRF token.
    app.state.csrf_token = secrets.token_urlsafe(32)

    _check_dependencies_gui()

    # Stash the default output dir for the index page to read.
    app.state.default_output_dir = args.output_dir

    # Stash max_parallel for the API to read.
    app.state.max_parallel = args.max_parallel

    # Related-content discovery kill switch (default on; see spec decision #8).
    app.state.related_enabled = not args.no_related

    # v1.8: initialize the process-wide download worker pool. URLs from
    # every submission share this one executor, so --max-parallel is a
    # single global cap rather than a per-submission setting.
    global _GLOBAL_EXECUTOR  # pylint: disable=global-statement
    _GLOBAL_EXECUTOR = ThreadPoolExecutor(
        max_workers=args.max_parallel, thread_name_prefix="audio-dl-worker"
    )

    # Pre-flight the port bind BEFORE arming the browser timer. If a previous
    # audio-dl instance already holds the port, uvicorn.run below would exit on
    # bind — but the 0.8s timer would have already opened a broken tab carrying
    # this dead instance's CSRF token (issue #44). _preflight_or_exit fails
    # loudly here instead (dialog on a Finder .app, stderr elsewhere).
    _preflight_or_exit(args.host, args.port)

    if not args.no_browser:
        # 0.0.0.0 / :: are bind-all addresses, not routable from a browser.
        # Open the browser to the loopback address instead.
        browser_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        launch_url = f"http://{browser_host}:{args.port}/?token={app.state.csrf_token}"
        threading.Timer(0.8, lambda: webbrowser.open(launch_url)).start()

    # Tie server lifetime to the browser: once a UI tab has connected, exit
    # when they've all been closed for the grace period and downloads are
    # done. SIGINT rides uvicorn's own signal handler, so shutdown is exactly
    # as graceful as Ctrl-C. The stop event kills the watchdog when the
    # server loop returns (tests stub uvicorn.run, so without it stray
    # watchdog threads would accumulate across main() calls).
    _presence_reset()
    watchdog_stop = threading.Event()
    if _auto_shutdown_enabled(args.no_auto_shutdown, args.allow_remote):
        threading.Thread(
            target=_shutdown_watchdog,
            args=(watchdog_stop, lambda: signal.raise_signal(signal.SIGINT)),
            daemon=True,
            name="audio-dl-shutdown-watchdog",
        ).start()

    global uvicorn  # pylint: disable=global-statement
    if uvicorn is None:
        import uvicorn as _uvicorn  # pylint: disable=import-outside-toplevel
        uvicorn = _uvicorn
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except OSError as e:
        print(f"ERROR: cannot bind {args.host}:{args.port} — {e}")
        sys.exit(1)
    finally:
        watchdog_stop.set()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Static files — must be last so all API routes take priority
# ---------------------------------------------------------------------------

_STATIC_DIR = str(_importlib_files("audio_dl_ui") / "static")


def _host_header_is_loopback(host_header: str) -> bool:
    """True if the ``Host`` header names a loopback address (port ignored).

    Guards CSRF-token injection against DNS rebinding: an attacker hostname
    that resolves to 127.0.0.1 yields a loopback *client* address but carries
    its own (non-loopback) ``Host`` header, so it must not receive the token.
    """
    host = (host_header or "").strip()
    if not host:
        return False
    if host.startswith("["):  # bracketed IPv6, e.g. "[::1]:8000"
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:  # "host:port" (bare IPv6 always uses brackets)
        host = host.rsplit(":", 1)[0]
    return host in _LOOPBACK_HOSTS


def _index_html_with_token(index_path: Path, token: str) -> str:
    """Read index.html and inject ``<meta name="csrf-token">`` into <head>.

    The token is ``secrets.token_urlsafe`` output (``[A-Za-z0-9_-]``), so it
    carries no HTML-special characters.
    """
    html = index_path.read_text(encoding="utf-8")
    meta = f'<meta name="csrf-token" content="{token}">'
    if "</head>" in html:
        return html.replace("</head>", f"{meta}</head>", 1)
    return meta + html


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_or_static(full_path: str, request: Request) -> Response:
    """Serve static files when they exist; fall back to index.html for SPA routing.

    Path-traversal guard: rejects any path containing ``..`` segments or
    percent-encoded slashes (``%2F`` / ``%2f``) that could escape the static root.

    When serving index.html to a same-origin loopback client, inject the
    per-launch CSRF token so bare URLs (bookmarks, address-bar autocomplete)
    and tabs that outlive an app relaunch can POST without a ``?token=`` param.
    Gated on BOTH a loopback client address AND a loopback ``Host`` header so a
    DNS-rebinding page (loopback client, attacker Host) never reads the token.
    """
    if ".." in full_path or "%2F" in full_path or "%2f" in full_path:
        raise HTTPException(status_code=404)
    static_root = Path(_STATIC_DIR).resolve()
    candidate = (static_root / full_path).resolve()
    if not candidate.is_relative_to(static_root):
        raise HTTPException(status_code=404)
    if full_path and candidate.is_file():
        target = candidate
    else:
        target = static_root / "index.html"
    if target.name == "index.html" and target.is_file():
        token = getattr(request.app.state, "csrf_token", "") or ""
        client_host = (request.client.host if request.client else "") or ""
        if (
            token
            and client_host in _LOOPBACK_HOSTS
            and _host_header_is_loopback(request.headers.get("host", ""))
        ):
            return HTMLResponse(_index_html_with_token(target, token))
    return FileResponse(str(target))
