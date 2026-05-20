# v1.9 Per-URL Format — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each queued URL carries its own target format, set via a per-row dropdown in a new single-screen row-builder form. Paste-time format detection strips a trailing `mp3`/`m4a`/`flac`/`alac`/`opus`/`wav`/`mp4` token and pre-fills the row picker. The server schema, `UrlState`, `_run_one`, snapshot, and In Flight card chip all carry the per-URL format through.

**Architecture:** Two layers move in lockstep — server data model + UI rebuild.

- **Server (small, sharp):** Add `UrlSpec(BaseModel)`; change `JobRequest.urls` from `str` to `list[UrlSpec]`; drop top-level `format` and `jobs` fields; add `UrlState.media_format`; switch `_run_one` from `job.media_format` to `url_state.media_format`; add `media_format` to each `_build_snapshot` URL entry and a `default_format` at the top of the snapshot.
- **Client (larger rewrite of `_INDEX_HTML_BODY` + form section of `_INDEX_JS` + new CSS in `_INDEX_CSS_BASE`):** New row-builder layout — committed rows + always-present empty input row at bottom; per-row `<select>` for format; default-format strip below with `set all → default` and `clear all` bulk actions; submit emits new POST shape. In Flight `card-template` gains a `card-format-chip`.
- **Tests:** ~10 existing tests touch the POST body shape — migrate them via the `_valid_body()` helper. Add tests for new validation paths and the snapshot's per-URL `media_format`. JS pure helpers (`parseLine`) are tested indirectly via POST body assertions per spec.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, vanilla JS, CSS grid (no new theme vars), pytest, pylint.

**Spec:** [docs/superpowers/specs/2026-05-19-per-url-format-design.md](../specs/2026-05-19-per-url-format-design.md) (committed 3db083a)

**Branching/PR notes:**
- Create a feature branch `v1.9-per-url-format` off `origin/main`. The plan doc is already on `main` via this commit; only implementation commits land in the PR.
- Per CLAUDE.md: sub-agents that write/edit code MUST use `isolation: "worktree"` on the Agent call.
- After PR opens and CI is green, mark ready-for-review (Codex fires on draft→ready).

---

## File Structure

| File | Role | Status |
|---|---|---|
| `audio_dl_ui.py` | All server + bundled HTML/CSS/JS. | Modify |
| `test_audio_dl_ui.py` | Tests; existing tests need POST-shape migration. | Modify |
| `audio_dl.py` | CLI (unchanged by v1.9); only `__version__` bump. | Modify |
| `pyproject.toml` | `version` bump. | Modify |
| `CHANGELOG.md` | Add `## v1.9.0` section. | Modify |

`audio_dl_ui.py` is already 3398 lines and the spec deliberately keeps everything in that one file (the project convention is a single-module web UI). Do not split it during v1.9.

---

## Task 0: Create feature branch

**Files:** none yet.

- [ ] **Step 1: Confirm on `main` at HEAD `3db083a` (spec commit) and create the branch.**

```bash
git fetch origin
git checkout -B v1.9-per-url-format origin/main
git log --oneline -2
```

Expected: top commit is `docs(spec): v1.9 per-URL format — single-screen row builder`.

- [ ] **Step 2: Confirm baseline tests pass.**

```bash
pytest -q
```

Expected: green. If any test fails, stop and investigate before touching code — it's a pre-existing problem.

---

## Task 1: `UrlSpec` model + new `JobRequest` shape + `UrlState.media_format` field

**Goal:** Change the wire format and the per-URL state container in one atomic commit. After this task, the server accepts the new shape and stores per-URL format on each `UrlState`; downloads still read `job.media_format` (Task 2 switches that). Old-shape POSTs return 422.

**Why one task:** `post_jobs` constructs `UrlState(url=..., media_format=...)`, which only compiles after the dataclass gains the field. Splitting this across two commits leaves a broken intermediate state — the constructor would fail with `TypeError`. The whole shape-and-field change ships together.

**Files:**
- Modify: `audio_dl_ui.py` (`UrlState` dataclass ~line 67, `JobState` ~line 98, `JobRequest` ~line 2968, `post_jobs` ~line 2992).
- Modify: `test_audio_dl_ui.py` (helper at line 72 + ~10 body callsites + ~5 `UrlState(url=...)` direct constructions).

- [ ] **Step 1: Write the failing test — new shape accepted, old shape rejected.**

Edit `test_audio_dl_ui.py`. Replace `_valid_body` at line 72 with the new-shape default:

```python
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
```

Add a new test class above `TestPostJobsValidation`:

```python
class TestPostJobsShapeV1_9:
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
```

Migrate the existing callsites in `TestPostJobsValidation` (lines ~86–122) — most stop making sense once `urls` is a list and `format`/`jobs` are gone. Replace the class with:

```python
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
```

Drop the `test_bad_format_400` (top-level format no longer exists; replaced by `test_unknown_format_in_urlspec_returns_400` in `TestPostJobsShapeV1_9`), `test_empty_urls_400` / `test_whitespace_only_urls_400` (empty-list case is covered by `test_empty_urls_list_returns_400` above), `test_jobs_too_low_400`, `test_jobs_too_high_400` (jobs field removed). Other test classes that build a body via `_valid_body()` keep using the helper unchanged.

Search for any other test that builds a body dict literal with `"urls": "..."` (string), `"format": "..."` (top-level), or `"jobs": N`:

```bash
grep -nE '"(urls|format|jobs)"' test_audio_dl_ui.py
```

