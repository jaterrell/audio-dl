# Rich Job Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the running-job row list in the web UI with a vertical stack of full-width cards, one per URL, each showing live speed/ETA/bytes, track metadata, a server-proxied thumbnail, and a filtered yt-dlp log tail.

**Architecture:** All changes land in `audio_dl_ui.py` plus a small `logger=` plumbing pass-through in `audio_dl.py`. Pure functions (filter, thumbnail-URL picker) drop in first under TDD, then `UrlState` gains new fields, then the `_YDLLogger` and `_run_one` flow wire phase + metadata + log + thumbnail-fetch into the existing SSE broadcast (`_emit`). UI changes happen in the three `_INDEX_*` constants (CSS, HTML body, JS) and the per-job thumbnail proxy endpoint sits next to `/jobs/{id}/events`.

**Tech Stack:** Python 3.10+, FastAPI, yt-dlp, httpx (already a uvicorn dep), pytest, vanilla JS. No new runtime deps.

**Spec:** [docs/superpowers/specs/2026-05-16-rich-job-cards-design.md](../specs/2026-05-16-rich-job-cards-design.md)

---

## File map

- **Modify** [audio_dl.py](../../../audio_dl.py): add `logger=` parameter to `_build_ydl_opts` and `download_media` (single pass-through, no behavior change for CLI).
- **Modify** [audio_dl_ui.py](../../../audio_dl_ui.py): new pure functions, extend `UrlState`, add `_YDLLogger`, extend progress hook + `_run_one`, add thumbnail fetcher + endpoint, extend `_build_snapshot`, rewrite UI `_INDEX_CSS_BASE`/`_INDEX_HTML_BODY`/`_INDEX_JS` row-template region to card markup.
- **Modify** [test_audio_dl.py](../../../test_audio_dl.py): cover the `logger=` pass-through in `_build_ydl_opts`.
- **Modify** [test_audio_dl_ui.py](../../../test_audio_dl_ui.py): new tests for each piece below.
- **Modify** [CHANGELOG.md](../../../CHANGELOG.md), [audio_dl.py](../../../audio_dl.py) `__version__`, [pyproject.toml](../../../pyproject.toml) `version`: final release-bump task.

No new files. No new runtime deps.

---

## Task 1: Pure filter — `_should_keep_log`

**Files:**
- Modify: `audio_dl_ui.py` (new pure function, near `_emit`)
- Modify: `test_audio_dl_ui.py` (new `TestShouldKeepLog` class)

- [ ] **Step 1: Write the failing tests**

Add to `test_audio_dl_ui.py`:

```python
from audio_dl_ui import _should_keep_log


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
    ])
    def test_filter(self, level, text, expected):
        assert _should_keep_log(level, text) is expected
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestShouldKeepLog -v
```
Expected: ImportError (`_should_keep_log` not defined).

- [ ] **Step 3: Write minimal implementation**

Add to `audio_dl_ui.py`, just above `def _emit`:

```python
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
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestShouldKeepLog -v
```
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): _should_keep_log pure filter for yt-dlp log lines"
```

---

## Task 2: Pure thumbnail picker — `_pick_thumbnail_url`

**Files:**
- Modify: `audio_dl_ui.py`
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
from audio_dl_ui import _pick_thumbnail_url


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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestPickThumbnailUrl -v
```
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

Add to `audio_dl_ui.py` near `_should_keep_log`:

```python
def _pick_thumbnail_url(info: dict) -> str | None:
    """Pick a reasonable thumbnail URL from a yt-dlp info dict.

    Prefers the largest thumbnail with width <= 480 (good for our 120px
    card thumbs without retina-blur). Falls back to the smallest width
    if none are <= 480, then the singular ``thumbnail`` field, then None.
    """
    thumbs = info.get("thumbnails") or []
    sized = [t for t in thumbs if isinstance(t.get("width"), int)]
    if sized:
        small = [t for t in sized if t["width"] <= 480]
        if small:
            chosen = max(small, key=lambda t: t["width"])
        else:
            chosen = min(sized, key=lambda t: t["width"])
        return chosen.get("url")
    if thumbs:
        return thumbs[0].get("url")
    return info.get("thumbnail") or None
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestPickThumbnailUrl -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): _pick_thumbnail_url chooses best info-dict thumbnail"
```

---

## Task 3: Extend `UrlState` with new fields

**Files:**
- Modify: `audio_dl_ui.py:62-76` (UrlState dataclass)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
import collections
from audio_dl_ui import UrlState


class TestUrlStateNewFields:
    def test_defaults(self):
        s = UrlState(url="https://example/x")
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
        a = UrlState(url="https://example/a")
        b = UrlState(url="https://example/b")
        a.log.append({"ts": 1.0, "level": "info", "text": "hello"})
        assert len(b.log) == 0
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestUrlStateNewFields -v
```
Expected: AttributeError on `title`.

- [ ] **Step 3: Extend the dataclass**

In `audio_dl_ui.py`, find the `UrlState` dataclass (around line 62) and replace its body with:

```python
@dataclass
class UrlState:  # pylint: disable=too-many-instance-attributes
    """Per-URL download state within a job, updated by progress hooks."""

    url: str
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
    # v1.X — rich card fields
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
```

Add `import collections` to the top-of-file imports — the existing import block in `audio_dl_ui.py:18-33` does not include it.

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestUrlStateNewFields -v
pytest test_audio_dl_ui.py -v   # all existing tests still green
```
Expected: 2 passed (new) + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): UrlState gains title/uploader/duration/phase/log/thumbnail_ready"
```

---

## Task 4: `_YDLLogger` class + `_make_url_logger` factory

**Files:**
- Modify: `audio_dl_ui.py`
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
from audio_dl_ui import _make_url_logger, JobState
import queue


def _fresh_job(url: str = "https://example/x") -> JobState:
    job = JobState(
        id="j1", media_format="mp3", output_dir="/tmp",
        playlist=False, force=False, fragments=4, jobs=1,
        url_states={url: UrlState(url=url)},
    )
    return job


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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestYDLLogger -v
```
Expected: ImportError on `_make_url_logger`.

