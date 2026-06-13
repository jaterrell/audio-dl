# -*- mode: python ; coding: utf-8 -*-
# pylint: disable=invalid-name,undefined-variable
"""PyInstaller spec for audio-dl.app (macOS bundle).

Build with:  scripts/build-app.sh

Phase 3a slice — dev / trusted-tester only. See
docs/superpowers/specs/2026-05-13-app-bundle.md for the rationale and the
deferred-to-3b items (codesign, notarization, embedded ffmpeg).
"""
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Single source of truth for the bundled version is audio_dl.__version__.
# Reading it via regex keeps this spec runnable without importing the package
# (PyInstaller analyzes the spec before installing into a build environment).
_VERSION_MATCH = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']',
    Path("audio_dl.py").read_text(encoding="utf-8"),
    re.M,
)
VERSION = _VERSION_MATCH.group(1) if _VERSION_MATCH else "0.0.0"

# Locate the imageio-ffmpeg static binary. Placing it in ``binaries=`` instead
# of ``datas=`` is the PyInstaller convention for executables (advisor review
# recommendation): it's processed through the binary pipeline so the exec bit
# and Mach-O signatures are handled correctly on macOS.
import imageio_ffmpeg  # noqa: E402  pylint: disable=wrong-import-position
_FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

# FastAPI / uvicorn / pydantic load plugins via importlib at runtime; static
# analysis misses pieces. Use collect_submodules instead of a hand-maintained
# hidden-imports list so the bundle stays robust across upstream releases
# without us having to chase new submodule names.
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("pydantic")
    + collect_submodules("pydantic_core")
    # Phase 3b: ffmpeg ships inside the bundle via imageio-ffmpeg. The module
    # is imported via try/except in audio_dl._find_ffmpeg, so PyInstaller's
    # static analysis would otherwise drop it.
    + ["imageio_ffmpeg"]
    # yt-dlp's EmbedThumbnail prefers pure-Python mutagen for m4a/mp3 cover art
    # and only falls back to ffprobe+ffmpeg when mutagen is missing. We ship
    # imageio-ffmpeg's ffmpeg but NOT ffprobe, so without mutagen the embed step
    # fails with "ffprobe not found" and the whole download fails at postprocess.
    # yt-dlp imports mutagen lazily, so PyInstaller can't see it statically.
    + collect_submodules("mutagen")
)

# The static ffmpeg binary goes into ``binaries=`` so PyInstaller treats it as
# an executable. ``get_ffmpeg_exe()`` returns the absolute path to the binary
# inside the imageio_ffmpeg site-packages tree at build time; the second tuple
# element is the destination directory INSIDE the bundle, matching the layout
# audio_dl._find_ffmpeg expects when imageio_ffmpeg.get_ffmpeg_exe() is called
# from a frozen process.
binaries = [(_FFMPEG_BIN, "imageio_ffmpeg/binaries")]

# Pick up data files (e.g. uvicorn's TLS defaults) that hooks may miss.
datas = (
    collect_data_files("uvicorn")
    + collect_data_files("fastapi")
    + [("audio_dl_ui/static", "audio_dl_ui/static")]
)

block_cipher = None

a = Analysis(  # noqa: F821
    ["_app_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="audio-dl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="audio-dl",
)

app = BUNDLE(  # noqa: F821
    coll,
    name="audio-dl.app",
    icon=None,
    bundle_identifier="com.jaterrell.audio-dl",
    version=VERSION,
    info_plist={
        "CFBundleName": "audio-dl",
        "CFBundleDisplayName": "audio-dl",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # Show in Dock; user can Cmd-Q to quit the embedded uvicorn server.
        "LSUIElement": False,
        # No file/URL handlers; the UI lives at http://127.0.0.1:8000.
    },
)
