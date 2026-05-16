# Per-theme card variations (v1.7) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the v1.6 per-theme override pattern to `.card` selectors. Three cluster-scoped CSS blocks (vintage / editorial / modern) layered on top of the shared card CSS, plus a one-line JS addition for the modern cluster's duration overlay.

**Architecture:** All variation is pure CSS authored as grouped selectors (`[data-theme="amber"] .card, [data-theme="solarized"] .card, [data-theme="gruvbox"] .card { ... }`) appended to `_INDEX_CSS_THEMES`. The card template and card-rendering JS stay cluster-agnostic; one new `setAttribute('data-duration', ...)` call exposes duration to the modern cluster's `::after` overlay. No backend, SSE, or `UrlState` changes.

**Tech Stack:** Python 3.10+, FastAPI, vanilla CSS/JS, pytest.

**Spec:** [docs/superpowers/specs/2026-05-16-per-theme-card-variations-design.md](../specs/2026-05-16-per-theme-card-variations-design.md)

---

## File Structure

| File | Action | Why |
|---|---|---|
| [audio_dl_ui.py](../../../audio_dl_ui.py) | Modify | Append ~120 LOC cluster CSS to `_INDEX_CSS_THEMES` (ends at line 1593, before `"""`). Add one `setAttribute` line to `renderCard` JS (around line 1874). Bump constant `__version__` propagation if any. |
| [test_audio_dl_ui.py](../../../test_audio_dl_ui.py) | Modify | Add `TestCardClusterOverrides` class after the existing `TestThemeRendering` (currently ends ~line 1168). 7 new tests. |
| [audio_dl.py](../../../audio_dl.py) | Modify | Bump `__version__ = "1.7"`. |
| [pyproject.toml](../../../pyproject.toml) | Modify | Bump `version = "1.7"`. |
| [CHANGELOG.md](../../../CHANGELOG.md) | Modify | Prepend `## v1.7 — Per-theme card structural variations` section. |
| [CLAUDE.md](../../../CLAUDE.md) | Modify | Append a Conventions bullet documenting the cluster-CSS-only / no-JS-cluster-branching discipline. Link this spec. |

No new files. No new dependencies. PyInstaller spec, release pipeline, and SSE protocol untouched.

---

## Pre-flight (do before any task)

- [ ] **Confirm current state.** Run from repo root:

  ```bash
  pytest -x test_audio_dl_ui.py 2>&1 | tail -5
  ```

  Expected: all tests pass (this is the v1.6 baseline).

- [ ] **Note current line numbers** (these may drift by ±10 as work proceeds; use them as anchors, not absolutes):
  - `audio_dl_ui.py:1017` — `_INDEX_CSS_THEMES = """...`
  - `audio_dl_ui.py:1593` — closing `"""` of `_INDEX_CSS_THEMES`
  - `audio_dl_ui.py:1864` — `function renderCard(url) {`
  - `audio_dl_ui.py:1874` — `if (st.duration) metaParts.push(formatDuration(st.duration));`
  - `test_audio_dl_ui.py:1125` — `class TestThemeRendering:`
  - `test_audio_dl_ui.py:1168` — end of `TestThemeRendering` (insertion point for new class)

---

## Task 1: Phosphor-untouched sanity test

Guards the v1.6-byte-identical invariant for the phosphor card.

**Files:**
- Modify: `test_audio_dl_ui.py` (insert new class after `TestThemeRendering`, around line 1168)

- [ ] **Step 1: Insert the new test class and its first test**

  Insert immediately after the closing of `TestThemeRendering` (before the `# ---` separator at ~line 1170):

  ```python
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
  ```