- [ ] **Step 3: Implement the logger**

Add to `audio_dl_ui.py` after `_should_keep_log`:

```python
class _YDLLogger:
    """yt-dlp-compatible logger that routes filtered lines into a URL's
    state deque and broadcasts each kept line as a ``url_log`` SSE event.

    yt-dlp invokes ``.debug``, ``.info``, ``.warning``, ``.error`` with
    a single string (sometimes an exception). We coerce, filter, append,
    emit. Never raises — a logger that crashes would break the download.
    """

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
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestYDLLogger -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): _YDLLogger emits url_log SSE events + appends to bounded deque"
```

---

## Task 5: Add `logger=` to `_build_ydl_opts` and `download_media` in `audio_dl.py`

**Files:**
- Modify: `audio_dl.py:211-304` (`_build_ydl_opts`) and `audio_dl.py:316+` (`download_media`)
- Modify: `test_audio_dl.py` (new test case in the existing `_build_ydl_opts` test class)

- [ ] **Step 1: Write the failing test**

Find the existing `_build_ydl_opts` test class in `test_audio_dl.py` and add:

```python
def test_logger_passed_through(self):
    class FakeLogger:
        pass
    fake = FakeLogger()
    opts = _build_ydl_opts(
        media_format="mp3", output_dir=".", playlist=False, force=False,
        concurrent_fragments=4, platform="youtube",
        logger=fake,
    )
    assert opts["logger"] is fake

def test_logger_omitted_when_none(self):
    opts = _build_ydl_opts(
        media_format="mp3", output_dir=".", playlist=False, force=False,
        concurrent_fragments=4, platform="youtube",
    )
    assert "logger" not in opts
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl.py -k logger -v
```
Expected: TypeError (`unexpected keyword argument 'logger'`).

- [ ] **Step 3: Add the parameter**

In `audio_dl.py`, change `_build_ydl_opts` signature to accept `logger=None`:

```python
def _build_ydl_opts(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches
    *,
    media_format: str,
    output_dir: str,
    playlist: bool,
    force: bool,
    concurrent_fragments: int,
    platform: str,
    sc_auth: str | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
    progress_hooks: list[Callable[[dict], None]] | None = None,
    ffmpeg_location: str | None = None,
    logger: object | None = None,
) -> dict:
```

In the `if progress_hooks:` block at the end, add right after it:

```python
if logger is not None:
    opts["logger"] = logger
```

Then in `download_media`, add the same parameter and pass it through. Find the `def download_media(...)` signature (around line 316) and add `logger=None` to the kwargs:

```python
def download_media(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    url: str,
    media_format: str = "mp3",
    output_dir: str = ".",
    sc_auth: str | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
    playlist: bool = False,
    force: bool = False,
    concurrent_fragments: int = 4,
    progress_hooks: list[Callable[[dict], None]] | None = None,
    logger: object | None = None,
) -> list[str]:
```

And in its `_build_ydl_opts(` call, pass `logger=logger`.

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl.py -k logger -v
pytest test_audio_dl.py -v   # full file
```
Expected: 2 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl.py test_audio_dl.py
git commit -m "feat(cli): plumb optional logger= through download_media to yt-dlp"
```

---

## Task 6: Wire logger into `_run_one`

**Files:**
- Modify: `audio_dl_ui.py:233-292` (`_run_one`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import patch


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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest test_audio_dl_ui.py::TestRunOneWiresLogger -v
```
Expected: AssertionError (`captured["logger"] is None`).

- [ ] **Step 3: Wire it**

In `audio_dl_ui.py` `_run_one`, find the `download_media(...)` call and add `logger=_make_url_logger(job, url_state)`:

```python
        paths = download_media(
            clean,
            media_format=job.media_format,
            output_dir=job.output_dir,
            playlist=job.playlist,
            force=job.force,
            concurrent_fragments=job.fragments,
            progress_hooks=[hook],
            logger=_make_url_logger(job, url_state),
        )
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestRunOneWiresLogger -v
pytest test_audio_dl_ui.py -v
```
Expected: 1 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): _run_one wires a per-URL _YDLLogger into download_media"
```

---

## Task 7: Capture metadata + emit first `url_metadata`

**Files:**
- Modify: `audio_dl_ui.py:187-230` (`_make_progress_hook`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing test**

```python
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

        meta = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "url_metadata"]
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

        meta = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "url_metadata"]
        assert len(meta) == 1
        assert meta[0]["title"] is None
        assert meta[0]["uploader"] is None
        assert meta[0]["duration"] is None
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestUrlMetadataEvent -v
```
Expected: failures — no `url_metadata` events.

- [ ] **Step 3: Extend the progress hook**

In `audio_dl_ui.py` `_make_progress_hook`, modify the body to capture and emit metadata. Replace the existing hook function with:

```python
def _make_progress_hook(job: JobState, url_state: UrlState) -> Callable[[dict], None]:
    """
    Build a yt-dlp progress hook bound to one URL.

    - Raises `_Cancelled` when `job.cancelled` is set.
    - Throttles progress emissions to ~5/sec/URL.
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
            _emit(job, {
                "type": "url_metadata",
                "job_id": job.id,
                "url": url_state.url,
                "title": url_state.title,
                "uploader": url_state.uploader,
                "duration": url_state.duration,
                "thumbnail_ready": False,
            })

        if d.get("status") != "downloading":
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
        })

    return hook
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestUrlMetadataEvent -v
pytest test_audio_dl_ui.py -v
```
Expected: 3 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): emit url_metadata SSE event from first info-dict-bearing hook tick"
```

---

## Task 8: Add `phase` field to `progress` events

**Files:**
- Modify: `audio_dl_ui.py` (`_make_progress_hook`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestPhaseField -v
```
Expected: failures — `phase` field missing from event.

- [ ] **Step 3: Set + emit `phase`**

In `_make_progress_hook` from Task 7, two changes:

1. After the `info_dict` block, before the `status != "downloading"` early-return, handle the `finished` status (which means download is done; postprocess starts now). The hook receives `status: "finished"` once per URL.

Replace the section starting from `if d.get("status") != "downloading":` with:

```python
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
```

2. Set `phase = "downloading"` and include it in the emitted event:

```python
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
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestPhaseField -v
pytest test_audio_dl_ui.py -v
```
Expected: 2 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): progress event gains phase=downloading|postprocessing"
```

---

## Task 9: Phase transitions in `_run_one`

**Files:**
- Modify: `audio_dl_ui.py:233-292` (`_run_one`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing test**

```python
class TestRunOnePhaseTransitions:
    def test_phases_resolving_then_complete(self):
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
        # When sanitize raises, phase is still "resolving" then transitions to "failed".
        # Easier to assert: resolving is set as the first phase.
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
```

Don't forget `from audio_dl_ui import _run_one, JOBS` at top of the test.

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestRunOnePhaseTransitions -v
```
Expected: failures — phase is still `None`.

