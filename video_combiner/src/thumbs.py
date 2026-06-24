from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from video_combiner.src.ffmpeg_bin import resolve_tool


class ThumbnailError(RuntimeError):
    pass


class ThumbnailService:
    def __init__(self, thumbs_dir: str | Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[1]
        self.thumbs_dir = Path(thumbs_dir) if thumbs_dir else base_dir / "tmp" / "thumbs"
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, path: str) -> str:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)

        out_path = self.thumbs_dir / f"{self._thumb_name(path)}.jpg"
        last_error = ""
        for seek in ("00:00:01", "00:00:00"):
            cmd = [
                resolve_tool("ffmpeg"),
                "-y",
                "-ss",
                seek,
                "-i",
                path,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(out_path),
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            except FileNotFoundError as exc:
                raise FileNotFoundError("ffmpeg not found (bundled binary missing and not on PATH)") from exc
            if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                return str(out_path)
            last_error = (result.stderr or "").strip()

        raise ThumbnailError(last_error or f"Failed to create thumbnail for {path}")

    @staticmethod
    def _thumb_name(path: str) -> str:
        return hashlib.sha1(path.encode("utf-8", errors="ignore")).hexdigest()[:16]