- [ ] **Step 2: Run the test to confirm it passes (no impl needed — current state has no phosphor .card rules)**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides::test_phosphor_has_no_card_override -v
  ```

  Expected: `1 passed`.

- [ ] **Step 3: Commit**

  ```bash
  git add test_audio_dl_ui.py
  git commit -m "test(ui): phosphor-no-card-override sanity test (v1.7 prep)"
  ```

---

## Task 2: Vintage cluster CSS (amber · solarized · gruvbox)

Dotted borders, uppercase, dithered thumb, segmented progress bar, `>` log prefix.

**Files:**
- Modify: `test_audio_dl_ui.py` (add test inside `TestCardClusterOverrides`)
- Modify: `audio_dl_ui.py` (append to `_INDEX_CSS_THEMES`, before its closing `"""`)

- [ ] **Step 1: Write the failing test**

  Add inside `TestCardClusterOverrides` (after `test_phosphor_has_no_card_override`):

  ```python
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
  ```

- [ ] **Step 2: Run the test to verify it fails**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides::test_vintage_cluster_card_block_present -v
  ```

  Expected: `1 failed` — `AssertionError: Vintage cluster grouped .card selector missing`.

- [ ] **Step 3: Implement the vintage cluster CSS**

  Open `audio_dl_ui.py`, locate the closing `"""` of `_INDEX_CSS_THEMES` (currently ~line 1593, right before `_INDEX_HTML_BODY = """...`). Insert this block **before** the closing `"""`, keeping the existing 2-space indentation pattern used throughout `_INDEX_CSS_THEMES`:

  ```css
    /* ===========================================================
       v1.7 — Per-theme card structural variations (cluster-scoped)
       Phosphor uses base .card rules unchanged.
       Do NOT override at the cluster level:
         - display: rules on .card-progress / .card-log (state CSS owns these)
         - --ok / --err on .card-badge (state CSS owns these)
         - animation properties on .card-badge::after
       =========================================================== */

    /* --- VINTAGE cluster (amber · solarized · gruvbox) ---------- */
    [data-theme="amber"] .card,
    [data-theme="solarized"] .card,
    [data-theme="gruvbox"] .card {
      border-style: dotted;
      letter-spacing: 0.04em;
    }
    [data-theme="amber"] .card-title,
    [data-theme="solarized"] .card-title,
    [data-theme="gruvbox"] .card-title,
    [data-theme="amber"] .card-meta,
    [data-theme="solarized"] .card-meta,
    [data-theme="gruvbox"] .card-meta {
      text-transform: uppercase;
    }
    [data-theme="amber"] .card-thumb,
    [data-theme="solarized"] .card-thumb,
    [data-theme="gruvbox"] .card-thumb {
      border-style: dotted;
    }
    [data-theme="amber"] .card-thumb img,
    [data-theme="solarized"] .card-thumb img,
    [data-theme="gruvbox"] .card-thumb img {
      filter: grayscale(0.7) contrast(1.2);
    }
    [data-theme="amber"] .card-bar > span,
    [data-theme="solarized"] .card-bar > span,
    [data-theme="gruvbox"] .card-bar > span {
      background-image: repeating-linear-gradient(
        90deg,
        rgba(0, 0, 0, 0.35) 0 2px,
        transparent 2px 5px
      );
    }
    [data-theme="amber"] .card-log-line::before,
    [data-theme="solarized"] .card-log-line::before,
    [data-theme="gruvbox"] .card-log-line::before {
      content: "> ";
      color: var(--dim);
    }
  ```

- [ ] **Step 4: Run the test to verify it passes**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides -v
  ```

  Expected: `2 passed` (phosphor sanity + vintage block present).

- [ ] **Step 5: Confirm no existing tests broke**

  ```bash
  pytest -x test_audio_dl_ui.py 2>&1 | tail -3
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add test_audio_dl_ui.py audio_dl_ui.py
  git commit -m "feat(ui): v1.7 vintage cluster — dotted, uppercase, dithered thumb"
  ```

---

## Task 3: Editorial cluster CSS (rose · moon · dawn)

Border-bottom only, serif title, italic byline, thin progress bar, italic log lines. Dawn-specific hide is a separate task.

**Files:**
- Modify: `test_audio_dl_ui.py` (add test inside `TestCardClusterOverrides`)
- Modify: `audio_dl_ui.py` (append below the vintage block in `_INDEX_CSS_THEMES`)

- [ ] **Step 1: Write the failing test**

  Add inside `TestCardClusterOverrides` (after `test_vintage_cluster_card_block_present`):

  ```python
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
  ```