- [ ] **Step 3: Set phase at each transition in `_run_one`**

Add `url_state.phase = "resolving"` as the first line of the try block (before `sanitize_url`). Set `url_state.phase = "complete"` after the success path. Set `url_state.phase = "failed"` in each failure branch.

Apply this diff to `_run_one`:

```python
def _run_one(job: JobState, raw_url: str) -> None:
    """One unit of work for the executor: sanitize, download, emit events."""
    url_state = job.url_states[raw_url]

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
            media_format=job.media_format,
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
    _emit(job, {"type": "url_completed", "job_id": job.id,
                "url": raw_url, "paths": paths})
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestRunOnePhaseTransitions -v
pytest test_audio_dl_ui.py -v
```
Expected: 3 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): _run_one sets explicit phase at every transition"
```

---

## Task 10: Thumbnail fetcher

**Files:**
- Modify: `audio_dl_ui.py` (new `_thumb_dir`, `_fetch_thumbnail`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
import os
import tempfile
from unittest.mock import MagicMock


class TestThumbnailFetcher:
    def test_writes_file_on_success(self, tmp_path, monkeypatch):
        from audio_dl_ui import _fetch_thumbnail, _thumb_dir
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        # Mock httpx.get to return fake bytes
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b"\xff\xd8\xff\xe0fakejpeg"
        with patch("audio_dl_ui.httpx.get", return_value=fake_response):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is True
        expected = os.path.join(_thumb_dir("job1"), "0.jpg")
        assert os.path.exists(expected)
        with open(expected, "rb") as f:
            assert f.read() == b"\xff\xd8\xff\xe0fakejpeg"

    def test_non_200_returns_false(self, tmp_path, monkeypatch):
        from audio_dl_ui import _fetch_thumbnail
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        fake_response = MagicMock(status_code=404)
        with patch("audio_dl_ui.httpx.get", return_value=fake_response):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is False

    def test_exception_returns_false(self, tmp_path, monkeypatch):
        from audio_dl_ui import _fetch_thumbnail
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))
        with patch("audio_dl_ui.httpx.get", side_effect=Exception("boom")):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is False

    def test_atomic_write(self, tmp_path, monkeypatch):
        """Failure mid-write must not leave a partial file at the target path."""
        from audio_dl_ui import _fetch_thumbnail, _thumb_dir
        monkeypatch.setattr("audio_dl_ui._THUMB_ROOT", str(tmp_path))

        # Simulate write failure by making os.replace raise
        fake_response = MagicMock(status_code=200, content=b"x" * 100)
        with patch("audio_dl_ui.httpx.get", return_value=fake_response), \
             patch("audio_dl_ui.os.replace", side_effect=OSError("disk full")):
            ok = _fetch_thumbnail("job1", 0, "https://img.example/x.jpg")
        assert ok is False
        assert not os.path.exists(os.path.join(_thumb_dir("job1"), "0.jpg"))
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestThumbnailFetcher -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the fetcher**

Add to the top-of-file import block in `audio_dl_ui.py`:

```python
import httpx
import tempfile
```

(`os` is already imported at line 22; `httpx` and `tempfile` are NOT currently imported and must be added.)

Then add, after the other module-level helpers near `_emit`:

```python
_THUMB_ROOT = os.path.join(tempfile.gettempdir(), "audio-dl-thumbs")


def _thumb_dir(job_id: str) -> str:
    return os.path.join(_THUMB_ROOT, job_id)


def _fetch_thumbnail(job_id: str, url_idx: int, src_url: str) -> bool:
    """Fetch a thumbnail to {THUMB_ROOT}/{job_id}/{url_idx}.jpg.

    Returns True on success, False on any failure (timeout, non-200,
    write error). No retries. Never raises.
    """
    try:
        resp = httpx.get(src_url, timeout=5.0, follow_redirects=True)
        if resp.status_code != 200:
            return False
        target_dir = _thumb_dir(job_id)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"{url_idx}.jpg")
        tmp_fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=".thumb-", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(resp.content)
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
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestThumbnailFetcher -v
pytest test_audio_dl_ui.py -v
```
Expected: 4 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): _fetch_thumbnail writes job-scoped thumb file atomically"
```

