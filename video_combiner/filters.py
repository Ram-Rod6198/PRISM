"""Pieces of FFmpeg filter graph that the composers of both modes are built from."""

from __future__ import annotations

from video_combiner.ffmpeg import time_arg
from video_combiner.project import TextOverlay


def fill(width: int, height: int) -> str:
    """Filters that make a video exactly ``width`` x ``height``: scaled to cover, the overhang cropped."""
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"


def drawtext(text: TextOverlay, scale: float = 1.0, starting_at_sec: float = 0.0) -> str:
    """The filter that draws ``text``.

    ``scale`` shrinks position and size along with a scaled-down canvas.
    ``starting_at_sec`` is the project time at which the filtered video begins,
    for when only the rest of a project is rendered.
    """
    escaped = text.text
    # Backslash first, so the escapes added for the other characters are not escaped again.
    for char in ("\\", ":", "'", "[", "]", "%", ","):
        escaped = escaped.replace(char, "\\" + char)
    color = (text.color or "white").replace(":", "\\:")
    start = max(0.0, text.start_at_sec) - starting_at_sec
    end = None if text.duration_sec is None else start + text.duration_sec
    if end is None:
        enable = f":enable='gte(t\\,{time_arg(start)})'" if start > 0 else ""
    elif end <= max(0.0, start):
        enable = ":enable='0'"
    else:
        enable = f":enable='between(t\\,{time_arg(start)}\\,{time_arg(end)})'"
    return (
        f"drawtext=text='{escaped}':x={round(text.x * scale)}:y={round(text.y * scale)}:"
        f"fontsize={max(1, round(text.size * scale))}:fontcolor={color}{enable}"
    )