- [ ] **Step 2: Run the test to verify it fails**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides::test_editorial_cluster_card_block_present -v
  ```

  Expected: `1 failed`.

- [ ] **Step 3: Implement the editorial cluster CSS**

  Append directly below the vintage cluster block in `_INDEX_CSS_THEMES`:

  ```css
    /* --- EDITORIAL cluster (rose · moon · dawn) ----------------- */
    [data-theme="rose"] .card,
    [data-theme="moon"] .card,
    [data-theme="dawn"] .card {
      border: none;
      border-bottom: 1px solid var(--frame);
      padding: 16px 14px;
      background: transparent;
    }
    [data-theme="rose"] .card-title,
    [data-theme="moon"] .card-title,
    [data-theme="dawn"] .card-title {
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.05em;
      font-weight: 700;
    }
    [data-theme="rose"] .card-meta,
    [data-theme="moon"] .card-meta,
    [data-theme="dawn"] .card-meta {
      font-style: italic;
    }
    [data-theme="rose"] .card-bar,
    [data-theme="moon"] .card-bar,
    [data-theme="dawn"] .card-bar {
      height: 3px;
      border: none;
      border-radius: 2px;
      background: color-mix(in srgb, var(--frame) 50%, transparent);
    }
    [data-theme="rose"] .card-log-line,
    [data-theme="moon"] .card-log-line,
    [data-theme="dawn"] .card-log-line {
      font-style: italic;
      font-size: 0.85em;
    }
  ```

- [ ] **Step 4: Run the test to verify it passes**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides -v
  ```

  Expected: `3 passed`.

- [ ] **Step 5: Confirm no existing tests broke**

  ```bash
  pytest -x test_audio_dl_ui.py 2>&1 | tail -3
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add test_audio_dl_ui.py audio_dl_ui.py
  git commit -m "feat(ui): v1.7 editorial cluster — serif title, italic byline, border-bottom"
  ```

---

## Task 4: Dawn thumb hide

Dawn is the editorial light theme; it gets a unique additional rule that hides the thumbnail entirely and collapses the card to a 1-column grid.

**Files:**
- Modify: `test_audio_dl_ui.py` (add test inside `TestCardClusterOverrides`)
- Modify: `audio_dl_ui.py` (append below the editorial block in `_INDEX_CSS_THEMES`)

- [ ] **Step 1: Write the failing test**

  Add inside `TestCardClusterOverrides`:

  ```python
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
  ```

- [ ] **Step 2: Run the tests to verify they fail**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides::test_dawn_card_thumb_hidden test_audio_dl_ui.py::TestCardClusterOverrides::test_dawn_card_grid_collapses_to_single_column -v
  ```

  Expected: `2 failed`.

- [ ] **Step 3: Implement the dawn-specific overrides**

  Append directly below the editorial cluster block in `_INDEX_CSS_THEMES`:

  ```css
    /* Dawn (editorial light) — hide thumb entirely, collapse grid */
    [data-theme="dawn"] .card {
      grid-template-columns: 1fr;
    }
    [data-theme="dawn"] .card-thumb {
      display: none;
    }
  ```

- [ ] **Step 4: Run the tests to verify they pass**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides -v
  ```

  Expected: `5 passed`.

- [ ] **Step 5: Confirm no existing tests broke**

  ```bash
  pytest -x test_audio_dl_ui.py 2>&1 | tail -3
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add test_audio_dl_ui.py audio_dl_ui.py
  git commit -m "feat(ui): v1.7 dawn — hide thumb, collapse grid to single column"
  ```

---

## Task 5: Modern cluster CSS (tokyo · atom · claude)

Top-full thumb with duration overlay, uppercase uploader-as-label above title via `order: -1`, rounded corners, thin progress bar.

**Files:**
- Modify: `test_audio_dl_ui.py` (add tests inside `TestCardClusterOverrides`)
- Modify: `audio_dl_ui.py` (append below dawn rules in `_INDEX_CSS_THEMES`)

- [ ] **Step 1: Write the failing tests**

  Add inside `TestCardClusterOverrides`:

  ```python
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

      def test_modern_cluster_meta_reordered_above_title(self):
          """Modern cluster lifts .card-meta above .card-title using CSS order."""
          from audio_dl_ui import _INDEX_CSS_THEMES
          pattern = (
              r'\[data-theme="(?:tokyo|atom|claude)"\]\s*\.card-meta\s*\{[^}]*order:\s*-1'
          )
          matches = re.findall(pattern, _INDEX_CSS_THEMES)
          assert len(matches) >= 3, (
              f"Expected order: -1 on .card-meta for all 3 modern themes — found {len(matches)}"
          )
  ```

