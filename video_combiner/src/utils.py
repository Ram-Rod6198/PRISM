from __future__ import annotations

import math
from pathlib import Path


def parse_rational_fps(value: str | None) -> float:
    if not value:
        return 30.0
    text = str(value).strip()
    if not text or text in {"0/0", "N/A"}:
        return 30.0
    if "/" in text:
        num_s, den_s = text.split("/", 1)
        try:
            num = float(num_s)
            den = float(den_s)
            if den == 0:
                return 30.0
            fps = num / den
            return fps if math.isfinite(fps) and fps > 0 else 30.0
        except ValueError:
            return 30.0
    try:
        fps = float(text)
        return fps if math.isfinite(fps) and fps > 0 else 30.0
    except ValueError:
        return 30.0


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0.00s"
    minutes = int(seconds // 60)
    rem = seconds - (minutes * 60)
    if minutes:
        return f"{minutes}:{rem:05.2f}"
    return f"{rem:.2f}s"


def short_name(path: str) -> str:
    return Path(path).name


def ff_time(seconds: float) -> str:
    value = max(0.0, float(seconds))
    text = f"{value:.6f}"
    return text.rstrip("0").rstrip(".") or "0"


def parse_timecode(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if ":" not in text:
            return max(0.0, float(text))
        parts = [p.strip() for p in text.split(":")]
        if len(parts) > 3 or any(p == "" for p in parts):
            return None
        nums = [float(p) for p in parts]
        if len(nums) == 3:
            h, m, s = nums
        elif len(nums) == 2:
            h, m, s = 0.0, nums[0], nums[1]
        else:
            h, m, s = 0.0, 0.0, nums[0]
        total = h * 3600 + m * 60 + s
        return max(0.0, total)
    except ValueError:
        return None


def format_timecode(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0.0, float(seconds))
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = total - (h * 3600) - (m * 60)
    if abs(s - round(s)) < 1e-6:
        return f"{h:02d}:{m:02d}:{int(round(s)):02d}"
    return f"{h:02d}:{m:02d}:{s:06.3f}".rstrip("0").rstrip(".")
