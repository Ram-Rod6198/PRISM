# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).resolve()
ENTRY = ROOT / "Main.py"
FFMPEG_BIN = ROOT / "video_combiner" / "assets" / "ffmpeg" / "bin"
PRESET_JSON = ROOT / "video_combiner" / "assets" / "canvas_presets.user.json"

datas = []
if FFMPEG_BIN.exists():
    for p in FFMPEG_BIN.iterdir():
        if p.is_file():
            datas.append((str(p), "video_combiner/assets/ffmpeg/bin"))
if PRESET_JSON.exists():
    datas.append((str(PRESET_JSON), "data"))

hiddenimports = collect_submodules("PIL")


a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VideoCombinerPortable",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