---

## Task 11: Wire thumbnail fetcher into the flow

**Files:**
- Modify: `audio_dl_ui.py` (extend `_make_progress_hook`, add `url_idx` lookup)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
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
        fake_response = MagicMock(status_code=200, content=b"\xff\xd8\xff\xe0fake")
        with patch("audio_dl_ui.httpx.get", return_value=fake_response):
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
        with patch("audio_dl_ui.httpx.get", side_effect=Exception("network")):
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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestThumbnailFetcherWiring -v
```
Expected: failures — no second metadata event.

- [ ] **Step 3: Wire dispatch**

Two pieces:

(a) Add a helper to find `url_idx` from raw URL in the URL ordering. Put it near `_thumb_dir`:

```python
def _url_idx(job: JobState, raw_url: str) -> int:
    """0-based position of the URL within the job's submission order."""
    for i, u in enumerate(job.url_states.keys()):
        if u == raw_url:
            return i
    return -1
```

(b) In `_make_progress_hook`, after the existing url_metadata emit, dispatch the fetcher in a daemon thread:

Replace the existing first-metadata block in `_make_progress_hook` with:

```python
        info = d.get("info_dict") or {}
        if info and not url_state.metadata_emitted:
            url_state.title = info.get("title")
            url_state.uploader = info.get("uploader")
            url_state.duration = info.get("duration")
            url_state.metadata_emitted = True
            _emit(job, {
                "type": "url_metadata",
                "job_id": job.id,
                "url": url_state.url,
                "title": url_state.title,
                "uploader": url_state.uploader,
                "duration": url_state.duration,
                "thumbnail_ready": False,
            })
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
                        })

                threading.Thread(target=_do_fetch, daemon=True).start()
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestThumbnailFetcherWiring -v
pytest test_audio_dl_ui.py -v
```
Expected: 3 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): dispatch thumbnail fetcher on first metadata; re-emit url_metadata on success"
```

---

## Task 12: Thumbnail proxy endpoint

**Files:**
- Modify: `audio_dl_ui.py` (new `GET /jobs/{job_id}/thumb/{url_idx}.jpg` endpoint)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestThumbnailEndpoint -v
```
Expected: 404 on all (endpoint doesn't exist yet → FastAPI returns 404 for unknown route).

- [ ] **Step 3: Add the endpoint**

In `audio_dl_ui.py`, **add `FileResponse` to the existing fastapi.responses import** (line 36, currently `from fastapi.responses import HTMLResponse, StreamingResponse`):

```python
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
```

Then add the endpoint near the other endpoints (after `get_events` or `cancel_job`):

```python


@app.get("/jobs/{job_id}/thumb/{url_idx}.jpg")
async def get_thumbnail(
    job_id: str,
    url_idx: int,
    _csrf: str = Depends(_require_csrf),  # pylint: disable=unused-argument
) -> FileResponse:
    """Serve a per-URL thumbnail from the job-scoped temp dir.

    CSRF-guarded via ?token=... query param (Image tags can't send custom
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
```

If `FileResponse` is already imported, skip the import. If `Depends` isn't imported at the top of the file, add it to the FastAPI import.

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestThumbnailEndpoint -v
pytest test_audio_dl_ui.py -v
```
Expected: 5 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): GET /jobs/{id}/thumb/{idx}.jpg serves per-URL thumbs (CSRF-guarded)"
```

---

## Task 13: Extend `_build_snapshot`

**Files:**
- Modify: `audio_dl_ui.py:1967-2005` (`_build_snapshot`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest test_audio_dl_ui.py::TestSnapshotNewFields -v
```
Expected: KeyError.

- [ ] **Step 3: Extend the snapshot**

In `_build_snapshot`, update each per-URL dict to include the new fields:

```python
    return {
        "type": "job_snapshot",
        "job_id": job.id,
        "complete": job.completed,
        "summary": summary,
        "urls": [
            {
                "url": s.url,
                "status": s.status,
                "percent": s.percent,
                "downloaded_bytes": s.downloaded_bytes,
                "total_bytes": s.total_bytes,
                "speed": s.speed,
                "eta": s.eta,
                "filename": s.filename,
                "paths": list(s.paths),
                "error": s.error,
                # v1.X — rich card fields
                "title": s.title,
                "uploader": s.uploader,
                "duration": s.duration,
                "thumbnail_ready": s.thumbnail_ready,
                "phase": s.phase,
                "log": list(s.log),
            }
            for s in job.url_states.values()
        ],
    }
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestSnapshotNewFields -v
pytest test_audio_dl_ui.py -v
```
Expected: 1 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): _build_snapshot includes title/uploader/duration/phase/log/thumbnail_ready"
```

---

## Task 14: Cleanup of thumbnail dir on job completion

**Files:**
- Modify: `audio_dl_ui.py:294-318` (`_supervise`) — schedule cleanup
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest test_audio_dl_ui.py::TestThumbCleanup -v
```
Expected: AssertionError.

- [ ] **Step 3: Add cleanup logic**

At the bottom of `_supervise` in `audio_dl_ui.py`, after the `if job.executor is not None: job.executor.shutdown(...)` line, add:

```python
    # Best-effort cleanup of thumbnail tempdir. Only remove if no
    # subscribers are still streaming — otherwise reconnects in the next
    # second would 404 on thumbs that should still render.
    with job.lock:
        subs_remaining = len(job.subscribers)
    if subs_remaining == 0:
        _cleanup_thumb_dir(job.id)
```

Add `import shutil` to the top-of-file imports (not currently imported).

Then add the helper near `_thumb_dir`:

```python
def _cleanup_thumb_dir(job_id: str) -> None:
    """Remove the job's thumb dir if it exists. Idempotent and never raises."""
    path = _thumb_dir(job_id)
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # pylint: disable=broad-except
        pass