Migrate each by switching to `_valid_body(...)` plus per-URL overrides. The likely affected classes from the spec: `TestPostJobsHappyPath`, `TestSseHappyPath`, `TestSseBroadcast`, `TestCancel`, `TestCsrfProtection`, `TestRunOneSanitizeError`, `TestRevealSnapshotsJobs`, `TestQueueBound`. For each affected test, change body-construction from:

```python
body = {
    "urls": "https://youtu.be/AAA https://youtu.be/BBB",
    "format": "m4a",
    "output_dir": str(tmp_path),
    ...
}
```

to:

```python
body = _valid_body(output_dir=str(tmp_path))
body["urls"] = [
    {"url": "https://youtu.be/AAA", "format": "m4a"},
    {"url": "https://youtu.be/BBB", "format": "m4a"},
]
```

- [ ] **Step 2: Run failing tests.**

```bash
pytest test_audio_dl_ui.py::TestPostJobsShapeV1_9 -v
```

Expected: all four tests in `TestPostJobsShapeV1_9` FAIL with 422 / 500 / wrong status — the server still expects the old shape.

- [ ] **Step 3: Add `media_format` to `UrlState`.**

In `audio_dl_ui.py` around line 67, add the field at the top of `UrlState` (required — no default; default-construction tests are migrated below):

```python
@dataclass
class UrlState:  # pylint: disable=too-many-instance-attributes
    """Per-URL download state within a job, updated by progress hooks."""

    url: str
    media_format: str        # v1.9 — per-URL target format
    sanitized_url: str = ""
    # ...rest unchanged
```

Audit every direct `UrlState(...)` construction:

```bash
grep -n "UrlState(" audio_dl_ui.py test_audio_dl_ui.py
```

Expect ~5 hits in tests (`_fresh_job` line ~1506, `TestProgressHook._make_job` line ~178, `TestUrlStateNewFields` lines 1481–1499, plus inline constructions like the one at test_audio_dl_ui.py:590). Update each to pass a `media_format`. Most can take a literal `"mp3"`:

- `_fresh_job`: `url_states={url: UrlState(url=url, media_format="mp3")}`
- `TestProgressHook._make_job`: same
- `TestUrlStateNewFields.test_defaults`: `s = UrlState(url="https://example/x", media_format="mp3")`
- `TestUrlStateNewFields.test_log_independence_across_instances`: both `a` and `b` get `media_format="mp3"`
- The line 590 inline case (`UrlState(url="u", paths=[path], status="completed")`): add `media_format="mp3"`.

If you find any production-code construction of `UrlState` outside `post_jobs`, that's a sign something else needs updating — flag and stop.

- [ ] **Step 4: Update `JobRequest` and `post_jobs` to the new shape.**

In `audio_dl_ui.py` around line 2968, replace `JobRequest` and add `UrlSpec` above it:

```python
class UrlSpec(BaseModel):
    """One URL + the target format for that URL (v1.9 per-URL format)."""
    url: str
    format: str


class JobRequest(BaseModel):
    """Request body for POST /jobs (v1.9: per-URL format)."""
    urls: list[UrlSpec]
    output_dir: str
    playlist: bool = False
    force: bool = False
    fragments: int = 4
    # NOTE: top-level `format` removed in v1.9 — each UrlSpec carries its own.
    # NOTE: `jobs` removed in v1.9 — vestigial since v1.8 (global executor).
```

Replace the body of `post_jobs` (lines ~2992–3028) to iterate `req.urls`:

```python
@app.post("/jobs")
async def post_jobs(req: JobRequest, _csrf: str = Depends(_require_csrf)) -> dict:  # pylint: disable=unused-argument
    """Validate the request, register a JobState, return the job_id."""
    if not req.urls:
        raise HTTPException(400, "At least one URL is required.")
    for spec in req.urls:
        if spec.format not in ALL_FORMATS:
            raise HTTPException(
                400,
                f"Unknown format: {spec.format!r} for {spec.url!r}. "
                f"Must be one of {ALL_FORMATS}.",
            )

    if not 1 <= req.fragments <= 16:
        raise HTTPException(400, "fragments must be in 1..16.")

    output_dir = os.path.expanduser(req.output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"output_dir not writable: {e}") from e

    job_id = uuid.uuid4().hex
    # Preserve order from the request. Same-URL submitted twice with
    # different formats: last-wins (UI prevents duplicates today; tests
    # may submit them).
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
```

Note that `url_states={u: UrlState(url=u) for u in urls}` becomes the loop above so each `UrlState` is constructed with its `media_format` — that field was added in Step 3.

- [ ] **Step 5: Drop `JobState.jobs` field (no longer set).**

In `audio_dl_ui.py` around line 122, delete the `jobs: int` line from the `JobState` dataclass. Search for other reads of `job.jobs`:

```bash
grep -n '\.jobs\b' audio_dl_ui.py test_audio_dl_ui.py
```

Expected: no remaining reads in `audio_dl_ui.py` (vestigial). Tests that set or assert `job.jobs` (e.g. `TestPostJobsHappyPath.test_registers_in_jobs_dict` line ~161 asserts `assert job.jobs == 2`; `_fresh_job` line 1509 passes `jobs=1`) need the field removed from their construction and assertion lines. Also remove `jobs=1` / `jobs=2` kwargs from `JobState(...)` constructions throughout the test file:

```bash
grep -n "jobs=" test_audio_dl_ui.py
```

Each hit either passes `jobs=N` to `JobState(...)` (drop the kwarg) or passes `jobs=N` to `_valid_body(...)` (drop the override — the field is gone from `JobRequest`).

