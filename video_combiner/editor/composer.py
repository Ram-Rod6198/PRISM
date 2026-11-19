"""Turns a Timeline into the FFmpeg arguments that export it."""

from __future__ import annotations

from video_combiner.editor.timeline import Timeline
from video_combiner.ffmpeg import mp4_output_args, time_arg

_DRAFT_HEIGHT = 360


def compose(timeline: Timeline, size: tuple[int, int] | None = None, draft: bool = False) -> list[str]:
    """FFmpeg arguments (inputs, filter graph, encoder settings) that export ``timeline`` as MP4.

    ``size`` is the output frame (width, height); by default that of the first
    clip. Clips of another shape are fitted inside it with black bars. The
    frame rate is the first clip's. ``draft`` makes a small, fast, rough encode
    for previewing. Raises ``ValueError``, with a message for the user, when
    the video track is empty.
    """
    if not timeline.video:
        raise ValueError("Add at least one clip to the timeline first.")
    width, height = size or frame_size(timeline)
    if draft:
        width, height = _even(width * _DRAFT_HEIGHT / height), _DRAFT_HEIGHT
    fps = timeline.video[0].media.fps
    duration = timeline.duration

    inputs: list[str] = []
    filters: list[str] = []
    sounds: list[str] = []

    def add_sound(input_number: int, start_sec: float, volume: float) -> None:
        label = f"a{len(sounds)}"
        filters.append(
            f"[{input_number}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={time_arg(volume)},adelay={round(start_sec * 1000)}:all=1[{label}]"
        )
        sounds.append(label)

    for number, clip in enumerate(timeline.video):
        # Seeking on the input is frame-accurate when re-encoding and skips decoding the unused part.
        inputs += ["-ss", time_arg(clip.in_sec), "-t", time_arg(clip.duration), "-i", clip.media.path]
        filters.append(
            f"[{number}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={time_arg(fps)},format=yuv420p,"
            f"setpts=PTS-STARTPTS[v{number}]"
        )
        if clip.media.has_audio and clip.volume > 0 and not timeline.video_muted:
            add_sound(number, clip.start_sec, clip.volume)
    video_labels = "".join(f"[v{number}]" for number in range(len(timeline.video)))
    filters.append(f"{video_labels}concat=n={len(timeline.video)}:v=1:a=0[vout]")

    input_count = len(timeline.video)
    for clip in timeline.audio:
        if clip.volume <= 0 or clip.start_sec >= duration:
            continue
        inputs += ["-ss", time_arg(clip.in_sec), "-t", time_arg(clip.duration), "-vn", "-i", clip.media.path]
        add_sound(input_count, clip.start_sec, clip.volume)
        input_count += 1

    audio_label = None
    if sounds:
        audio_label = "aout"
        mixed = "".join(f"[{label}]" for label in sounds)
        mix = f"amix=inputs={len(sounds)}:normalize=0:duration=longest," if len(sounds) > 1 else ""
        # Pad with silence so the sound track is as long as the picture.
        filters.append(f"{mixed}{mix}apad[aout]")

    return [
        *inputs,
        "-filter_complex", ";".join(filters),
        *mp4_output_args("vout", audio_label, fps, duration, draft=draft),
    ]


def frame_size(timeline: Timeline) -> tuple[int, int]:
    """The export's default frame: the first clip's size (H.264 needs even numbers)."""
    first = timeline.video[0].media
    return _even(first.width), _even(first.height)


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)