```

Also extend `_events_iter`'s `finally` block to clean up if this is the last subscriber AND the job is complete. Find `_events_iter` and locate the `finally:` block:

```python
    finally:
        with job.lock:
            try:
                job.subscribers.remove(sub_queue)
            except ValueError:
                pass
            remaining = len(job.subscribers)
        if job.completed and remaining == 0:
            _cleanup_thumb_dir(job.id)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestThumbCleanup -v
pytest test_audio_dl_ui.py -v
```
Expected: 2 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): clean up thumbnail dir on job complete + last subscriber disconnect"
```

---

## Task 15: CSS `.card` block in `_INDEX_CSS_BASE`

This task can't be unit-tested cleanly — CSS only matters when rendered. We use a substring snapshot test (does the served HTML include the new selectors) and verify visually by running the app.

**Files:**
- Modify: `audio_dl_ui.py:381-699` (`_INDEX_CSS_BASE`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Write the failing substring test**

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest test_audio_dl_ui.py::TestCardCss -v
```
Expected: AssertionError (`.card {` not in HTML).

- [ ] **Step 3: Add the CSS block**

Inside `_INDEX_CSS_BASE`, find the existing rows-list styling (search for `.url-row` or whatever row class exists today; pylint-line-too-long is already disabled for the block). Append a new section at the end of the existing CSS block, BEFORE the closing `"""`:

```css
  /* ── v1.X rich job cards ────────────────────────────────────────── */
  .card {
    display: grid;
    grid-template-columns: 128px 1fr;
    gap: 14px;
    padding: 12px 14px;
    border: 1px solid var(--frame);
    margin: 8px 0;
    background: var(--bg);
  }
  .card-thumb {
    width: 120px;
    height: 68px;
    background: var(--dim);
    border: 1px solid var(--frame);
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .card-thumb img { display: block; width: 100%; height: 100%; object-fit: cover; }
  .card-thumb--placeholder::before {
    content: "▢";
    color: var(--frame);
    font-size: 24px;
  }
  .card-body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .card-head { display: flex; align-items: baseline; gap: 8px; }
  .card-title {
    color: var(--accent);
    font-weight: bold;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-meta { color: var(--dim); font-size: 0.9em; }
  .card-badge { color: var(--accent); font-family: inherit; margin-left: auto; }
  .card[data-state="complete"] .card-badge { color: var(--ok); }
  .card[data-state="failed"] .card-badge { color: var(--err); }
  .card[data-state="resolving"] .card-badge::after {
    content: "";
    display: inline-block;
    animation: card-blink 1s infinite;
  }
  @keyframes card-blink {
    50% { opacity: 0.3; }
  }
  .card-progress { display: flex; align-items: center; gap: 10px; }
  .card-bar {
    flex: 1;
    height: 6px;
    background: var(--dim);
    border: 1px solid var(--frame);
    position: relative;
  }
  .card-bar > span {
    position: absolute;
    top: 0; left: 0; bottom: 0;
    background: var(--bar, var(--accent));
    transition: width 0.15s linear;
  }
  .card-stats { color: var(--dim); font-size: 0.9em; min-width: 24ch; text-align: right; }
  .card-log {
    list-style: none;
    margin: 0; padding: 0;
    color: var(--dim);
    font-size: 0.9em;
  }
  .card-log-line { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .card-log-line[data-level="warning"] { color: var(--warn); }
  .card-log-line[data-level="error"] { color: var(--err); }
  /* State-driven show/hide */
  .card[data-state="queued"] .card-progress,
  .card[data-state="resolving"] .card-progress,
  .card[data-state="queued"] .card-log,
  .card[data-state="resolving"] .card-log { display: none; }
  @media (prefers-reduced-motion: reduce) {
    .card[data-state="resolving"] .card-badge::after { animation: none; }
  }
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestCardCss -v
pytest test_audio_dl_ui.py -v
```
Expected: 1 new pass + all existing pass.

- [ ] **Step 5: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): add .card CSS block for rich job cards"
```

---

## Task 16: HTML template — swap row markup for card template

**Files:**
- Modify: `audio_dl_ui.py:1278-1343` (`_INDEX_HTML_BODY`)
- Modify: `test_audio_dl_ui.py`

- [ ] **Step 1: Read current `_INDEX_HTML_BODY`**

```bash
sed -n '1278,1345p' audio_dl_ui.py
```

Note the existing row-list container id/class — typically something like `#queue` or `#job-list`. We keep its container, only swap inner markup. The exact replacement depends on the current shape; the goal is: the container that holds per-URL elements is preserved, and a new `<template>` element for cards is added so JS can clone it.

- [ ] **Step 2: Write the failing substring test**

```python
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
```

- [ ] **Step 3: Run test, verify it fails**

```bash
pytest test_audio_dl_ui.py::TestCardTemplate -v
```
Expected: AssertionError.

- [ ] **Step 4: Add the card template**

Inside `_INDEX_HTML_BODY`, at the end (just before the closing `"""`), append:

```html
<template id="card-template">
  <article class="card" data-state="queued">
    <div class="card-thumb card-thumb--placeholder"></div>
    <div class="card-body">
      <header class="card-head">
        <span class="card-title"></span>
        <span class="card-meta"></span>
        <span class="card-badge">[--]</span>
      </header>
      <div class="card-progress">
        <div class="card-bar"><span style="width:0%"></span></div>
        <div class="card-stats"></div>
      </div>
      <ul class="card-log"></ul>
    </div>
  </article>
</template>
```

The existing container `<div class="body-section" id="rows">` ([audio_dl_ui.py:1321](../../../audio_dl_ui.py:1321)) is preserved — JS appends `.card` elements there instead of `.url-row` elements. Remove the old `.url-row` CSS selectors as part of Task 17's DRY cleanup.

- [ ] **Step 5: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestCardTemplate -v
pytest test_audio_dl_ui.py -v
```
Expected: 1 new pass + all existing pass.

- [ ] **Step 6: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): card template element for JS-cloned per-URL cards"
```

---

## Task 17: JS — handlers + card rendering

**Files:**
- Modify: `audio_dl_ui.py:1345-1872` (`_INDEX_JS`)
- Modify: `test_audio_dl_ui.py`

This task replaces row-rendering code with card-rendering code. The exact integration depends on the existing event dispatcher inside `_INDEX_JS`. Read it first, locate the SSE `onmessage` handler and the row-append logic, and replace.

- [ ] **Step 1: Read current JS**

```bash
sed -n '1345,1872p' audio_dl_ui.py | head -200
```

Locate: (a) SSE EventSource setup, (b) message dispatcher (`onmessage` → `JSON.parse(data)` → switch on `type`), (c) row create/update helpers, (d) progress percent renderer.

- [ ] **Step 2: Write the failing substring tests**

```python
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
```

- [ ] **Step 3: Run test, verify it fails**

```bash
pytest test_audio_dl_ui.py::TestCardJs -v
```
Expected: AssertionError.

- [ ] **Step 4: Implement card rendering JS**

Inside `_INDEX_JS`, in the SSE event dispatcher area, add card render logic. The shape (place inside the existing IIFE):

```javascript
// Card rendering — v1.X rich job cards
const cardEls = {};   // url -> HTMLElement
const cardState = {}; // url -> { phase, title, uploader, duration, thumbnail_ready, log[] }

function upsertCard(url) {
  if (cardEls[url]) return cardEls[url];
  const tpl = document.getElementById('card-template');
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.dataset.url = url;
  const container = document.getElementById('rows');
  container.appendChild(node);
  cardEls[url] = node;
  cardState[url] = { phase: 'queued', log: [] };
  node.querySelector('.card-title').textContent = url;
  return node;
}

function renderCard(url) {
  const el = upsertCard(url);
  const st = cardState[url] || {};
  // state attribute drives CSS show/hide
  el.dataset.state = st.phase || 'queued';

  // Title row
  if (st.title) {
    el.querySelector('.card-title').textContent = st.title;
    const metaParts = [];
    if (st.uploader) metaParts.push(st.uploader);
    if (st.duration) metaParts.push(formatDuration(st.duration));
    el.querySelector('.card-meta').textContent = metaParts.join(' · ');
  } else {
    el.querySelector('.card-title').textContent = url;
    el.querySelector('.card-meta').textContent = '';
  }

  // Badge
  const badge = el.querySelector('.card-badge');
  badge.textContent = phaseBadge(st.phase);

  // Thumbnail
  const thumb = el.querySelector('.card-thumb');
  if (st.thumbnail_ready && currentJobId) {
    thumb.classList.remove('card-thumb--placeholder');
    thumb.innerHTML = `<img src="/jobs/${currentJobId}/thumb/${st.url_idx}.jpg?token=${CSRF_TOKEN}" alt="">`;
  } else {
    thumb.classList.add('card-thumb--placeholder');
    thumb.innerHTML = '';
  }

  // Progress
  const bar = el.querySelector('.card-bar span');
  bar.style.width = (st.percent || 0) + '%';
  el.querySelector('.card-stats').textContent = progressStats(st);

  // Log tail — last 3
  const ul = el.querySelector('.card-log');
  ul.innerHTML = '';
  const tail = (st.log || []).slice(-3);
  for (const line of tail) {
    const li = document.createElement('li');
    li.className = 'card-log-line';
    li.dataset.level = line.level;
    li.textContent = line.text;
    ul.appendChild(li);
  }
}

function phaseBadge(phase) {
  switch (phase) {
    case 'downloading':    return '[..]';
    case 'postprocessing': return '[~~]';
    case 'complete':       return '[OK]';
    case 'failed':         return '[xx]';
    case 'resolving':      return '[??]';
    default:               return '[--]';
  }
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, '0');
  return m + ':' + s;
}