- [ ] **Step 6: Run the v1.9 shape tests + the migrated validation tests.**

```bash
pytest test_audio_dl_ui.py::TestPostJobsShapeV1_9 test_audio_dl_ui.py::TestPostJobsValidation -v
```

Expected: PASS.

- [ ] **Step 7: Run the full suite.**

```bash
pytest -q
```

Expected: PASS. If anything red, it's a missed body-shape callsite or a `UrlState(url=...)` construction missing `media_format` — migrate it.

- [ ] **Step 8: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat: per-URL format wire shape + UrlState.media_format"
```

---

## Task 2: `_run_one` reads `url_state.media_format`

**Goal:** Per-URL format flows end-to-end into the download call. Until this lands, downloads still use `job.media_format` (the first UrlSpec's format from Task 1) — wrong-for-mixed-batches but harmless for single-format batches, which is what every test exercised before v1.9.

**Files:**
- Modify: `audio_dl_ui.py` (`_run_one` line 500).
- Modify: `test_audio_dl_ui.py` (new test class).

- [ ] **Step 1: Write the failing test — `_run_one` receives the per-URL format.**

Add to `test_audio_dl_ui.py` in the appropriate location (near the other `_run_one` tests around line 1602):

```python
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
            # TestRunOneSanitizeError line 768) is a 50× 0.05s poll = 2.5s
            # ceiling, which is plenty for two stub downloads.
            for _ in range(50):
                if JOBS[job_id].completed:
                    break
                time.sleep(0.05)
            assert JOBS[job_id].completed, "job did not complete in time"

        assert captured_formats["https://youtu.be/AAA"] == "m4a"
        assert captured_formats["https://youtu.be/BBB"] == "mp4"
