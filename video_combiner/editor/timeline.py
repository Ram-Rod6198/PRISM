"""The editor's document: video clips played back to back, with audio laid underneath."""

from __future__ import annotations

from dataclasses import dataclass, replace

from video_combiner.ffmpeg import MediaInfo

MIN_CLIP_SEC = 0.1
_MAX_UNDO_STEPS = 200


@dataclass
class Clip:
    """A stretch of one media file placed on the timeline.

    ``in_sec``/``out_sec`` are times within the file; ``start_sec`` is when the
    clip begins on the timeline. ``volume`` scales its sound (1.0 = unchanged).
    """

    media: MediaInfo
    in_sec: float
    out_sec: float
    start_sec: float = 0.0
    volume: float = 1.0

    @property
    def duration(self) -> float:
        return self.out_sec - self.in_sec

    @property
    def end_sec(self) -> float:
        return self.start_sec + self.duration


class Timeline:
    """A cut: video clips that play one after another, and audio clips placed freely beneath them.

    Video clips never overlap or leave gaps; the timeline keeps their
    ``start_sec`` up to date. Audio clips stay where they are put and are mixed
    together, and with the video clips' own sound unless ``video_muted``. The
    result is as long as the video track; audio past its end is not heard.

    Read ``video`` and ``audio`` freely, but change clips only through the
    methods here. They accept any value and bring it within bounds, so a mouse
    drag can pass raw positions. Call ``checkpoint()`` before a user action to
    make everything up to the next checkpoint undoable as one step.
    """

    def __init__(self) -> None:
        self.video: list[Clip] = []
        self.audio: list[Clip] = []
        self.video_muted = False
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._state_after_undo: tuple | None = None

    # --- reading ----------------------------------------------------------

    @property
    def duration(self) -> float:
        """Length of the result: the end of the last video clip."""
        return self.video[-1].end_sec if self.video else 0.0

    @property
    def extent(self) -> float:
        """Where the last clip of either track ends (audio may run past the video)."""
        return max([self.duration, *(clip.end_sec for clip in self.audio)])

    def is_audio(self, clip: Clip) -> bool:
        return any(clip is other for other in self.audio)

    def video_at(self, sec: float) -> Clip | None:
        """The video clip showing at timeline time ``sec`` (the last clip at the very end)."""
        for clip in self.video:
            if clip.start_sec <= sec < clip.end_sec:
                return clip
        return self.video[-1] if self.video and sec == self.duration else None

    def frame_at(self, sec: float) -> tuple[MediaInfo, float] | None:
        """Which file, and what time within it, is on screen at timeline time ``sec``; None if nothing is."""
        clip = self.video_at(sec)
        if clip is None:
            return None
        one_frame = 1.0 / clip.media.fps
        return clip.media, min(clip.in_sec + (sec - clip.start_sec), max(clip.in_sec, clip.out_sec - one_frame))

    # --- editing ----------------------------------------------------------

    def add_video(self, media: MediaInfo) -> Clip:
        """Append the whole of ``media`` to the end of the video track."""
        clip = Clip(media, 0.0, media.duration)
        self.video.append(clip)
        self._reflow()
        return clip

    def add_audio(self, media: MediaInfo, start_sec: float = 0.0) -> Clip:
        """Place the whole of ``media``'s sound on the audio track, beginning at ``start_sec``."""
        clip = Clip(media, 0.0, media.duration, start_sec=max(0.0, start_sec))
        self.audio.append(clip)
        return clip

    def remove(self, clip: Clip) -> None:
        self._track(clip).remove(clip)
        self._reflow()

    def reorder(self, clip: Clip, index: int) -> None:
        """Move a video clip to position ``index`` in the playing order."""
        self.video.remove(clip)
        self.video.insert(max(0, min(index, len(self.video))), clip)
        self._reflow()

    def slide(self, clip: Clip, start_sec: float) -> None:
        """Move an audio clip so it begins at timeline time ``start_sec``."""
        clip.start_sec = max(0.0, start_sec)

    def trim(self, clip: Clip, in_sec: float | None = None, out_sec: float | None = None) -> None:
        """Set where in its file the clip begins and/or ends.

        Trimming the start of an audio clip leaves the rest of it where it was
        on the timeline, so sound that was in sync stays in sync.
        """
        if in_sec is not None:
            earliest = max(0.0, clip.in_sec - clip.start_sec) if self.is_audio(clip) else 0.0
            new_in = max(earliest, min(in_sec, clip.out_sec - MIN_CLIP_SEC))
            if self.is_audio(clip):
                clip.start_sec += new_in - clip.in_sec
            clip.in_sec = new_in
        if out_sec is not None:
            clip.out_sec = max(clip.in_sec + MIN_CLIP_SEC, min(out_sec, clip.media.duration))
        self._reflow()

    def set_volume(self, clip: Clip, volume: float) -> None:
        clip.volume = max(0.0, min(volume, 2.0))

    def split(self, clip: Clip, at_sec: float) -> Clip | None:
        """Cut ``clip`` in two at timeline time ``at_sec``; returns the new second half.

        Returns None, changing nothing, if that time is not inside the clip
        (or is so close to an edge that a piece would be shorter than the minimum).
        """
        offset = at_sec - clip.start_sec
        if not MIN_CLIP_SEC <= offset <= clip.duration - MIN_CLIP_SEC:
            return None
        second_half = replace(clip, in_sec=clip.in_sec + offset, start_sec=at_sec)
        clip.out_sec = second_half.in_sec
        track = self._track(clip)
        track.insert(track.index(clip) + 1, second_half)
        return second_half

    # --- undo ---------------------------------------------------------------

    def checkpoint(self) -> None:
        """Remember the current state as the point ``undo()`` returns to.

        Checkpoints are cheap and harmless when nothing changes afterwards, so
        callers need not know in advance whether an action will have an effect.
        """
        self._undo.append(self._snapshot())
        del self._undo[:-_MAX_UNDO_STEPS]

    def undo(self) -> bool:
        """Return to the latest checkpoint that differs from now. False if there is none.

        Undo and redo rebuild the clips: clip objects obtained earlier are no
        longer part of the timeline afterwards.
        """
        current = self._snapshot()
        self._forget_redo_if_edited(current)
        while self._undo:
            earlier = self._undo.pop()
            if earlier != current:
                self._redo.append(current)
                self._restore(earlier)
                return True
        return False

    def redo(self) -> bool:
        """Reapply the step most recently undone. False if there is none, or an edit was made since."""
        current = self._snapshot()
        self._forget_redo_if_edited(current)
        if not self._redo:
            return False
        self._undo.append(current)
        self._restore(self._redo.pop())
        return True

    def _forget_redo_if_edited(self, current: tuple) -> None:
        # Redo steps only make sense from the exact state the last undo/redo left behind.
        if self._redo and current != self._state_after_undo:
            self._redo.clear()

    def _snapshot(self) -> tuple:
        return [replace(clip) for clip in self.video], [replace(clip) for clip in self.audio], self.video_muted

    def _restore(self, snapshot: tuple) -> None:
        video, audio, self.video_muted = snapshot
        self.video = [replace(clip) for clip in video]
        self.audio = [replace(clip) for clip in audio]
        self._state_after_undo = snapshot

    # --- internals ----------------------------------------------------------

    def _track(self, clip: Clip) -> list[Clip]:
        return self.audio if self.is_audio(clip) else self.video

    def _reflow(self) -> None:
        """Close up the video track: each clip starts where the previous one ends."""
        position = 0.0
        for clip in self.video:
            clip.start_sec = position
            position = clip.end_sec