function formatBytes(n) {
  if (!n) return '0B';
  const units = ['B','KB','MB','GB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(n >= 100 || i === 0 ? 0 : 1) + units[i];
}

function progressStats(st) {
  if (st.phase === 'postprocessing') return 'extracting audio…';
  if (st.phase === 'complete') {
    return st.total_bytes ? ('saved · ' + formatBytes(st.total_bytes)) : 'done';
  }
  if (st.phase === 'failed') return 'failed';
  if (st.phase === 'downloading') {
    const parts = [];
    if (st.speed) parts.push(formatBytes(st.speed) + '/s');
    if (st.eta != null) parts.push('ETA ' + formatDuration(st.eta));
    if (st.downloaded_bytes && st.total_bytes) {
      parts.push(formatBytes(st.downloaded_bytes) + '/' + formatBytes(st.total_bytes));
    }
    return parts.join(' · ');
  }
  return '';
}
```

Then in the SSE event dispatcher, add handlers for `url_metadata`, `url_log`, and extend the existing `progress` handler:

```javascript
// In the existing onmessage / event dispatcher:
case 'job_snapshot':
  for (const u of msg.urls) {
    cardState[u.url] = {
      url_idx: msg.urls.indexOf(u),
      phase: u.phase || (u.status === 'completed' ? 'complete' : u.status === 'failed' ? 'failed' : null),
      title: u.title, uploader: u.uploader, duration: u.duration,
      thumbnail_ready: u.thumbnail_ready, log: u.log || [],
      percent: u.percent, speed: u.speed, eta: u.eta,
      downloaded_bytes: u.downloaded_bytes, total_bytes: u.total_bytes,
    };
    renderCard(u.url);
  }
  break;

case 'url_started':
  cardState[msg.url] = cardState[msg.url] || { log: [] };
  cardState[msg.url].phase = 'resolving';
  renderCard(msg.url);
  break;

case 'url_metadata':
  cardState[msg.url] = cardState[msg.url] || { log: [] };
  Object.assign(cardState[msg.url], {
    title: msg.title, uploader: msg.uploader, duration: msg.duration,
    thumbnail_ready: msg.thumbnail_ready,
  });
  // url_idx lookup by current insertion order in cardEls / cardState
  cardState[msg.url].url_idx = Object.keys(cardState).indexOf(msg.url);
  renderCard(msg.url);
  break;

case 'progress':
  cardState[msg.url] = cardState[msg.url] || { log: [] };
  Object.assign(cardState[msg.url], {
    phase: msg.phase || cardState[msg.url].phase,
    percent: msg.percent,
    speed: msg.speed, eta: msg.eta,
    downloaded_bytes: msg.downloaded_bytes, total_bytes: msg.total_bytes,
  });
  renderCard(msg.url);
  break;

case 'url_log':
  cardState[msg.url] = cardState[msg.url] || { log: [] };
  cardState[msg.url].log.push({ level: msg.level, text: msg.text, ts: msg.ts });
  if (cardState[msg.url].log.length > 50) cardState[msg.url].log.shift();
  renderCard(msg.url);
  break;

case 'url_completed':
  cardState[msg.url] = cardState[msg.url] || { log: [] };
  cardState[msg.url].phase = 'complete';
  cardState[msg.url].paths = msg.paths;
  renderCard(msg.url);
  break;

case 'url_failed':
  cardState[msg.url] = cardState[msg.url] || { log: [] };
  cardState[msg.url].phase = 'failed';
  cardState[msg.url].error = msg.error;
  renderCard(msg.url);
  break;
```

**Important:** the existing JS uses `currentJobId` (set on POST /jobs response at [audio_dl_ui.py:1370](../../../audio_dl_ui.py:1370), reassigned at [audio_dl_ui.py:1682](../../../audio_dl_ui.py:1682)) and `CSRF_TOKEN` (constant at [audio_dl_ui.py:1359](../../../audio_dl_ui.py:1359)). Use those exact names. The DOM helper `$()` is defined at line 1360 — use it instead of `document.getElementById` for consistency.

**Remove the old row-rendering code** (`rowFor`, `setGlyph`, `.url-row` handling) from `_INDEX_JS`. **Also remove the `.url-row` CSS block** at [audio_dl_ui.py:615-635](../../../audio_dl_ui.py:615). DRY out the dispatcher so only the card path remains.

- [ ] **Step 5: Run tests, verify they pass**

```bash
pytest test_audio_dl_ui.py::TestCardJs -v
pytest test_audio_dl_ui.py -v
```
Expected: 1 new pass + all existing pass.

- [ ] **Step 6: Manual smoke test**

```bash
audio-dl-ui --no-browser &
UI_PID=$!
sleep 1
open http://127.0.0.1:8000  # or visit manually
```

Submit a 30-second YouTube URL and verify:
1. Card appears immediately in `queued` state with raw URL.
2. Card transitions to `resolving`, then `downloading` with title appearing.
3. Thumbnail loads within a couple seconds.
4. Speed/ETA/bytes update live in the stats line.
5. Log tail shows last 3 lines (e.g., `[hls] downloading fragment N/M`).
6. Card transitions to `postprocessing` then `complete` with `[OK]` badge.
7. Try with all 10 themes — visual sanity that nothing is broken on the unusual ones (amber, dawn).

```bash
kill $UI_PID
```

- [ ] **Step 7: Commit**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat(ui): card rendering JS + url_metadata/url_log/progress handlers"
```

---

## Task 18: CHANGELOG + version bump + final smoke

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `audio_dl.py:31` (`__version__`)
- Modify: `pyproject.toml:7` (`version`)

- [ ] **Step 1: Decide version**

Since v1.6 and v1.7 were commit-labeled but never released (versions still at 1.5), this PR is a chance to either:
- (a) Set both files to **v1.6** and treat this work + the prior UI commits as one release, OR
- (b) Set both files to **v1.8** so version-label matches the commit-label of the most recent prior work.

Choose **v1.6** (matches the "next unreleased version" semantic — what's actually shipping). Update internal phrasing in the spec/plan headers if needed; not required.

- [ ] **Step 2: Bump `__version__`**

In `audio_dl.py`:

```python
__version__ = "1.6"
```

- [ ] **Step 3: Bump pyproject**

In `pyproject.toml`:

```toml
version = "1.6"
```

- [ ] **Step 4: Add CHANGELOG entry**

Prepend the following `## v1.6` section to `CHANGELOG.md`, before `## v1.5`:

```markdown
## v1.6 — Rich job cards + structural-identity themes (2026-05-16)

Web UI: replaces the running-job row list with a stack of full-width
cards, each one a self-contained status panel — thumbnail, title +
uploader · duration, live speed/ETA/bytes, last 3 yt-dlp log lines,
and the v1.6/v1.7 per-theme structural typography + grid identities
shipped together.

### Added
- **Rich job cards** ([2026-05-16 spec](docs/superpowers/specs/2026-05-16-rich-job-cards-design.md)).
  Per-URL card with:
  - Server-proxied thumbnail at `/jobs/{id}/thumb/{idx}.jpg`
    (CSRF-guarded; no cross-origin loads).
  - Title / uploader / duration extracted from yt-dlp's info dict.
  - Live speed, ETA, downloaded/total bytes on every progress tick.
  - Filtered yt-dlp log tail: keeps `[hls]`, `[ffmpeg]`,
    `[ExtractAudio]`, `[EmbedThumbnail]`, `[Metadata]`, warnings and
    errors; drops debug, download-destination and extractor chatter.
- **Six lifecycle states per card:** queued, resolving, downloading,
  postprocessing, complete, failed. `phase` is set server-side and
  travels on the `progress` event.
- **`url_metadata` SSE event** (one-shot per URL, may fire twice — once
  on info-known, once on thumb-fetched).
- **`url_log` SSE event** (filtered yt-dlp output, bounded ring of 50
  per URL).
- **`progress` event** gains a `phase` field; existing fields preserved.
- **`job_snapshot`** carries title / uploader / duration /
  thumbnail_ready / phase / log for late-connect subscribers.
- **v1.6 / v1.7 theme work shipped:** per-theme typography overrides,
  Phosphor reference rendering, structural identities for vintage
  (Amber, Solarized, Gruvbox), editorial (Rose Pine + Moon + Dawn),
  modern (Tokyo Night, Atom Dark Pro, Claude), and per-theme CSS Grid
  layouts so each theme is structurally distinct.

### Changed
- `progress` event payload includes the new `phase` field; existing
  consumers ignore unknown fields.
- yt-dlp now runs with a per-URL `logger=` so its output is routed
  through the SSE log stream rather than printed to the UI process's
  stderr.

### Internal
- Pure functions added: `_should_keep_log`, `_pick_thumbnail_url`,
  `_url_idx`. Each is independently unit-tested.
- Thumbnail cleanup runs on job-complete-and-last-subscriber-disconnect.
- No new runtime dependencies (`httpx` is already pulled in by
  `uvicorn[standard]`).
```

- [ ] **Step 5: Full test suite + lint**

```bash
pytest -v
pylint $(git ls-files '*.py')
```

Expected: all tests pass; pylint score >= existing baseline. Fix any new findings.

- [ ] **Step 6: Manual smoke (real download)**

```bash
audio-dl-ui --no-browser &
UI_PID=$!
sleep 1
```

Visit `http://127.0.0.1:8000`, submit a short YouTube URL, watch cards. Then submit two URLs at once with `jobs=2` to verify multi-card layout. Then with a known-failing URL (404) to verify failed-state card.

```bash
kill $UI_PID
```

- [ ] **Step 7: Commit**

```bash
git add CHANGELOG.md audio_dl.py pyproject.toml
git commit -m "chore: bump to v1.6 — rich job cards + structural-identity themes"
```

- [ ] **Step 8: Push branch + open PR**

```bash
git push -u origin "$(git branch --show-current)"
gh pr create --title "v1.6 — rich job cards" --body "$(cat <<'EOF'
## Summary

- Replaces row list with per-URL cards: thumbnail, title/uploader/duration, live speed/ETA/bytes, filtered yt-dlp log tail.
- Six lifecycle states (`phase` set server-side; emitted on `progress`).
- New `url_metadata` and `url_log` SSE events; `progress` gets `phase` field.
- Thumbnail proxy at `/jobs/{id}/thumb/{idx}.jpg`, CSRF-guarded.
- Ships the v1.6/v1.7 commit-labeled theme work as part of the v1.6 release.

Spec: [2026-05-16-rich-job-cards-design.md](docs/superpowers/specs/2026-05-16-rich-job-cards-design.md)
Plan: [2026-05-16-rich-job-cards.md](docs/superpowers/plans/2026-05-16-rich-job-cards.md)

## Test plan

- [ ] `pytest` — all tests pass
- [ ] `pylint $(git ls-files '*.py')` — clean
- [ ] Manual: single YouTube URL → card transitions through all phases
- [ ] Manual: two URLs in parallel → both cards live-update independently
- [ ] Manual: failing URL → card lands in `failed` state with error log
- [ ] Manual: cycle all 10 themes → no broken card layout in any

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

After completing all tasks, verify against the spec:

- [ ] **§ User-visible behavior — 6 states** — covered by Task 9 (phase transitions) + Task 17 (JS state → CSS `[data-state=...]`).
- [ ] **§ UrlState extensions** — Task 3.
- [ ] **§ SSE `progress` + `phase`** — Tasks 7, 8.
- [ ] **§ `url_metadata` one-shot, may fire twice** — Tasks 7 (first emit) and 11 (re-emit on thumb success).
- [ ] **§ `url_log`** — Task 4.
- [ ] **§ `job_snapshot` extension** — Task 13.
- [ ] **§ Thumbnail proxy** — Tasks 10 (fetcher), 11 (dispatch), 12 (endpoint).
- [ ] **§ Logger seam + filter + routing** — Tasks 1 (filter), 4 (logger), 5–6 (wiring through `download_media`).
- [ ] **§ Phase transitions** — Tasks 8 (hook-side), 9 (`_run_one`-side).
- [ ] **§ UI rendering** — Tasks 15 (CSS), 16 (template), 17 (JS).
- [ ] **§ Error handling table** — failure paths covered: thumb fetch (Task 10/11), logger non-string coerce (Task 4), missing title/uploader (Task 7 fallback), phase=failed (Task 9), thumb endpoint CSRF/404 (Task 12), thumb dir on cancel — implicit via subscriber-disconnect cleanup (Task 14).
- [ ] **§ Testing** — every test category from spec § Testing is in the task list.
- [ ] **§ File-size impact** — estimated within plan; verified by running `wc -l audio_dl_ui.py` after Task 17.
- [ ] **§ Versioning** — Task 18.
- [ ] **§ Non-goals respected** — no per-theme card variations, no expandable log, no responsive treatment, no aggregate stats.

If anything in the spec is uncovered after running through this list, add a task.
