"""PyInstaller entry-point shim for the audio-dl macOS .app bundle.

Two reasons for the shim instead of pointing PyInstaller at
``audio_dl_ui:main`` directly:

1. LaunchServices on older macOS can inject ``-psn_NNN_MMM`` or similar
   Finder process-serial-number flags into argv when an app is launched
   from the GUI. ``audio_dl_ui:main`` uses ``argparse`` and would reject
   them. This shim strips just those flags, preserving real CLI args
   (e.g., ``--no-browser``) so the bundled binary can be driven headless.

2. A GUI-launched ``.app`` does NOT inherit the user's shell ``PATH``.
   Homebrew prefixes (``/opt/homebrew/bin`` on Apple Silicon,
   ``/usr/local/bin`` on Intel) are missing, so ``shutil.which("ffmpeg")``
   would fail even on a Mac where the tester has installed ffmpeg.
   ``_bootstrap_homebrew_path`` fixes that, so the dep check and any
   yt-dlp subprocess use the same ffmpeg the tester sees in a terminal.

Importing this module has no side effects. Module-level code only runs
when launched as ``__main__`` (i.e., by the PyInstaller bootloader).
"""
from __future__ import annotations

import os
import sys


# Homebrew install prefixes, in priority order. Apple Silicon first because
# audio-dl Phase 3a only targets modern macOS (LSMinimumSystemVersion = 11.0
# Big Sur); Intel /usr/local/bin still wins on Rosetta-bridged setups.
_HOMEBREW_PATHS = ("/opt/homebrew/bin", "/usr/local/bin")


def _bootstrap_homebrew_path(env: dict[str, str] | None = None) -> None:
    """Prepend Homebrew bin directories to ``$PATH`` so GUI launches find ffmpeg.

    Idempotent. Operates on ``os.environ`` by default; tests pass a fake env.
    Only prepends paths that are missing — preserves the user's existing
    PATH ordering when they overlap.
    """
    target = os.environ if env is None else env
    current = target.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    for prefix in reversed(_HOMEBREW_PATHS):
        if prefix not in parts:
            parts.insert(0, prefix)
    target["PATH"] = os.pathsep.join(parts)


def _main() -> None:
    """Strip Finder-injected -psn_* argv, bootstrap PATH, delegate to audio_dl_ui.main.

    LaunchServices injects -psn_NNN_MMM (Finder process-serial-number) when
    a .app is launched via double-click. argparse in audio_dl_ui.main would
    reject those. We drop just those args, preserving real flags like
    --no-browser so the bundle can be driven headless (e.g., CI smoke test).
    """
    sys.argv = [arg for arg in sys.argv if not arg.startswith("-psn_")]
    # The PATH bootstrap is only meaningful when launched from a GUI context
    # (PyInstaller frozen bundle, Finder double-click). Running this shim
    # directly from a terminal also calls _bootstrap_homebrew_path, but it's
    # idempotent and any user with these prefixes already on PATH is a no-op.
    _bootstrap_homebrew_path()
    # Import inside the function so ``import _app_entry`` from tests does not
    # pull in fastapi/uvicorn at module-load time.
    from audio_dl_ui import main  # pylint: disable=import-outside-toplevel
    main()


if __name__ == "__main__":
    _main()