- [ ] **Step 2: Run the tests to verify they fail**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides -v 2>&1 | tail -15
  ```

  Expected: 3 new tests fail (modern block, duration overlay, meta order).

- [ ] **Step 3: Implement the modern cluster CSS**

  Append directly below the dawn rules in `_INDEX_CSS_THEMES`:

  ```css
    /* --- MODERN cluster (tokyo · atom · claude) ----------------- */
    [data-theme="tokyo"] .card,
    [data-theme="atom"] .card,
    [data-theme="claude"] .card {
      border-radius: 10px;
      grid-template-columns: 1fr;
      grid-template-rows: auto auto;
      gap: 10px;
    }
    [data-theme="tokyo"] .card-thumb,
    [data-theme="atom"] .card-thumb,
    [data-theme="claude"] .card-thumb {
      width: 100%;
      height: 100px;
      border-radius: 6px;
      position: relative;
    }
    [data-theme="tokyo"] .card-thumb::after,
    [data-theme="atom"] .card-thumb::after,
    [data-theme="claude"] .card-thumb::after {
      content: attr(data-duration);
      position: absolute;
      top: 6px;
      right: 6px;
      background: rgba(0, 0, 0, 0.5);
      color: #fff;
      font-family: ui-monospace, "JetBrains Mono", monospace;
      font-size: 0.7em;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 3px;
    }
    [data-theme="tokyo"] .card-thumb[data-duration=""]::after,
    [data-theme="atom"] .card-thumb[data-duration=""]::after,
    [data-theme="claude"] .card-thumb[data-duration=""]::after {
      display: none;
    }
    [data-theme="tokyo"] .card-meta,
    [data-theme="atom"] .card-meta,
    [data-theme="claude"] .card-meta {
      order: -1;
      text-transform: uppercase;
      font-size: 0.7em;
      font-weight: 600;
      letter-spacing: 0.08em;
      color: var(--accent);
    }
    [data-theme="tokyo"] .card-bar,
    [data-theme="atom"] .card-bar,
    [data-theme="claude"] .card-bar {
      height: 3px;
      border: none;
      border-radius: 2px;
    }
  ```

  Note: the `display: none` on the empty-`data-duration` selector IS allowed despite the "no display overrides" rule from the spec — that rule applies to `.card-progress` and `.card-log` (state-driven children), not `.card-thumb::after`.

- [ ] **Step 4: Run the new tests to verify they pass**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides -v
  ```

  Expected: `8 passed`.

- [ ] **Step 5: Confirm no existing tests broke**

  ```bash
  pytest -x test_audio_dl_ui.py 2>&1 | tail -3
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add test_audio_dl_ui.py audio_dl_ui.py
  git commit -m "feat(ui): v1.7 modern cluster — top-full thumb, duration overlay, label-above-title"
  ```

---

## Task 6: JS — set `data-duration` attribute in renderCard

Without this, the modern cluster's `::after` overlay reads `attr(data-duration)` as empty and stays hidden (because of the `[data-duration=""]::after { display: none }` rule). One line of JS unlocks the overlay.

**Files:**
- Modify: `test_audio_dl_ui.py` (add test inside `TestCardClusterOverrides`)
- Modify: `audio_dl_ui.py` (`renderCard` function in `_INDEX_JS`, around line 1874)

- [ ] **Step 1: Write the failing test**

  Add inside `TestCardClusterOverrides`:

  ```python
      def test_render_card_sets_data_duration_attribute(self):
          """renderCard must set data-duration on .card-thumb so the modern
          cluster's ::after overlay can read it via attr(). Accept either
          single- or double-quoted attribute name."""
          from audio_dl_ui import _INDEX_JS
          assert (
              "setAttribute('data-duration'" in _INDEX_JS
              or 'setAttribute("data-duration"' in _INDEX_JS
          ), "renderCard must call setAttribute('data-duration', ...) on .card-thumb"
  ```

- [ ] **Step 2: Run the test to verify it fails**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides::test_render_card_sets_data_duration_attribute -v
  ```

  Expected: `1 failed`.

- [ ] **Step 3: Add the `setAttribute` line in renderCard**

  Open `audio_dl_ui.py` and find the `renderCard` function (around line 1864). Locate the existing duration handling:

  ```js
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
  ```

  Add this single line **after** the closing brace of the `if/else` block above (so the attribute is set in both branches, falling back to `""` when duration is unknown):

  ```js
      el.querySelector('.card-thumb').setAttribute('data-duration', st.duration ? formatDuration(st.duration) : '');
  ```

  The placement matters: it runs regardless of whether metadata has arrived, so a card in the `queued` or `resolving` phase has `data-duration=""` and the modern cluster's `[data-duration=""]::after { display: none }` rule keeps the overlay hidden until duration is known.

- [ ] **Step 4: Run the test to verify it passes**

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides::test_render_card_sets_data_duration_attribute -v
  ```

  Expected: `1 passed`.

