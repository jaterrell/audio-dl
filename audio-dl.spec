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
)

# Pick up data files (e.g. uvicorn's TLS defaults) that some hooks miss.
datas = (
    collect_data_files("uvicorn")
    + collect_data_files("fastapi")
)

block_cipher = None

a = Analysis(  # noqa: F821
    ["_app_entry.py"],
    pathex=[],
    binaries=[],
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
