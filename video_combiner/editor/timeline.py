"""The Edit mode's document: the tile layout, with clips placed along a timeline in every tile."""

from __future__ import annotations

from dataclasses import dataclass, replace

from video_combiner.ffmpeg import MediaInfo
from video_combiner.project import AUDIO_MIX, AUDIO_NONE, Slot, Tile, TileProject, VideoItem

AUDIO_TRACK = "track"  # A value of ``Timeline.audio``: only the clips on the audio track are heard.
MIN_CLIP_SEC = 0.1
_MAX_UNDO_STEPS = 200
_START_SIZE = (1920, 1080)


@dataclass
class Clip(VideoItem):
    """A stretch of one file placed on the timeline.

    ``tile`` is the index of the tile it plays in. None puts it on the audio
    track: heard, but not seen.
    """

    tile: int | None = 0


class Timeline(TileProject):
    """A cut: each tile has a track of clips, and one more track carries audio only.

    Clips stay where they are put. Clips in the same tile never overlap: a clip
    moved onto others pushes them later. While a tile has no clip playing it
    shows nothing. Clips on the audio track may overlap and are mixed. The
    result ends where the last clip in a tile ends; sound past that is not
    heard.

    ``audio`` may also be ``AUDIO_TRACK``; the audio track is part of
    ``AUDIO_MIX`` too.

    Read ``videos`` freely (it holds every clip, of every track), but change
    clips only through the methods here. They accept any value and bring it
    within bounds, so a mouse drag can pass raw positions. Call
    ``checkpoint()`` when a user action is complete; ``undo()`` then steps back
    one action at a time.
    """

    def __init__(self) -> None:
        super().__init__()
        self.videos: list[Clip] = []
        self.set_layout(*_START_SIZE, _whole_canvas_tile(*_START_SIZE))
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._state_after_undo: tuple | None = None
        self.checkpoint()

    # --- reading ----------------------------------------------------------

    def track(self, tile: int | None) -> list[Clip]:
        """The clips of one tile (None: of the audio track), earliest first."""
        return sorted((clip for clip in self.videos if clip.tile == tile), key=lambda clip: clip.start_at_sec)

    def tile_of(self, video: VideoItem) -> int | None:
        tile = video.tile  # type: ignore[attr-defined]
        return tile if tile is not None and tile < len(self.tiles) else None

    @property
    def duration(self) -> float:
        """Length of the result: where the last clip shown in a tile ends."""
        return max((clip.end_sec for clip in self.videos if self.tile_of(clip) is not None), default=0.0)

    @property
    def extent(self) -> float:
        """Where the last clip of any track ends (audio may run past the picture)."""
        return max((clip.end_sec for clip in self.videos), default=0.0)

    def slots(self, at_sec: float) -> list[Slot]:
        """Each tile with the clip showing in it at timeline time ``at_sec``, and the moment of the clip on screen."""
        resolved = []
        at_the_end = at_sec >= self.duration
        for index, tile in enumerate(self.tiles):
            showing = None
            for clip in self.track(index):
                # At the very end of the timeline the last frame stays up, as it does in a player.
                if clip.start_at_sec <= at_sec < clip.end_sec or (at_the_end and clip.end_sec == at_sec):
                    showing = clip
            if showing is None:
                resolved.append(Slot(index, tile, None, tile.x, tile.y))
                continue
            x, y = showing.position if showing.position is not None else (tile.x, tile.y)
            trim_start, trim_end = showing.trim_bounds()
            last_frame = max(trim_start, trim_end - 1.0 / showing.media.fps)
            frame_sec = min(trim_start + (at_sec - showing.start_at_sec), last_frame)
            resolved.append(Slot(index, tile, showing, x, y, frame_sec))
        return resolved

    def heard(self) -> list[Clip]:
        """The clips whose sound is part of the result, given ``audio``."""
        if self.audio == AUDIO_NONE:
            return []
        clips = []
        for clip in self.videos:
            tile = self.tile_of(clip)
            if not clip.media.has_audio or (tile is None and clip.tile is not None):
                continue
            if self.audio == AUDIO_MIX:
                chosen = clip.include_in_mix
            elif self.audio == AUDIO_TRACK:
                chosen = clip.tile is None
            else:
                chosen = tile == self.audio
            if chosen:
                clips.append(clip)
        return clips

    # --- editing ----------------------------------------------------------

    def add_video(self, media: MediaInfo, tile: int | None = None) -> Clip:
        """Put the whole of ``media`` in a tile, right after the clips already there.

        Without ``tile`` it goes to the first tile that is still empty, as in
        Combine mode, or to the first tile once all have something. The very
        first video of a new timeline also sets the canvas to its own size.
        """
        if not self.videos and (self.canvas_w, self.canvas_h) == _START_SIZE:
            if self.tiles == _whole_canvas_tile(*_START_SIZE) and media.width >= 2 and media.height >= 2:
                size = media.width // 2 * 2, media.height // 2 * 2
                self.set_layout(*size, _whole_canvas_tile(*size))
        if tile is None:
            tile = next((index for index in range(len(self.tiles)) if not self.track(index)), 0)
        start = max((clip.end_sec for clip in self.track(tile)), default=0.0)
        clip = Clip(media, trim_end_sec=media.duration, start_at_sec=start, tile=tile)
        self.videos.append(clip)
        return clip

    def add_sound(self, media: MediaInfo, start_sec: float = 0.0) -> Clip:
        """Place the whole of ``media``'s sound on the audio track, beginning at ``start_sec``."""
        clip = Clip(media, trim_end_sec=media.duration, start_at_sec=max(0.0, start_sec), tile=None)
        self.videos.append(clip)
        return clip

    def remove(self, clip: Clip) -> None:
        """Take ``clip`` off the timeline; the clips around it stay where they are."""
        del self.videos[self._index(clip)]

    def place(self, clip: Clip, tile: int | None, start_sec: float) -> None:
        """Move ``clip`` to a tile (None: the audio track) so that it begins at timeline time ``start_sec``.

        A clip dropped onto another in a tile goes in front of it or behind it,
        whichever is nearer, and later clips move right just far enough to make
        room. Dragging a clip past its neighbours is how they are reordered.
        """
        start_sec = max(0.0, start_sec)
        clip.tile = tile
        if tile is None:
            clip.start_at_sec = start_sec
            return
        others = [other for other in self.track(tile) if other is not clip]
        for other in others:
            if other.start_at_sec < start_sec < other.end_sec:
                in_front = start_sec < (other.start_at_sec + other.end_sec) / 2
                start_sec = other.start_at_sec if in_front else other.end_sec
                break
        clip.start_at_sec = start_sec
        position = sum(1 for other in others if other.start_at_sec < start_sec)
        in_order = [*others[:position], clip, *others[position:]]
        for earlier, later in zip(in_order, in_order[1:]):
            later.start_at_sec = max(later.start_at_sec, earlier.end_sec)

    def trim(self, clip: Clip, trim_start_sec: float | None = None, trim_end_sec: float | None = None) -> None:
        """Set where in its file the clip begins and/or ends.

        What remains of the clip stays where it was on the timeline, and no
        other clip moves: trimming the start makes the clip begin later, and a
        clip in a tile can grow only as far as its neighbour on that side.
        """
        free_from, free_until = self._room_around(clip)
        start, end = clip.trim_bounds()
        if trim_start_sec is not None:
            earliest = max(0.0, start - (clip.start_at_sec - free_from))
            new_start = max(earliest, min(trim_start_sec, end - MIN_CLIP_SEC))
            clip.start_at_sec += new_start - start
            clip.trim_start_sec = start = new_start
        if trim_end_sec is not None:
            latest = min(clip.media.duration, start + (free_until - clip.start_at_sec))
            end = max(start + MIN_CLIP_SEC, min(trim_end_sec, latest))
        clip.trim_end_sec = end

    def set_timing(
        self, video: VideoItem, trim_start_sec: float, trim_end_sec: float | None, start_at_sec: float
    ) -> None:
        # Typed values obey the same rules as dragging; only what differs from now is applied,
        # so a field that merely shows a rounded time never nudges the clip.
        clip: Clip = video  # type: ignore[assignment]
        was_start, was_end = clip.trim_bounds()
        if _differs(start_at_sec, clip.start_at_sec):
            self.place(clip, clip.tile, start_at_sec)
        if _differs(trim_start_sec, was_start):
            self.trim(clip, trim_start_sec=trim_start_sec)
        new_end = clip.media.duration if trim_end_sec is None else trim_end_sec
        if _differs(new_end, was_end):
            self.trim(clip, trim_end_sec=new_end)

    def split(self, clip: Clip, at_sec: float) -> Clip | None:
        """Cut ``clip`` in two at timeline time ``at_sec``; returns the new second half.

        Returns None, changing nothing, if that time is not inside the clip
        (or is so close to an edge that a piece would be shorter than the minimum).
        """
        offset = at_sec - clip.start_at_sec
        start, end = clip.trim_bounds()
        if not MIN_CLIP_SEC <= offset <= (end - start) - MIN_CLIP_SEC:
            return None
        second_half = replace(clip, trim_start_sec=start + offset, trim_end_sec=end, start_at_sec=at_sec)
        clip.trim_end_sec = start + offset
        self.videos.insert(self._index(clip) + 1, second_half)
        return second_half

    def close_gaps(self) -> None:
        """Pull the clips of every tile together, so each tile plays back to back from the start."""
        for tile in range(len(self.tiles)):
            position = 0.0
            for clip in self.track(tile):
                clip.start_at_sec = position
                position = clip.end_sec

    # --- undo ---------------------------------------------------------------

    def checkpoint(self) -> None:
        """Record the clips as they are now, as a state ``undo()`` can return to.

        Checkpoints are cheap, and harmless when nothing changed since the
        last one, so callers need not know whether an action had any effect.
        """
        self._undo.append(self._snapshot())
        del self._undo[:-_MAX_UNDO_STEPS]

    def undo(self) -> bool:
        """Return to the latest checkpoint that differs from now. False if there is none.

        Undo and redo rebuild the clips: clip objects obtained earlier are no
        longer part of the timeline afterwards. The tile layout is not undone.
        """
        current = self._snapshot()
        self._forget_redo_if_edited(current)
        while self._undo:
            earlier = self._undo.pop()
            if earlier != current:
                self._redo.append(current)
                self._restore(earlier)
                break
        # The state now in effect stays on record, for the next undo to step back from.
        self._undo.append(self._snapshot())
        return self._snapshot() != current

    def redo(self) -> bool:
        """Reapply the step most recently undone. False if there is none, or an edit was made since."""
        current = self._snapshot()
        self._forget_redo_if_edited(current)
        if not self._redo:
            return False
        self._restore(self._redo.pop())
        self._undo += [current, self._snapshot()]
        return True

    def _forget_redo_if_edited(self, current: tuple) -> None:
        # Redo steps only make sense from the exact state the last undo/redo left behind.
        if self._redo and current != self._state_after_undo:
            self._redo.clear()

    def _snapshot(self) -> tuple:
        return [replace(clip) for clip in self.videos], self.audio

    def _restore(self, snapshot: tuple) -> None:
        clips, self.audio = snapshot
        self.videos[:] = [replace(clip) for clip in clips]
        self._state_after_undo = snapshot

    # --- internals ----------------------------------------------------------

    def _index(self, clip: Clip) -> int:
        return next(index for index, other in enumerate(self.videos) if other is clip)

    def _room_around(self, clip: Clip) -> tuple[float, float]:
        """The stretch of timeline ``clip`` may occupy without touching its neighbours."""
        if clip.tile is None:
            return 0.0, float("inf")
        track = self.track(clip.tile)
        index = next(index for index, other in enumerate(track) if other is clip)
        free_from = track[index - 1].end_sec if index > 0 else 0.0
        free_until = track[index + 1].start_at_sec if index + 1 < len(track) else float("inf")
        return free_from, free_until


def _whole_canvas_tile(width: int, height: int) -> list[Tile]:
    return [Tile(0, 0, width, height, "Tile 1")]


def _differs(a: float, b: float) -> bool:
    return abs(a - b) > 0.0005