- [ ] **Step 5: Confirm no existing tests broke**

  ```bash
  pytest -x test_audio_dl_ui.py 2>&1 | tail -3
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add test_audio_dl_ui.py audio_dl_ui.py
  git commit -m "feat(ui): v1.7 — renderCard sets data-duration for modern cluster overlay"
  ```

---

## Task 7: Forbidden-override sanity test

A regression net for the "cluster CSS doesn't touch state-managed display rules" discipline. Cheap to run, hard to violate accidentally without it failing.

**Files:**
- Modify: `test_audio_dl_ui.py` (add test inside `TestCardClusterOverrides`)

- [ ] **Step 1: Write the test**

  Add inside `TestCardClusterOverrides`:

  ```python
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
  ```

- [ ] **Step 2: Run the tests to verify they pass**

  (No implementation needed — the v1.7 CSS already honors the discipline. These tests guard the invariant for future edits.)

  ```bash
  pytest test_audio_dl_ui.py::TestCardClusterOverrides -v
  ```

  Expected: all `TestCardClusterOverrides` tests pass (`11 passed`).

- [ ] **Step 3: Confirm full test suite stays green**

  ```bash
  pytest -x test_audio_dl_ui.py 2>&1 | tail -3
  pytest -x test_audio_dl.py 2>&1 | tail -3
  ```

  Expected: both pass cleanly.

- [ ] **Step 4: Commit**

  ```bash
  git add test_audio_dl_ui.py
  git commit -m "test(ui): v1.7 — guard cluster CSS from touching state-managed display/color"
  ```

---

## Task 8: Version bump + CHANGELOG + CLAUDE.md convention bullet

Mechanical release housekeeping per [CLAUDE.md](../../../CLAUDE.md) release flow.

**Files:**
- Modify: `audio_dl.py` (`__version__`)
- Modify: `pyproject.toml` (`version`)
- Modify: `CHANGELOG.md` (prepend v1.7 section)
- Modify: `CLAUDE.md` (append Conventions bullet)

- [ ] **Step 1: Bump `__version__` in `audio_dl.py`**

  Find the existing `__version__` line (search: `__version__ =`). Change:

  ```python
  __version__ = "1.6"
  ```

  to:

  ```python
  __version__ = "1.7"
  ```

- [ ] **Step 2: Bump `version` in `pyproject.toml`**

  Find the `version = "1.6"` line under `[project]`. Change to:

  ```toml
  version = "1.7"
  ```

- [ ] **Step 3: Prepend v1.7 entry to `CHANGELOG.md`**

  Open `CHANGELOG.md`. Locate the existing top entry (`## v1.6 — ...`). Insert a new section **above** it:

  ```markdown
  ## v1.7 — Per-theme card structural variations

  Cards now express each cluster's structural identity, not just its color palette.

  - **Vintage cluster (amber · solarized · gruvbox):** dotted card + thumb borders, uppercase title and uploader, dithered/grayscale thumb filter, segmented progress bar via repeating-gradient, `>` log-line prefix.
  - **Editorial cluster (rose · moon · dawn):** border-bottom only (no full box), serif title (Georgia), italic byline, thin rounded progress bar, italic log lines. Dawn additionally hides the thumb and collapses the card to a single-column grid.
  - **Modern cluster (tokyo · atom · claude):** rounded 10px card with top-full-width thumb, duration overlay in the thumb's top-right corner, uppercase uploader-as-label *above* the title via CSS `order`, thin rounded progress bar.
  - **Phosphor (default):** unchanged — remains the v1.6 reference card.

  Implementation is pure CSS layered on the v1.6 card structure plus one new `setAttribute('data-duration')` call in `renderCard` to expose duration to the modern cluster's `::after` overlay. No backend, SSE, or `UrlState` changes.

  Spec: `docs/superpowers/specs/2026-05-16-per-theme-card-variations-design.md`

  ```

