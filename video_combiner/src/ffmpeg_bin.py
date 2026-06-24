from __future__ import annotations

import os
import sys
from pathlib import Path


def bundled_bin_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "video_combiner" / "assets" / "ffmpeg" / "bin"
        return Path(sys.executable).resolve().parent / "video_combiner" / "assets" / "ffmpeg" / "bin"
    return Path(__file__).resolve().parents[1] / "assets" / "ffmpeg" / "bin"


def resolve_tool(tool_name: str) -> str:
    candidates = [tool_name]
    if os.name == "nt" and not tool_name.lower().endswith(".exe"):
        candidates.insert(0, f"{tool_name}.exe")

    bin_dir = bundled_bin_dir()
    for name in candidates:
        path = bin_dir / name
        if path.exists():
            return str(path)

    # Fallback to PATH lookup by base tool name.
    return tool_name
