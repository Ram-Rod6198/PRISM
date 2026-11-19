"""Turns a CombinerProject into the FFmpeg arguments that render it."""

from __future__ import annotations

from video_combiner.combiner.project import AUDIO_MIX, AUDIO_NONE, CombinerProject, Slot, TextOverlay, VideoItem
from video_combiner.ffmpeg import mp4_output_args, time_arg


def compose(project: CombinerProject) -> list[str]:
    """FFmpeg arguments (inputs, filter graph, encoder settings) that render ``project`` as MP4.

    Every tile is as long as the whole render: a video is black before it starts
    and after it ends. Raises ``ValueError``, with a message for the user, when
    the project has nothing to render.
    """
    duration = project.duration
    if duration <= 0:
        raise ValueError("Nothing to render: put at least one video with a non-empty trim range in a tile.")
    slots = project.slots()
    fps = time_arg(project.fps)
    total = time_arg(duration)

    # Slots whose video is visible, mapped to the FFmpeg input number that carries it.
    playing: dict[int, int] = {}
    inputs: list[str] = []
    for slot in slots:
        if slot.video is not None and _visible_seconds(slot.video, duration) > 0:
            playing[slot.index] = len(playing)
            inputs += ["-i", slot.video.media.path]

    filters = [f"color=c=black:s={project.canvas_w}x{project.canvas_h}:r={fps}:d={total}[base]"]
    for slot in slots:
        w, h = max(1, slot.tile.w), max(1, slot.tile.h)
        label = _video_label(slot)
        if slot.index not in playing:
            filters.append(f"color=c=black:s={w}x{h}:r={fps}:d={total}[{label}]")
            continue
        video = slot.video
        assert video is not None
        trim_start, _ = video.trim_bounds()
        delay = max(0.0, video.start_at_sec)
        visible = _visible_seconds(video, duration)
        filters.append(
            f"[{playing[slot.index]}:v]"
            f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
            f"[{label}_scaled]"
        )
        filters.append(
            f"[{label}_scaled]trim=start={time_arg(trim_start)}:duration={time_arg(visible)},"
            f"setpts=PTS-STARTPTS,"
            f"tpad=start_duration={time_arg(delay)}:stop_duration={time_arg(duration - delay - visible)}:stop_mode=add,"
            f"trim=duration={total},setpts=PTS-STARTPTS[{label}]"
        )

    # Empty tiles go down first so they can never cover a video; then list order, later on top.
    stacking = sorted(slots, key=lambda slot: (slot.video is not None, slot.index))
    canvas = "base"
    for position, slot in enumerate(stacking, start=1):
        next_canvas = "vstacked" if position == len(stacking) else f"canvas{position}"
        filters.append(
            f"[{canvas}][{_video_label(slot)}]overlay=x={slot.x}:y={slot.y}:eof_action=pass[{next_canvas}]"
        )
        canvas = next_canvas

    texts = [text for text in project.texts if text.enabled and text.text.strip()]
    for number, text in enumerate(texts, start=1):
        next_canvas = "vout" if number == len(texts) else f"vtxt{number}"
        filters.append(f"[{canvas}]{_drawtext(text)}[{next_canvas}]")
        canvas = next_canvas
    if not texts:
        filters.append(f"[{canvas}]format=yuv420p[vout]")

    audio_label = _append_audio(filters, project, slots, playing, duration)
    return [
        *inputs,
        "-filter_complex", ";".join(filters),
        *mp4_output_args("vout", audio_label, project.fps, duration),
    ]


def _video_label(slot: Slot) -> str:
    return f"v{slot.index + 1}"


def _visible_seconds(video: VideoItem, duration: float) -> float:
    """How long the video's trimmed segment is actually on screen within a render of ``duration``."""
    trim_start, trim_end = video.trim_bounds()
    return max(0.0, min(trim_end - trim_start, duration - max(0.0, video.start_at_sec)))


def _append_audio(
    filters: list[str],
    project: CombinerProject,
    slots: list[Slot],
    playing: dict[int, int],
    duration: float,
) -> str | None:
    """Add the audio part of the graph to ``filters``; returns its output label, or None for silence."""
    if project.audio == AUDIO_NONE:
        return None
    heard = []
    for slot in slots:
        video = slot.video
        if video is None or slot.index not in playing or not video.media.has_audio:
            continue
        if video.include_in_mix if project.audio == AUDIO_MIX else slot.index == project.audio:
            heard.append((slot, video))
    if not heard:
        return None

    labels = []
    for slot, video in heard:
        trim_start, _ = video.trim_bounds()
        delay_ms = int(round(max(0.0, video.start_at_sec) * 1000))
        label = "aout" if len(heard) == 1 else f"a{slot.index + 1}"
        filters.append(
            f"[{playing[slot.index]}:a]"
            f"atrim=start={time_arg(trim_start)}:duration={time_arg(_visible_seconds(video, duration))},"
            f"asetpts=PTS-STARTPTS,"
            f"adelay={delay_ms}:all=1,"
            f"apad,atrim=duration={time_arg(duration)},asetpts=N/SR/TB[{label}]"
        )
        labels.append(label)
    if len(labels) > 1:
        filters.append("".join(f"[{label}]" for label in labels) + f"amix=inputs={len(labels)}:normalize=0[aout]")
    return "aout"


def _drawtext(text: TextOverlay) -> str:
    escaped = text.text
    # Backslash first, so the escapes added for the other characters are not escaped again.
    for char in ("\\", ":", "'", "[", "]", "%", ","):
        escaped = escaped.replace(char, "\\" + char)
    color = (text.color or "white").replace(":", "\\:")
    start = max(0.0, text.start_at_sec)
    if text.duration_sec is None:
        enable = f":enable='gte(t\\,{time_arg(start)})'" if start > 0 else ""
    elif text.duration_sec <= 0:
        enable = ":enable='0'"
    else:
        enable = f":enable='between(t\\,{time_arg(start)}\\,{time_arg(start + text.duration_sec)})'"
    return (
        f"drawtext=text='{escaped}':x={int(text.x)}:y={int(text.y)}:"
        f"fontsize={max(1, int(text.size))}:fontcolor={color}{enable}"
    )
