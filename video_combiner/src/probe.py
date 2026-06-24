from __future__ import annotations

import json
import os
import subprocess

from video_combiner.src.ffmpeg_bin import resolve_tool
from video_combiner.src.model import VideoItem
from video_combiner.src.utils import parse_rational_fps, safe_float


class ProbeError(RuntimeError):
    pass


class ProbeService:
    def probe(self, path: str) -> VideoItem:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)

        cmd = [
            resolve_tool("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise FileNotFoundError("ffprobe not found (bundled binary missing and not on PATH)") from exc

        if result.returncode != 0:
            raise ProbeError(result.stderr.strip() or f"ffprobe failed: {path}")

        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ProbeError(f"Invalid ffprobe JSON: {path}") from exc

        streams = data.get("streams") or []
        fmt = data.get("format") or {}
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not video_stream:
            raise ProbeError(f"No video stream found: {path}")

        duration = safe_float(fmt.get("duration"), default=0.0)
        if duration <= 0:
            duration = safe_float(video_stream.get("duration"), default=0.0)

        avg_rate = str(video_stream.get("avg_frame_rate") or "").strip()
        raw_rate = str(video_stream.get("r_frame_rate") or "").strip()
        if avg_rate and avg_rate not in {"0/0", "N/A"}:
            fps = parse_rational_fps(avg_rate)
        else:
            fps = parse_rational_fps(raw_rate)

        return VideoItem(
            path=path,
            duration=max(0.0, duration),
            fps=fps or 30.0,
            width=int(video_stream.get("width") or 0),
            height=int(video_stream.get("height") or 0),
            has_audio=any(s.get("codec_type") == "audio" for s in streams),
            thumb_path=None,
        )