- [ ] **Step 4: Append the Conventions bullet to `CLAUDE.md`**

  Open `CLAUDE.md`. Find the Conventions list — the existing list ends with the "Rich cards (v1.6)" bullet. Append immediately after it:

  ```markdown
  - Per-theme card variations (v1.7): card-level theme overrides are
    **cluster-scoped CSS only**. Card-rendering JS in `_INDEX_JS` stays
    cluster-agnostic — modern's duration overlay reads a `data-duration`
    attribute set unconditionally on every render (empty string when
    unknown; CSS `[data-duration=""]::after { display: none }` hides it).
    Cluster CSS must not override `display` on `.card-progress`/`.card-log`
    children or `color` on `.card-badge` — those belong to base state CSS
    and own the queued/resolving show-hide + complete/failed signaling.
    Tests in `TestCardClusterOverrides` enforce both invariants. See
    [docs/superpowers/specs/2026-05-16-per-theme-card-variations-design.md](docs/superpowers/specs/2026-05-16-per-theme-card-variations-design.md).
  ```

- [ ] **Step 5: Verify version consistency**

  ```bash
  grep -n '^__version__\|^version' audio_dl.py pyproject.toml
  ```

  Expected:
  ```
  audio_dl.py:N:__version__ = "1.7"
  pyproject.toml:M:version = "1.7"
  ```

- [ ] **Step 6: Run the full test suite**

  ```bash
  pytest 2>&1 | tail -5
  ```

  Expected: all tests pass.

- [ ] **Step 7: Run pylint at the strict bar**

  ```bash
  pylint $(git ls-files '*.py') 2>&1 | tail -3
  ```

  Expected: `Your code has been rated at 10.00/10`.

- [ ] **Step 8: Commit**

  ```bash
  git add audio_dl.py pyproject.toml CHANGELOG.md CLAUDE.md
  git commit -m "chore: bump to v1.7 — per-theme card structural variations"
  ```

---

## Final verification

Before opening the PR, validate end-to-end.

- [ ] **All tests pass**

  ```bash
  pytest -v 2>&1 | tail -10
  ```

- [ ] **Pylint 10.00/10**

  ```bash
  pylint $(git ls-files '*.py') 2>&1 | tail -3
  ```

- [ ] **Manual UI smoke (single URL is enough)**

  ```bash
  audio-dl-ui --no-browser &
  open http://127.0.0.1:8000
  ```

  Run through every theme (`⌘T` cycles); for each:
  - Card visually reflects its cluster (vintage dotted/uppercase, editorial serif/italic, modern top-thumb/rounded).
  - Phosphor card is unchanged from v1.6 (mental diff).
  - Dawn shows no thumb and the card uses full row width.
  - Tokyo/Atom/Claude cards show a duration overlay in the thumb corner once metadata loads.
  - Cards transition correctly through `queued → resolving → downloading → postprocessing → complete`.

- [ ] **Bundle build smoke (only if changing scripts/spec — not expected here)**

  Skip — this release doesn't touch `audio-dl.spec`, `_app_entry.py`, or `scripts/build-app.sh`. The release pipeline (`.github/workflows/release.yml`) will exercise the bundle build on the `v1.7.0` tag automatically.

- [ ] **Open PR** (do not push to `origin/main` directly — the spec went straight to main per the doc convention, but implementation lands via PR + squash merge)

  Use `superpowers:finishing-a-development-branch` to wrap up.

---

## Spec coverage check

Cross-reference the spec sections against the tasks:

| Spec section | Implemented by |
|---|---|
| Goal / Non-goals | All tasks (cluster-only, pure CSS, no backend) |
| Cluster membership | Task 2 (vintage), 3 (editorial), 5 (modern); phosphor untouched by Task 1's guard |
| Vintage cluster treatments | Task 2 |
| Editorial cluster treatments | Task 3 (base) + Task 4 (dawn thumb hide) |
| Modern cluster treatments | Task 5 |
| DOM / JS changes (one `setAttribute`) | Task 6 |
| Lifecycle state coverage | Tasks 2–5 honor the no-override discipline; Task 7 enforces it as a test |
| CSS specificity discipline | Task 7 |
| File changes table | Tasks 2, 3, 4, 5 (CSS), 6 (JS), 8 (version + CHANGELOG + CLAUDE.md) |
| Testing (5 spec tests) | Tasks 1, 2, 3, 4, 5, 6, 7 — adds 7 spec tests + 4 spec-derived (dawn grid, modern meta-order, badge color, multiple-display) for 11 total |
| File-size impact | Verified at end (~130 LOC added, comfortably within budget) |
| Versioning | Task 8 |
| Open follow-ups (v1.8+) | Out of scope, preserved in spec |
| Acceptance criteria | Final verification section |

No spec gaps.
