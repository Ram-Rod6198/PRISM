"""Turns a Timeline into FFmpeg arguments: for the exported file, and for playing it in the window."""

from __future__ import annotations

from dataclasses import dataclass

from video_combiner.editor.timeline import Timeline
from video_combiner.ffmpeg import mp4_output_args, time_arg
from video_combiner.filters import drawtext, fill

_PLAYBACK_MAX_SIZE = (960, 540)
_PLAYBACK_MAX_FPS = 30.0


@dataclass(frozen=True)
class Playback:
    """What it takes to play a timeline from some point on, in real time.

    ``picture`` are FFmpeg arguments for ``ffmpeg.FrameStream``, giving frames
    of ``width`` x ``height`` at ``fps``. ``sound`` are FFmpeg arguments that
    write the matching sound to any audio file, or None when nothing is heard.
    Both last ``duration`` seconds.
    """

    picture: list[str]
    sound: list[str] | None
    width: int
    height: int
    fps: float
    duration: float


def compose(timeline: Timeline) -> list[str]:
    """FFmpeg arguments (inputs, filter graph, encoder settings) that export ``timeline`` as MP4.

    Each clip fills its tile, cropped as needed, for as long as it plays; the
    frame rate is the first clip's. Raises ``ValueError``, with a message for
    the user, when no tile has a clip in it.
    """
    if timeline.duration <= 0:
        raise ValueError("Nothing to render: add at least one video to a tile first.")
    graph = _Graph(timeline, 0.0, 1.0, timeline.fps)
    return [*graph.arguments(), *mp4_output_args("vout", graph.sound_label, timeline.fps, graph.duration)]


def compose_playback(timeline: Timeline, from_sec: float, fit_within: tuple[int, int]) -> Playback:
    """How to play ``timeline`` from ``from_sec`` to its end, in a picture no larger than ``fit_within``.

    The picture is the canvas scaled down (never up) and capped at a size that
    decodes comfortably in real time. ``from_sec`` must lie before the end.
    """
    limit_w, limit_h = (min(a, b) for a, b in zip(fit_within, _PLAYBACK_MAX_SIZE))
    scale = min(1.0, limit_w / timeline.canvas_w, limit_h / timeline.canvas_h)
    fps = min(timeline.fps, _PLAYBACK_MAX_FPS)
    picture = _Graph(timeline, from_sec, scale, fps, sound=False)
    sound = _Graph(timeline, from_sec, scale, fps, picture=False)
    length = ["-t", time_arg(picture.duration)]
    return Playback(
        picture=[*picture.arguments(), "-map", "[vout]", "-r", time_arg(fps), *length],
        sound=[*sound.arguments(), "-map", f"[{sound.sound_label}]", *length] if sound.sound_label else None,
        width=picture.width,
        height=picture.height,
        fps=fps,
        duration=picture.duration,
    )


class _Graph:
    """The inputs and filter graph for the part of a timeline after ``from_sec``, at ``scale`` of its canvas.

    The picture comes out as ``[vout]`` and the sound as ``[sound_label]``
    (None when nothing is heard). Either half can be left out, so that playing
    never decodes what it does not use.
    """

    def __init__(
        self, timeline: Timeline, from_sec: float, scale: float, fps: float, picture: bool = True, sound: bool = True
    ) -> None:
        self.duration = timeline.duration - from_sec
        self.width, self.height = _even(timeline.canvas_w * scale), _even(timeline.canvas_h * scale)
        self.sound_label: str | None = None
        self._inputs: list[str] = []
        self._filters: list[str] = []
        heard = timeline.heard() if sound else []
        total = time_arg(self.duration)
        canvas = "base"
        if picture:
            self._filters.append(f"color=c=black:s={self.width}x{self.height}:r={time_arg(fps)}:d={total}[base]")

        sounds: list[str] = []
        input_count = 0
        # Tiles in order, so that later tiles end up on top; the audio track (None) has nothing to show.
        for tile_index in (*range(len(timeline.tiles)), None):
            for clip in timeline.track(tile_index):
                skipped = max(0.0, from_sec - clip.start_at_sec)
                start = max(0.0, clip.start_at_sec - from_sec)
                trim_start, trim_end = clip.trim_bounds()
                length = min(trim_end - trim_start - skipped, self.duration - start)
                shown = picture and tile_index is not None
                audible = any(clip is other for other in heard)
                if length <= 0 or not (shown or audible):
                    continue
                # Seeking on the input is frame-accurate when re-encoding and skips decoding the unused part.
                self._inputs += ["-ss", time_arg(trim_start + skipped), "-t", time_arg(length)]
                self._inputs += [*([] if shown else ["-vn"]), *([] if audible else ["-an"]), "-i", clip.media.path]
                number, input_count = input_count, input_count + 1
                if shown:
                    tile = timeline.tiles[tile_index]
                    x, y = clip.position if clip.position is not None else (tile.x, tile.y)
                    width, height = max(1, round(tile.w * scale)), max(1, round(tile.h * scale))
                    # Shifting the clip's timestamps makes the overlay appear at its place on the timeline
                    # and vanish when the clip ends; the canvas shows through before and after.
                    self._filters.append(
                        f"[{number}:v]{fill(width, height)},fps={time_arg(fps)},"
                        f"setpts=PTS-STARTPTS+{time_arg(start)}/TB[c{number}]"
                    )
                    self._filters.append(
                        f"[{canvas}][c{number}]overlay=x={round(x * scale)}:y={round(y * scale)}"
                        f":eof_action=pass[k{number}]"
                    )
                    canvas = f"k{number}"
                if audible:
                    self._filters.append(
                        f"[{number}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                        f"adelay={round(start * 1000)}:all=1[a{number}]"
                    )
                    sounds.append(f"[a{number}]")

        if picture:
            for text in timeline.texts:
                if text.enabled and text.text.strip():
                    self._filters.append(f"[{canvas}]{drawtext(text, scale, from_sec)}[t{len(self._filters)}]")
                    canvas = f"t{len(self._filters) - 1}"
            self._filters.append(f"[{canvas}]format=yuv420p[vout]")
        if sounds:
            mix = f"amix=inputs={len(sounds)}:normalize=0:duration=longest," if len(sounds) > 1 else ""
            # Pad with silence so the sound is as long as the picture.
            self._filters.append(f"{''.join(sounds)}{mix}apad[aout]")
            self.sound_label = "aout"

    def arguments(self) -> list[str]:
        return [*self._inputs, "-filter_complex", ";".join(self._filters)]


def _even(value: float) -> int:
    return max(2, round(value) // 2 * 2)
