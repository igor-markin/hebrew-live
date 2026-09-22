# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir macOS bundle for the stage-one engine proof."""
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
PACKAGE_ROOT = SOURCE_ROOT / "hebrew_live"

datas = [
    (str(PACKAGE_ROOT / "browser.css"), "hebrew_live"),
    (str(PACKAGE_ROOT / "browser.html"), "hebrew_live"),
    (str(PACKAGE_ROOT / "browser.js"), "hebrew_live"),
    (str(PACKAGE_ROOT / "models.json"), "hebrew_live"),
    (str(PACKAGE_ROOT / "desktop_models.json"), "hebrew_live"),
    # Retranslation hashes the prompt source at import time for diagnostic
    # provenance.  PyInstaller's PYZ archive does not expose that source as a
    # normal filesystem path, so keep the exact file beside the frozen package.
    (str(PACKAGE_ROOT / "translation.py"), "hebrew_live"),
    (str(PACKAGE_ROOT / "web"), "hebrew_live/web"),
]
binaries = []
hiddenimports = [
    "mlx_lm.models.gemma3_text",
    "hebrew_live.model_selection",
]

# Native libraries and dynamically selected model/tokenizer modules need an
# explicit collection pass. mlx-whisper itself is statically reachable; keeping
# it out of this list avoids pulling its conversion-only torch helper into the app.
datas += collect_data_files("mlx_whisper", includes=["assets/*"])
for package in (
    "mlx",
    "mlx_lm",
    "onnxruntime",
    "sounddevice",
    "soundfile",
    "soxr",
    "sentencepiece",
    "tokenizers",
    "bidi",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

for distribution in (
    "hebrew-live-cli",
    "mlx",
    "mlx-whisper",
    "mlx-lm",
    "onnxruntime",
    "sounddevice",
    "soundfile",
    "soxr",
    "huggingface-hub",
    "python-bidi",
    "transformers",
    "tokenizers",
    "sentencepiece",
):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        # Analysis will still fail later if runtime metadata is truly required;
        # this keeps an optional distribution name from breaking the spec itself.
        pass

proof_config = os.environ.get("HEBREW_LIVE_PROOF_CONFIG")
if proof_config:
    datas.append((proof_config, "hebrew_live"))

a = Analysis(
    [str(PACKAGE_ROOT / "desktop_entry.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchaudio", "torchvision", "tensorflow", "jax", "jaxlib"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hebrew Live",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Hebrew Live",
)
app = BUNDLE(
    coll,
    name="Hebrew Live.app",
    icon=None,
    bundle_identifier="com.igormarkin.hebrewlive",
    version="0.1.0-alpha.1",
    info_plist={
        "CFBundleDisplayName": "Hebrew Live",
        "CFBundleName": "Hebrew Live",
        "LSMinimumSystemVersion": "26.2",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Hebrew Live uses the microphone only for local speech recognition and translation.",
    },
)
