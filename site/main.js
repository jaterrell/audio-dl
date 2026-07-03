/* audio-dl landing — terminal typing demo, copy buttons, scroll reveals */
(function () {
  "use strict";

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- scroll reveals ---------- */
  var revealEls = document.querySelectorAll(".reveal");
  if (!reducedMotion && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.12 });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------- copy buttons ---------- */
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    var hint = btn.querySelector(".copy-hint");
    var original = hint ? hint.textContent : "";
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(btn.getAttribute("data-copy")).then(function () {
        btn.classList.add("copied");
        if (hint) hint.textContent = "copied";
        setTimeout(function () {
          btn.classList.remove("copied");
          if (hint) hint.textContent = original;
        }, 1600);
      });
    });
  });

  /* ---------- latest release version (single source: GitHub releases) ---------- */
  var ver = document.getElementById("ver");
  if (ver) {
    fetch("https://api.github.com/repos/jaterrell/audio-dl/releases/latest")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (rel) {
        if (rel && typeof rel.tag_name === "string" && /^v[\d.]+$/.test(rel.tag_name)) {
          ver.textContent = " · " + rel.tag_name;
        }
      })
      .catch(function () { /* omit version on failure */ });
  }

  /* ---------- terminal typing demo ---------- */
  var term = document.getElementById("term");
  if (!term) return;

  // [text, cssClass, mode] — mode "type" types char-by-char, "print" appears at once
  var SCRIPT = [
    ["$ ", "t-prompt", "print"],
    ["audio-dl https://soundcloud.com/artist/shadow -f flac", "", "type"],
    ["\n", "", "print"],
    ["▸ soundcloud · resolving…", "t-dim", "print"],
    ["\n", "", "print"],
    ["▸ Chromatics — Shadow", "t-accent", "print"],
    ["\n", "", "print"],
    ["  ████████████████████████ 100%   4.2 MiB/s", "", "bar"],
    ["\n", "", "print"],
    ["  embedding cover art + tags…", "t-dim", "print"],
    ["\n", "", "print"],
    ["✓ Shadow.flac → ~/Music", "t-ok", "print"],
    ["\n", "", "print"],
    ["$ ", "t-prompt", "print"],
  ];

  var cursor = document.createElement("span");
  cursor.className = "t-cursor";

  function span(cls, text) {
    var s = document.createElement("span");
    if (cls) s.className = cls;
    s.textContent = text;
    return s;
  }

  function renderAll() {
    SCRIPT.forEach(function (step) {
      term.appendChild(span(step[1], step[0]));
    });
    term.appendChild(cursor);
  }

  if (reducedMotion) {
    renderAll();
    return;
  }

  term.appendChild(cursor);

  var i = 0;
  function next() {
    if (i >= SCRIPT.length) return;
    var step = SCRIPT[i++];
    var text = step[0], cls = step[1], mode = step[2];

    if (mode === "type") {
      var target = span(cls, "");
      term.insertBefore(target, cursor);
      var j = 0;
      (function typeChar() {
        target.textContent += text[j++];
        if (j < text.length) {
          setTimeout(typeChar, 26 + Math.random() * 40);
        } else {
          setTimeout(next, 320);
        }
      })();
    } else if (mode === "bar") {
      // progress bar fills block-by-block, percent counts up
      var bar = span(cls, "  ");
      term.insertBefore(bar, cursor);
      var blocks = 24, b = 0;
      (function fill() {
        b++;
        var pct = Math.round((b / blocks) * 100);
        bar.textContent = "  " + "█".repeat(b) + "░".repeat(blocks - b) +
          " " + String(pct).padStart(3) + "%   4.2 MiB/s";
        if (b < blocks) {
          setTimeout(fill, 55);
        } else {
          setTimeout(next, 260);
        }
      })();
    } else {
      term.insertBefore(span(cls, text), cursor);
      setTimeout(next, text === "\n" ? 60 : 300);
    }
  }

  // start once the terminal scrolls into view (it's above the fold on load)
  var started = false;
  function start() {
    if (started) return;
    started = true;
    setTimeout(next, 700);
  }
  if ("IntersectionObserver" in window) {
    var tio = new IntersectionObserver(function (entries) {
      if (entries.some(function (e) { return e.isIntersecting; })) {
        start();
        tio.disconnect();
      }
    }, { threshold: 0.3 });
    tio.observe(term);
  } else {
    start();
  }
})();
