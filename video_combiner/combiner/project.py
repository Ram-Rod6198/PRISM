"""The Combine mode's document: one video per tile, all playing at once."""

from __future__ import annotations

from video_combiner.project import Slot, TileProject, VideoItem


class CombinerProject(TileProject):
    """Everything that determines a combined render.

    Order carries the meaning: the n-th video plays in the n-th tile, and
    videos beyond the last tile are not rendered. The lists may be edited
    freely.
    """

    def tile_of(self, video: VideoItem) -> int | None:
        index = next(i for i, other in enumerate(self.videos) if other is video)
        return index if index < len(self.tiles) else None

    def slots(self) -> list[Slot]:
        """The layout resolved: each tile paired with its video and that video's position."""
        resolved = []
        for index, tile in enumerate(self.tiles):
            video = self.videos[index] if index < len(self.videos) else None
            x, y = video.position if video is not None and video.position is not None else (tile.x, tile.y)
            resolved.append(Slot(index, tile, video, x, y))
        return resolved

    @property
    def duration(self) -> float:
        """Length of the render: when the last rendered video finishes."""
        return max((slot.video.end_sec for slot in self.slots() if slot.video is not None), default=0.0)