```

- [ ] **Step 2: Run the failing test.**

```bash
pytest test_audio_dl_ui.py::TestRunOnePerUrlFormat -v
```

Expected: FAIL — `_run_one` still passes `job.media_format`, so both URLs receive the first format (`m4a`) and the `mp4` assertion fails.

- [ ] **Step 3: Switch `_run_one` to read `url_state.media_format`.**

In `audio_dl_ui.py` at line 500, change:

```python
        paths = download_media(
            clean,
            media_format=job.media_format,
```

to:

```python
        paths = download_media(
            clean,
            media_format=url_state.media_format,
```

That's the only line in `_run_one` that needs to change.

- [ ] **Step 4: Run the test.**

```bash
pytest test_audio_dl_ui.py::TestRunOnePerUrlFormat -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite.**

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat: _run_one downloads with per-URL media_format"
```

---

## Task 3: Snapshot exposes per-URL `media_format` + top-level `default_format`

**Goal:** Late-connect SSE subscribers can render each card with the right format chip.

**Files:**
- Modify: `audio_dl_ui.py` (`_build_snapshot`).
- Modify: `test_audio_dl_ui.py` (extend `TestSnapshotNewFields` or add a sibling class).

- [ ] **Step 1: Write the failing test — snapshot carries per-URL format.**

Add to `test_audio_dl_ui.py` near `TestSnapshotNewFields` (around line 2024):

```python
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
```

- [ ] **Step 2: Run failing test.**

```bash
pytest test_audio_dl_ui.py::TestSnapshotPerUrlFormat -v
```

Expected: FAIL — `media_format` key absent from `snap["urls"][*]`, `default_format` absent at top level.

- [ ] **Step 3: Update `_build_snapshot`.**

In `audio_dl_ui.py` at `_build_snapshot` (line ~3031), add `media_format` to each URL dict and `default_format` at the top:

```python
def _build_snapshot(job: JobState) -> dict:
    """Build a ``job_snapshot`` event describing the job's current state."""
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

- [ ] **Step 4: Run the test.**

```bash
pytest test_audio_dl_ui.py::TestSnapshotPerUrlFormat -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite.**

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat: snapshot carries per-URL media_format + default_format"
```

---

## Task 4: Form HTML — row-builder layout

**Goal:** Replace the textarea+single-format-select with the row builder shown in the spec's mockup. Default-format strip below; bulk actions.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_HTML_BODY`, lines ~1917–1927).

- [ ] **Step 1: Replace the form's body section.**

In `audio_dl_ui.py`, locate the `<form id="dl">` block (lines ~1917–1927) and replace the entire `<div class="body-section">` content with:

```html
  <form id="dl">
    <div class="body-section">
      <div class="urls-zone-header">
        <span class="label">urls</span>
        <span class="urls-count"><span id="queue-count">0</span> in queue</span>
        <span class="dim urls-hint">↵ to add · paste many lines to split</span>
      </div>
      <div id="queue-list" class="queue-list"></div>
      <div class="queue-input-row">
        <span class="queue-gutter queue-gutter-add">+</span>
        <input type="text" id="add-input" class="queue-url-input"
               placeholder="paste or type a URL…" autocomplete="off">
        <select class="queue-format-select" id="add-input-format" disabled>__FORMAT_OPTIONS__</select>
        <span class="queue-remove-spacer"></span>
      </div>
      <div class="default-strip">
        <span class="dim">default format for new URLs:</span>
        <select id="default-format" class="default-format-select">__FORMAT_OPTIONS__</select>
        <button type="button" id="set-all-default" class="strip-action">set all rows → default</button>
        <button type="button" id="clear-all" class="strip-action">clear all</button>
      </div>

      <div class="field-line"><span class="label">output</span><span class="marker">▸</span> <input class="field" id="output_dir" name="output_dir" type="text" value="__DEFAULT_OUTPUT_DIR__" required></div>
      <div class="field-line"><span class="label">fragments</span><span class="marker">▸</span> <input class="slider" id="fragments" name="fragments" type="range" min="1" max="16" value="4"> <span id="fragments_val" class="dim">4</span></div>
      <div class="field-line"><span class="label">flags</span><span class="marker">▸</span> <label style="margin-right:12px;"><input type="checkbox" id="playlist" name="playlist"> playlist</label> <label><input type="checkbox" id="force" name="force"> overwrite</label></div>
      <div class="field-line" style="margin-top:6px;"><span class="label"></span><button type="submit" class="tui-btn" id="submit">[ SUBMIT <span id="submit-count">0</span> ]</button> <span class="dim">⌘↵</span></div>
      <div class="field-line" id="submit-notice-row" hidden><span class="label"></span><span class="marker">▸</span> <span id="submit-notice" class="dim"></span></div>
    </div>
  </form>
```

The placeholder `__FORMAT_OPTIONS__` is already filled by `index()`'s `options.join` (line 2983); reusing it twice (for the trailing input row's select and the default-strip select) is fine — the templating just calls `.replace` on the string.

Also extend the In Flight `card-template` (around line 1976) to include a format chip in the header:

```html
<template id="card-template">
  <article class="card" data-state="queued">
    <div class="card-thumb card-thumb--placeholder"></div>
    <div class="card-body">
      <header class="card-head">
        <span class="card-title"></span>
        <span class="card-meta"></span>
        <span class="card-format-chip"></span>
        <span class="card-badge">[--]</span>
      </header>
      <div class="card-progress">
        <div class="card-bar"><span style="width:0%"></span></div>
        <div class="card-stats"></div>
        <button type="button" class="card-reveal" hidden>↗</button>
      </div>
      <ul class="card-log"></ul>
    </div>
  </article>
</template>
```

- [ ] **Step 2: Verify the page renders without template errors.**

```bash
pytest test_audio_dl_ui.py::TestIndex -v
```

Expected: PASS — `index()` returns 200 and the page contains `audio-dl`. The form is broken behaviorally (no JS yet), but the smoke test only checks the HTML reaches the browser.

- [ ] **Step 3: Commit (form HTML only — JS+CSS land next).**

```bash
git add audio_dl_ui.py
git commit -m "feat: row-builder form HTML scaffold (no behavior yet)"
```

---

## Task 5: CSS for queue rows + default strip + card chip

**Goal:** The row builder lays out correctly across themes; the format chip styles like the existing history badge.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_CSS_BASE`, somewhere near where existing form CSS lives — search for `.field-line`).

- [ ] **Step 1: Locate the right insertion point.**

```bash
grep -n "\.field-line\|\.tui-btn\|\.history-badge\b" audio_dl_ui.py | head -20
```

Insert the new rules immediately after the existing form-related rules in `_INDEX_CSS_BASE`. Reuse `var(--accent)`, `var(--dim)`, `var(--text)` already defined per-theme.

- [ ] **Step 2: Add the queue-list grid rules.**

```css
.urls-zone-header {
  display: flex; gap: 12px; align-items: baseline;
  margin-bottom: 6px;
}
.urls-count { color: var(--accent); }
.urls-hint { font-size: 0.85em; }

.queue-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 4px; }
.queue-row, .queue-input-row {
  display: grid;
  grid-template-columns: 16px 1fr 12ch 22px;
  align-items: center;
  gap: 8px;
}
.queue-gutter { color: var(--accent); text-align: center; }
.queue-gutter-add { color: var(--dim); }
.queue-url {
  font-family: inherit;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.queue-url-domain { color: var(--accent); }
.queue-url-path   { color: var(--dim); }
.queue-url.invalid {
  border-bottom: 1px dashed #b33;
}
.queue-url-input {
  background: transparent;
  border: 1px solid var(--dim);
  color: var(--text);
  font-family: inherit;
  padding: 2px 6px;
}
.queue-url-input.invalid { border-color: #b33; }
.queue-format-select, .default-format-select {
  background: transparent;
  border: 1px solid var(--dim);
  color: var(--text);
  font-family: inherit;
  padding: 1px 4px;
  width: 12ch;
}
.queue-format-select:disabled {
  opacity: 0.6;
}
.queue-remove {
  background: transparent;
  border: none;
  color: var(--dim);
  cursor: pointer;
  font-size: 1em;
}
.queue-remove:hover { color: var(--accent); }
.queue-remove-spacer { width: 22px; }

.default-strip {
  display: flex; gap: 12px; align-items: center;
  margin: 6px 0 10px 0;
  font-size: 0.9em;
}
.strip-action {
  background: transparent;
  border: 1px dashed var(--dim);
  color: var(--text);
  font-family: inherit;
  cursor: pointer;
  padding: 1px 8px;
}
.strip-action:hover { border-color: var(--accent); color: var(--accent); }

/* In-Flight card format chip — mirrors history-badge styling. */
.card-format-chip {
  display: inline-block;
  border: 1px solid var(--dim);
  padding: 0 6px;
  margin-left: 8px;
  font-size: 0.8em;
  text-transform: uppercase;
}
.card-format-chip[data-kind="lossless"] { color: var(--accent); border-color: var(--accent); }
.card-format-chip[data-kind="video"]    { color: var(--text);   border-color: var(--text); }
.card-format-chip[data-kind="lossy"]    { color: var(--dim);    border-color: var(--dim); }
.card-format-chip:empty { display: none; }
```

The lossy/lossless/video color buckets mirror the existing `history-badge` rules — search for `history-badge` in CSS to confirm color mapping and adjust if the existing scheme uses different vars.

- [ ] **Step 3: Smoke-test by launching the UI manually.**

```bash
audio-dl-ui --no-browser --port 9099 &
sleep 1
curl -s "http://127.0.0.1:9099/" | grep -c 'queue-list'
kill %1 2>/dev/null
```

Expected: count ≥ 1 (the new class names appear in the rendered HTML).

- [ ] **Step 4: Run the HTML test.**

```bash
pytest test_audio_dl_ui.py::TestIndex -v
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py
git commit -m "feat: CSS for queue rows, default strip, and format chip"
```

---

## Task 6: JS — queue state + render + Enter-to-commit

**Goal:** Typing a URL + Enter commits a row. Removing via × works. The empty input row persists at the bottom.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_JS`).

- [ ] **Step 1: Add the queue state at the top of the IIFE.**

In `audio_dl_ui.py` around line 2027 (right after `const rows = $('rows');`), add:

```js
  // ── v1.9 row-builder state ──────────────────────────────────────────
  const queue = [];          // [{ id, url, format, error }]
  let nextRowId = 1;
  const ALL_FORMATS_JS = new Set(['mp3','m4a','flac','alac','opus','wav','mp4']);
  let defaultFormat = 'm4a';

  function isValidUrl(s) {
    return /^https?:\\/\\//i.test(s);
  }

  function renderQueue() {
    const list = $('queue-list');
    list.innerHTML = '';
    for (const row of queue) {
      const el = document.createElement('div');
      el.className = 'queue-row';
      el.dataset.rowId = row.id;
      el.innerHTML = (
        '<span class="queue-gutter">▸</span>' +
        '<span class="queue-url' + (row.error ? ' invalid' : '') + '"' +
              (row.error ? ' title="' + row.error + '"' : '') + '>' +
          escapeHtml(row.url) +
        '</span>' +
        '<select class="queue-format-select">' + formatOptionsHTML(row.format) + '</select>' +
        '<button type="button" class="queue-remove" title="remove">×</button>'
      );
      el.querySelector('.queue-format-select').addEventListener('change', (e) => {
        row.format = e.target.value;
      });
      el.querySelector('.queue-remove').addEventListener('click', () => {
        const idx = queue.findIndex(r => r.id === row.id);
        if (idx >= 0) { queue.splice(idx, 1); renderQueue(); }
      });
      list.appendChild(el);
    }
    $('queue-count').textContent = String(queue.length);
    $('submit-count').textContent = String(queue.filter(r => !r.error).length);
    const submitBtn = $('submit');
    submitBtn.disabled = queue.length === 0 || queue.some(r => r.error);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Build a fresh <option> string for a per-row select with `selected` set
  // on the row's current format. Uses the same ALL_FORMATS set the server
  // exposes via __FORMAT_OPTIONS__, but rebuilds here so each row's select
  // can be initialized with a default.
  const ALL_FORMATS_LIST = Array.from(ALL_FORMATS_JS);
  function formatOptionsHTML(selected) {
    return ALL_FORMATS_LIST
      .map(f => '<option value="' + f + '"' + (f === selected ? ' selected' : '') + '>' + f + '</option>')
      .join('');
  }

  function commitRow(url, format) {
    const row = {
      id: 'r_' + (nextRowId++),
      url,
      format: format || defaultFormat,
      error: isValidUrl(url) ? null : 'must start with http:// or https://',
    };
    queue.push(row);
    renderQueue();
  }
```

(The `ALL_FORMATS_LIST` array is hardcoded because the server-side options string is rendered into HTML for the two top-level selects but JS needs its own array. The spec's seven formats — `mp3 m4a flac alac opus wav mp4` — are the source of truth in `audio_dl.py`; if it ever changes, both need updating. This matches the existing pattern where `__FORMAT_OPTIONS__` is injected.)

- [ ] **Step 2: Wire the input row to commit on Enter / blur.**

Add immediately after `commitRow`:

```js
  const addInput = $('add-input');
  const addInputFormat = $('add-input-format');

  function syncAddInputFormat() {
    addInputFormat.value = defaultFormat;
  }

  addInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const v = addInput.value.trim();
      if (!v) return;
      if (!isValidUrl(v)) {
        addInput.classList.add('invalid');
        addInput.title = 'must start with http:// or https://';
        return;
      }
      addInput.classList.remove('invalid');
      addInput.title = '';
      commitRow(v, defaultFormat);
      addInput.value = '';
    }
  });

  addInput.addEventListener('blur', () => {
    const v = addInput.value.trim();
    if (v && isValidUrl(v)) {
      commitRow(v, defaultFormat);
      addInput.value = '';
    }
  });

  $('default-format').addEventListener('change', (e) => {
    defaultFormat = e.target.value;
    syncAddInputFormat();
  });
  syncAddInputFormat();
  renderQueue();   // initial render — shows submit count = 0
```

- [ ] **Step 3: Smoke-test in a real browser.**

```bash
audio-dl-ui --no-browser --port 9099 &
sleep 1
open http://127.0.0.1:9099/   # macOS
```

Type a URL, press Enter — verify a row materializes. Click the × — verify it removes. Switch the default-strip dropdown — verify the empty-row dropdown follows. Kill the server with `kill %1` when done.

- [ ] **Step 4: Run tests.**

```bash
pytest -q
```

Expected: PASS (no test should regress; JS isn't covered).

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py
git commit -m "feat: row-builder queue state + Enter-to-commit"
```

---

## Task 7: JS — paste handler with per-line format detection

**Goal:** Pasting a multi-line list splits into rows. A trailing format token is stripped and pre-fills that row's picker.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_JS`).

- [ ] **Step 1: Add `parseLine` and the paste handler.**

In the same IIFE, right after the `commitRow` function, add:

```js
  function parseLine(line) {
    const trimmed = line.trim();
    if (!trimmed) return null;
    const parts = trimmed.split(/\\s+/);
    if (parts.length >= 2) {
      const last = parts[parts.length - 1].toLowerCase();
      if (ALL_FORMATS_JS.has(last)) {
        return { url: parts.slice(0, -1).join(' '), format: last };
      }
    }
    return { url: trimmed, format: defaultFormat };
  }
```

Add a paste listener on the input row's input (right after the existing `addInput.addEventListener('blur', ...)` block):

```js
  addInput.addEventListener('paste', (e) => {
    const text = (e.clipboardData || window.clipboardData).getData('text');
    if (!text) return;
    // If single line with no newline, fall through to default browser behavior
    // (user is editing a single field, not bulk-pasting).
    if (!/\\n/.test(text)) return;
    e.preventDefault();
    const lines = text.split(/\\n/);
    for (const line of lines) {
      const parsed = parseLine(line);
      if (parsed) commitRow(parsed.url, parsed.format);
    }
    addInput.value = '';
  });
```

- [ ] **Step 2: Add a server-side integration test exercising the paste outcomes.**

Per spec note 7: drive the parse table indirectly. Add to `test_audio_dl_ui.py` near `TestPostJobsShapeV1_9`:

```python
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
```

- [ ] **Step 3: Run the test.**

```bash
pytest test_audio_dl_ui.py::TestPostJobsBatchFormats -v
```

Expected: PASS.

- [ ] **Step 4: Manual smoke — paste the spec's table.**

Restart `audio-dl-ui --no-browser --port 9099`. In the browser, paste this block into the input row:

```
https://yt.com/abc
https://yt.com/abc mp3
https://yt.com/abc MP3
https://yt.com/abc unrelated

mp3
```

Verify the rows match the spec's expected-row table (note 6 — `mp3` alone becomes an invalid row with format=default).

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py test_audio_dl_ui.py
git commit -m "feat: paste handler splits lines and detects trailing format token"
```

---

## Task 8: JS — bulk actions + submit body shape

**Goal:** `set all → default`, `clear all`, and `submit()` posts the new shape. History re-download still works.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_JS`).

- [ ] **Step 1: Wire bulk actions.**

After the paste handler, add:

```js
  $('set-all-default').addEventListener('click', () => {
    for (const row of queue) row.format = defaultFormat;
    renderQueue();
  });

  $('clear-all').addEventListener('click', () => {
    queue.length = 0;
    renderQueue();
  });
```

- [ ] **Step 2: Replace `submitJob` and the form submit handler.**

Find the existing `$('dl').addEventListener('submit', ...)` (line ~2646) and the `submitJob` function (line ~2659). Replace both with:

```js
  $('dl').addEventListener('submit', async (e) => {
    e.preventDefault();
    await submitJob({
      rows: queue.filter(r => !r.error).map(r => ({ url: r.url, format: r.format })),
      output_dir: $('output_dir').value,
      playlist: $('playlist').checked,
      force: $('force').checked,
      fragments: parseInt($('fragments').value, 10),
      clearQueueOnSuccess: true,
    });
  });

  async function submitJob(opts) {
    if (!opts.rows || opts.rows.length === 0) return;
    $('submit').disabled = true;
    $('cancel').disabled = false;
    stopSpinner();
    refreshSummary();

    // Dedupe against URLs currently in flight (preserves v1.8 guard).
    const inFlight = new Set(Object.keys(cardState));
    const acceptedRows = opts.rows.filter(r => !inFlight.has(r.url));
    const skippedCount = opts.rows.length - acceptedRows.length;
    if (skippedCount > 0) {
      flashSubmitNotice(
        `${skippedCount} URL${skippedCount > 1 ? 's' : ''} already in flight, skipped`
      );
    }
    if (acceptedRows.length === 0) {
      $('submit').disabled = false;
      if (activeStreams.size === 0) $('cancel').disabled = true;
      return;
    }

    for (const r of acceptedRows) {
      urlMeta[r.url] = urlMeta[r.url] || {};
      urlMeta[r.url].format = r.format;
    }

    const body = {
      urls: acceptedRows,
      output_dir: opts.output_dir,
      playlist: opts.playlist,
      force: opts.force,
      fragments: opts.fragments,
    };
    let resp;
    try {
      resp = await fetch('/jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Audio-DL-Token': CSRF_TOKEN},
        body: JSON.stringify(body),
      });
    } catch (err) {
      alert('Failed to start: ' + err);
      $('submit').disabled = false;
      $('cancel').disabled = true;
      return;
    }
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({detail: resp.statusText}));
      alert('Error: ' + (detail.detail || resp.statusText));
      $('submit').disabled = false;
      $('cancel').disabled = true;
      return;
    }
    const {job_id} = await resp.json();
    currentJobId = job_id;
    if (opts.clearQueueOnSuccess) {
      queue.length = 0;
      renderQueue();
      $('add-input').value = '';
    }
    const stream = new EventSource('/jobs/' + job_id + '/events?token=' + encodeURIComponent(CSRF_TOKEN));
    activeStreams.set(job_id, stream);
    stream.onmessage = (m) => {
      if (!m.data) return;
      try { handleEvent(JSON.parse(m.data)); } catch (e) { console.error(e, m.data); }
    };
    stream.onerror = () => { /* EventSource auto-reconnects */ };
    $('submit').disabled = queue.length === 0;
  }
```

- [ ] **Step 3: Update `historyRedl` to the new shape.**

Find `historyRedl` (line ~2435). Replace its body:

```js
  async function historyRedl(entry) {
    await submitJob({
      rows: [{ url: entry.url, format: entry.format || defaultFormat }],
      output_dir: $('output_dir').value,
      playlist: $('playlist').checked,
      force: $('force').checked,
      fragments: parseInt($('fragments').value, 10),
      clearQueueOnSuccess: false,
    });
  }
```

- [ ] **Step 4: Manual smoke — full happy path.**

```bash
audio-dl-ui --no-browser --port 9099 &
sleep 1
open http://127.0.0.1:9099/
```

Steps:
1. Paste 3 URLs in different formats — verify rows commit with the right pickers.
2. Click `[ SUBMIT 3 ]` — verify the request fires, cards appear in In Flight, and the queue clears.
3. Wait for completion; verify each file ended up in the right format (e.g., `~/Downloads/audio-dl/title.m4a` vs `title.mp4`).
4. From History, click re-download on a row — verify it submits with the entry's format.
5. Click `clear all` with a populated queue — verify it empties; click again — no-op.
6. Click `set all rows → default` — verify every row's picker flips.

Kill the server with `kill %1`.

- [ ] **Step 5: Run the full suite.**

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add audio_dl_ui.py
git commit -m "feat: bulk actions + per-URL submit body + history re-download path"
```

---

## Task 9: JS — In Flight card format chip

**Goal:** Each In Flight card shows its format (m4a / mp4 / flac / …) populated from snapshot + `url_started`.

**Files:**
- Modify: `audio_dl_ui.py` (`_INDEX_JS`).

- [ ] **Step 1: Locate `renderCard` and add chip population.**

Find `renderCard` (search for the function — likely after `upsertCard`, around line 2190). Inside, after the existing badge/title/meta updates, add:

```js
    // Format chip — populated once from urlMeta or snapshot media_format.
    const chip = el.querySelector('.card-format-chip');
    const fmt = (urlMeta[url] && urlMeta[url].format) || (st && st.media_format) || '';
    if (fmt) {
      chip.textContent = fmt.toUpperCase();
      const kind =
        ['flac','alac','wav'].includes(fmt) ? 'lossless' :
        fmt === 'mp4' ? 'video' : 'lossy';
      chip.setAttribute('data-kind', kind);
    } else {
      chip.textContent = '';
      chip.removeAttribute('data-kind');
    }
```

- [ ] **Step 2: Wire snapshot `media_format` into `cardState`.**

Find the `job_snapshot` handler (line ~2537). In the per-URL assignment block (line ~2549 — the `cardState[u.url] = {...}` literal), add `media_format: u.media_format` to the assigned object:

```js
        cardState[u.url] = {
          url_idx: i,
          phase,
          media_format: u.media_format,  // v1.9
          title: u.title, uploader: u.uploader, duration: u.duration,
          thumbnail_ready: u.thumbnail_ready, log: u.log || [],
          percent: u.percent, speed: u.speed, eta: u.eta,
          downloaded_bytes: u.downloaded_bytes, total_bytes: u.total_bytes,
          paths: u.paths,
        };
```

Also seed `urlMeta` from the snapshot so a late-reconnect renders the chip on the first cycle (the `renderCard` lookup checks `urlMeta` first):

Right after the loop populating `cardState` from `ev.urls`, add (still inside the snapshot branch):

```js
        for (const u of ev.urls) {
          urlMeta[u.url] = urlMeta[u.url] || {};
          if (u.media_format && !urlMeta[u.url].format) {
            urlMeta[u.url].format = u.media_format;
          }
        }
```

- [ ] **Step 3: Manual smoke — submit a mixed job, refresh mid-flight.**

```bash
audio-dl-ui --no-browser --port 9099 &
sleep 1
open http://127.0.0.1:9099/
```

Submit 3 URLs in different formats. Refresh the browser mid-flight. Verify each card shows the right chip (M4A / MP4 / FLAC), color-bucketed by lossy/lossless/video.

- [ ] **Step 4: Run the suite.**

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add audio_dl_ui.py
git commit -m "feat: In Flight card format chip, snapshot-aware"
```

---

## Task 10: Version bumps + CHANGELOG

**Files:**
- Modify: `audio_dl.py` (`__version__`).
- Modify: `pyproject.toml` (`version`).
- Modify: `CHANGELOG.md`.

- [ ] **Step 1: Bump version in `audio_dl.py`.**

In `audio_dl.py` at line 31, change `__version__ = "1.8.0"` to `__version__ = "1.9.0"`.

- [ ] **Step 2: Bump version in `pyproject.toml`.**

Search for the `version` line and change it to `1.9.0`. Match the line currently in use:

```bash
grep -n "^version" pyproject.toml
```

- [ ] **Step 3: Add CHANGELOG entry.**

Open `CHANGELOG.md` and add a new section at the top under the heading, before the current `## v1.8.0` block:

```markdown
## v1.9.0

- **Per-URL format.** The new-job form is now a row builder: each URL has
  its own format dropdown. Pasting a multi-line list splits into rows, and
  a trailing format token (`mp3`, `m4a`, `flac`, `alac`, `opus`, `wav`,
  `mp4`) on a line strips off the URL and pre-fills that row's picker.
- **Default-format strip** beneath the queue with `set all rows → default`
  and `clear all` bulk actions.
- **In Flight cards** gain a format chip in the header, color-bucketed by
  lossy / lossless / video to match the History row badges.
- **POST /jobs body shape changed** (breaking): top-level `format` is
  removed; `urls` is now a `list[{url, format}]`. The vestigial top-level
  `jobs` field is also removed. The UI is the only client; CLI behavior
  is unchanged.
- **Snapshot** events gain `default_format` at the top level and
  `media_format` per URL entry.
```

- [ ] **Step 4: Verify versions match.**

```bash
grep -E "^__version__|^version" audio_dl.py pyproject.toml
```

Expected: both show `1.9.0`.

- [ ] **Step 5: Run the suite + lint.**

```bash
pytest -q
pylint $(git ls-files '*.py')
```

Expected: pytest green; pylint clean. (Pylint complaints introduced by the new code should be fixed inline — e.g., long lines, missing docstrings on `UrlSpec`.)

- [ ] **Step 6: Commit.**

```bash
git add audio_dl.py pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 1.9.0 + CHANGELOG"
```

---

## Task 11: Open draft PR + transition to ready

**Files:** none (git/GH only).

- [ ] **Step 1: Push the branch.**

```bash
git push -u origin v1.9-per-url-format
```

- [ ] **Step 2: Open a draft PR.**

```bash
gh pr create --draft --title "v1.9.0 — per-URL format / single-screen row builder" --body "$(cat <<'EOF'
## Summary

- Each queued URL carries its own target format, picked in the form before submit.
- New-job form is a row builder; paste splits into rows; trailing format token pre-fills the picker.
- Default-format strip with `set all → default` and `clear all`.
- In Flight cards get a format chip; History row badge unchanged.
- POST /jobs body becomes `{urls: [{url, format}, ...]}`; top-level `format` and vestigial `jobs` removed.

Spec: docs/superpowers/specs/2026-05-19-per-url-format-design.md

## Test plan

- [ ] `pytest` green on 3.10–3.13 in CI
- [ ] `pylint` clean
- [ ] Manually verified the spec's paste-table outcomes
- [ ] Manually verified mixed-format batch produces correct file extensions
- [ ] Manually verified browser refresh mid-flight rebuilds cards with right chip
- [ ] Manually verified History re-download produces the same format

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Wait for CI green, then mark ready-for-review.**

```bash
gh pr checks --watch
gh pr ready
```

Codex review fires on the draft→ready transition.

- [ ] **Step 4: Report PR URL to the user.**

---

## Self-Review Notes

(Done while writing — fixes already inline.)

- **Spec coverage:** every locked decision (#1–#13 in the spec) maps to a task above. #1 → Task 4; #2–4 → Tasks 4+6+7; #5 → Task 7; #6 → Tasks 4+6; #7 → Tasks 4+8; #8 → Task 6; #9 → Task 6; #10 → Tasks 4+9; #11 → Task 1; #12 → Task 1; #13 → Task 8.
- **Snapshot shape:** the spec's example uses `url_states: {url: {...}}` (dict) but the actual code uses `urls: [{...}]` (list). Plan keeps the list shape and adds `media_format` per entry; reader on the JS side already iterates the list.
- **`JobState.jobs` removal:** spec only removes the request field; the dataclass field was unread post-v1.8 so we drop it too. Tests that set or assert `job.jobs` are updated in Task 1 Step 5.
- **`UrlState.media_format` is required (no default).** Empty-string would mask validation failures and produce mid-job errors. Direct-construction tests are migrated explicitly in Task 1 Step 3.
- **Task 1 spans schema + dataclass field by design.** `post_jobs` constructs `UrlState(url=..., media_format=...)` which only compiles after the field exists; splitting these across two commits would leave a broken intermediate. Task 2 (single line in `_run_one`) is the smallest follow-up that keeps the test suite green at every commit.
- **JS paste-handler edge case:** single-line paste (no `\n`) falls through to native input behavior — otherwise the user can't edit a single URL inside the input row without it auto-splitting. Spec didn't pin this down; the plan picks this behavior and notes it in Task 7 Step 1.
- **JS ALL_FORMATS source:** hardcoded to a 7-item Set on the client mirroring `audio_dl.py`. If a new format ever lands in `ALL_FORMATS`, both must update — already true today for the `__FORMAT_OPTIONS__` template path.

## Done criteria

(Verbatim from spec, restated for execution-time confirmation.)

- `audio-dl-ui` launches; form shows the row-builder layout matching the spec mockup.
- Pasting `https://yt.com/abc\nhttps://yt.com/xyz mp4` commits two rows; the second has `mp4` pre-selected.
- Typing `https://yt.com/qrs` + ↵ commits a row with the default format.
- Each row's dropdown changes only that row's format.
- `set all rows → default` overrides every row.
- Submitting a mixed-format batch produces N downloads each in the right format.
- In Flight cards show the right format chip per URL.
- Refreshing the browser mid-submission rebuilds cards with the right chip.
- History entries retain their per-URL format on re-download.
- `POST /jobs` with old `{urls: "...", format: "..."}` returns 422.
- `POST /jobs` with `[{url, format: "mp3x"}]` returns 400 naming the bad format.
- `pytest` green, `pylint` clean.
- CHANGELOG has a v1.9.0 section; both version sources match.
