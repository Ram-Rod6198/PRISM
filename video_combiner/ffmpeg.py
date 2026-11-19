"""Everything PRISM asks of FFmpeg: inspecting media, grabbing stills, encoding.

Callers pass media paths and FFmpeg *arguments* (never the program name) and get
Python values or an ``FFmpegError`` back. Where the binaries live, how they are
launched and how their failures are worded is decided here and nowhere else.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_BUNDLED_BIN_DIR = _PACKAGE_DIR / "assets" / "ffmpeg" / "bin"
_THUMB_DIR = _PACKAGE_DIR / "tmp" / "thumbs"
_THUMB_MAX_WIDTH = 1280
_DEFAULT_FPS = 30.0
_ENCODED_TIME = re.compile(r"\btime=(\d+):(\d+):(\d+(?:\.\d+)?)")


class FFmpegError(RuntimeError):
    """FFmpeg could not do what was asked; the message is fit to show the user."""


class FFmpegNotFound(FFmpegError):
    """Neither a bundled nor a PATH copy of ffmpeg/ffprobe could be started."""


@dataclass(frozen=True)
class MediaInfo:
    """What PRISM knows about one media file on disk."""

    path: str
    duration: float
    fps: float
    width: int
    height: int
    has_video: bool
    has_audio: bool
    thumb_path: str | None = None

    @property
    def name(self) -> str:
        return Path(self.path).name


def load_media(path: str) -> MediaInfo:
    """Inspect a media file and prepare a thumbnail for it.

    Width and height are as displayed (rotation metadata applied). A file with
    only audio is valid media (``has_video`` is False). A thumbnail that cannot
    be made is not an error; ``thumb_path`` is simply None.
    """
    result = _run("ffprobe", ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if result.returncode != 0:
        raise FFmpegError(_last_line(result.stderr) or f"Could not read {Path(path).name}")
    try:
        report = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError(f"Could not read {Path(path).name}") from exc

    streams = report.get("streams") or []
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if video is None and not has_audio:
        raise FFmpegError(f"No video or audio found in {Path(path).name}")

    duration = _to_float((report.get("format") or {}).get("duration"))
    width = height = 0
    fps = _DEFAULT_FPS
    if video is not None:
        if duration <= 0:
            duration = _to_float(video.get("duration"))
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        if _is_rotated_sideways(video):
            width, height = height, width
        fps = _parse_fps(video.get("avg_frame_rate")) or _parse_fps(video.get("r_frame_rate")) or _DEFAULT_FPS

    return MediaInfo(
        path=path,
        duration=max(0.0, duration),
        fps=fps,
        width=width,
        height=height,
        has_video=video is not None,
        has_audio=has_audio,
        thumb_path=_make_thumbnail(path) if video is not None else None,
    )


def still_frame(path: str, at_sec: float, max_height: int = 540) -> bytes:
    """The video frame of ``path`` at ``at_sec``, as JPEG bytes no taller than ``max_height``."""
    for seek in (at_sec, at_sec - 0.25):
        result = _run(
            "ffmpeg",
            [
                "-v", "error",
                "-ss", time_arg(seek),
                "-i", path,
                "-frames:v", "1",
                "-vf", f"scale=-2:'min({int(max_height)},ih)'",
                "-f", "image2pipe",
                "-c:v", "mjpeg",
                "-q:v", "4",
                "pipe:1",
            ],
            text=False,
        )
        # Seeking to the very end of a file yields no frame; step back once.
        if result.returncode == 0 and result.stdout:
            return result.stdout
        if seek <= 0:
            break
    raise FFmpegError(f"No frame at {time_arg(at_sec)}s in {Path(path).name}")


class Encode:
    """One FFmpeg encode into ``output_path``; may be cancelled from another thread."""

    def __init__(self, args: list[str], output_path: str) -> None:
        self.output_path = output_path
        self.cancelled = False
        self._command = [_tool("ffmpeg"), "-y", "-hide_banner", "-nostdin", *args, output_path]
        self._process: subprocess.Popen[str] | None = None

    @property
    def command_line(self) -> str:
        """The exact command, quoted so it can be pasted into a terminal."""
        return subprocess.list2cmdline(self._command)

    def run(
        self,
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> None:
        """Encode to completion, blocking the calling thread.

        ``on_line`` receives each line FFmpeg logs; ``on_progress`` the seconds
        of output encoded so far. Raises ``FFmpegError`` if FFmpeg fails. After
        a cancel the partial output file is removed and ``cancelled`` is True.
        """
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_no_console_window(),
            )
        except OSError as exc:
            raise FFmpegNotFound(_NOT_FOUND.format(tool="ffmpeg")) from exc
        if self.cancelled:
            self._process.terminate()

        last_lines: list[str] = []
        with self._process as process:
            assert process.stderr is not None
            for raw in process.stderr:
                line = raw.rstrip()
                if not line:
                    continue
                last_lines = [*last_lines[-2:], line]
                if on_line:
                    on_line(line)
                match = _ENCODED_TIME.search(line)
                if match and on_progress:
                    hours, minutes, seconds = match.groups()
                    on_progress(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
        exit_code = process.returncode

        if self.cancelled:
            Path(self.output_path).unlink(missing_ok=True)
        elif exit_code != 0:
            # FFmpeg explains a failure in its final lines.
            raise FFmpegError("\n".join(last_lines) or f"ffmpeg exited with code {exit_code}")

    def cancel(self) -> None:
        self.cancelled = True
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()


class FrameStream:
    """Video decoded by FFmpeg into plain pictures, handed over one at a time.

    ``args`` are FFmpeg arguments (inputs, filters, mapping) whose video output
    is ``width`` x ``height``. FFmpeg works ahead only as far as its pipe
    holds, so reading at playing speed costs no more than playing. Reading and
    closing may happen on different threads.
    """

    def __init__(self, args: list[str], width: int, height: int) -> None:
        self._frame_bytes = width * height * 3
        self._closed = False
        command = [_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", *args]
        command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self._frame_bytes,
                **_no_console_window(),
            )
        except OSError as exc:
            raise FFmpegNotFound(_NOT_FOUND.format(tool="ffmpeg")) from exc

    def read(self) -> bytes | None:
        """The next frame as ``width * height`` RGB pixels, row by row; None when there are no more.

        Raises ``FFmpegError`` if FFmpeg gave up rather than finished. After
        ``close()`` there are simply no more frames.
        """
        assert self._process.stdout is not None and self._process.stderr is not None
        try:
            frame = self._process.stdout.read(self._frame_bytes)
        except (OSError, ValueError):  # The pipe was closed under us by close().
            frame = b""
        if len(frame) == self._frame_bytes:
            return frame
        try:
            complaint = self._process.stderr.read().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            complaint = ""
        failed = self._process.wait() != 0
        self._process.stdout.close()
        self._process.stderr.close()
        if failed and not self._closed:
            raise FFmpegError(_last_line(complaint) or "FFmpeg could not decode the video.")
        return None

    def close(self) -> None:
        """Stop decoding. Safe to call more than once."""
        self._closed = True
        if self._process.poll() is None:
            self._process.terminate()


def mp4_output_args(
    video_label: str,
    audio_label: str | None,
    fps: float,
    duration: float,
) -> list[str]:
    """Arguments that encode the filter outputs ``[video_label]``/``[audio_label]`` as H.264/AAC MP4.

    ``audio_label`` None means a silent file.
    """
    args = ["-map", f"[{video_label}]"]
    if audio_label:
        args += ["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-an"]
    return args + [
        "-r", time_arg(fps),
        "-t", time_arg(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-preset", "veryfast",
        "-movflags", "+faststart",
    ]


def time_arg(seconds: float) -> str:
    """A non-negative number of seconds in the shortest form FFmpeg accepts ("2.5", "0")."""
    text = f"{max(0.0, float(seconds)):.6f}"
    return text.rstrip("0").rstrip(".") or "0"


# --- launching the binaries -------------------------------------------------

_NOT_FOUND = "{tool} was not found (no bundled binary and not on PATH)."


def _tool(name: str) -> str:
    """Path of the bundled binary if one ships with the app, else the bare name for PATH lookup."""
    bundled = _BUNDLED_BIN_DIR / (f"{name}.exe" if os.name == "nt" else name)
    return str(bundled) if bundled.exists() else name


def _no_console_window() -> dict[str, int]:
    # Without this, every FFmpeg call flashes a console window in a windowed Windows app.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _run(tool: str, args: list[str], text: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [_tool(tool), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            errors="replace" if text else None,
            check=False,
            **_no_console_window(),
        )
    except OSError as exc:
        raise FFmpegNotFound(_NOT_FOUND.format(tool=tool)) from exc


def _make_thumbnail(path: str) -> str | None:
    """Write a JPEG of an early frame of ``path`` into the thumbnail cache; None if FFmpeg can't."""
    try:
        _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    out_path = _THUMB_DIR / (hashlib.sha1(path.encode("utf-8", errors="ignore")).hexdigest()[:16] + ".jpg")
    # One second in usually skips fade-ins and black leaders; very short clips need frame zero.
    for seek in ("1", "0"):
        result = _run(
            "ffmpeg",
            [
                "-y", "-v", "error",
                "-ss", seek,
                "-i", path,
                "-frames:v", "1",
                "-vf", f"scale='min({_THUMB_MAX_WIDTH},iw)':-2",
                "-q:v", "2",
                str(out_path),
            ],
        )
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return str(out_path)
    return None


# --- reading ffprobe's report -----------------------------------------------


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _parse_fps(value: object) -> float | None:
    """Frames per second from ffprobe's "30000/1001" or "25" notation; None if unusable."""
    text = str(value or "").strip()
    numerator, _, denominator = text.partition("/")
    try:
        fps = float(numerator) / (float(denominator) if denominator else 1.0)
    except (ValueError, ZeroDivisionError):
        return None
    return fps if math.isfinite(fps) and fps > 0 else None


def _is_rotated_sideways(video_stream: dict) -> bool:
    """True when rotation metadata makes players show the stream with width and height swapped."""
    rotation = _to_float((video_stream.get("tags") or {}).get("rotate"))
    for side_data in video_stream.get("side_data_list") or []:
        if "rotation" in side_data:
            rotation = _to_float(side_data.get("rotation"))
    return round(abs(rotation)) % 180 == 90


def _last_line(text: str | None) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""
