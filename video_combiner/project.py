"""What every PRISM document is made of: a canvas of tiles, videos shown in them, and text on top."""

from __future__ import annotations

from dataclasses import dataclass

from video_combiner.ffmpeg import MediaInfo

# What is heard, besides a tile index meaning "only the videos in that tile".
AUDIO_MIX = "mix"
AUDIO_NONE = "none"

# The layer the user is working on: ("video" | "tile" | "text", index into that list), or None.
Selection = tuple[str, int] | None


@dataclass
class Tile:
    """A named rectangle of the output canvas, in output pixels."""

    x: int
    y: int
    w: int
    h: int
    name: str


@dataclass
class VideoItem:
    """A video in the project, with how much of it plays and when."""

    media: MediaInfo
    include_in_mix: bool = True
    # Top-left corner in output pixels; None means "at the corner of my tile".
    position: tuple[int, int] | None = None
    trim_start_sec: float = 0.0
    trim_end_sec: float | None = None  # None plays to the end of the file.
    start_at_sec: float = 0.0  # When the trimmed segment begins in the output.

    def trim_bounds(self) -> tuple[float, float]:
        """(start, end) of the segment that plays, in file time, always within the file and ordered."""
        start = max(0.0, self.trim_start_sec)
        end = self.media.duration if self.trim_end_sec is None else self.trim_end_sec
        end = min(max(0.0, end), self.media.duration)
        return start, max(start, end)

    @property
    def end_sec(self) -> float:
        """When this video's segment finishes in the output."""
        start, end = self.trim_bounds()
        return max(0.0, self.start_at_sec) + (end - start)


@dataclass
class TextOverlay:
    """Text drawn above all videos, in output pixels."""

    enabled: bool = False
    text: str = ""
    x: int = 40
    y: int = 40
    size: int = 72
    color: str = "white"
    start_at_sec: float = 0.0
    duration_sec: float | None = None  # None keeps the text up until the end.


@dataclass(frozen=True)
class Slot:
    """One tile and the video showing in it (None if the tile is empty).

    ``index`` is the tile's place in the project. ``x``/``y`` is where the
    video's top-left corner lands: the tile's corner unless the video carries
    its own position. The video is always drawn at the tile's size.
    ``frame_sec`` is the moment of the video's file that is on screen, where
    the mode knows it; None stands for "the video in general".
    """

    index: int
    tile: Tile
    video: VideoItem | None
    x: int
    y: int
    frame_sec: float | None = None


def grid_tiles(width: int, height: int) -> list[Tile]:
    """Four tiles covering a ``width`` x ``height`` canvas as a 2x2 grid."""
    left_w, top_h = max(1, width // 2), max(1, height // 2)
    right_w, bottom_h = max(1, width - left_w), max(1, height - top_h)
    return [
        Tile(0, 0, left_w, top_h, "Tile 1"),
        Tile(left_w, 0, right_w, top_h, "Tile 2"),
        Tile(0, top_h, left_w, bottom_h, "Tile 3"),
        Tile(left_w, top_h, right_w, bottom_h, "Tile 4"),
    ]


class TileProject:
    """The part of a document that both modes share, and the panels that edit it rely on.

    ``tiles``, ``videos`` and ``texts`` are plain ordered lists. Later tiles
    and later texts are drawn on top of earlier ones. Which tile a video plays
    in, and what happens when its timing is edited, is each mode's business:
    see ``tile_of`` and ``set_timing``.

    ``audio`` is ``AUDIO_MIX`` (every video marked ``include_in_mix``),
    ``AUDIO_NONE``, or a tile index (only the videos in that tile are heard).
    """

    def __init__(self) -> None:
        self.canvas_w = 3840
        self.canvas_h = 2160
        self.tiles: list[Tile] = grid_tiles(self.canvas_w, self.canvas_h)
        self.videos: list[VideoItem] = []
        self.texts: list[TextOverlay] = []
        self.audio: str | int = AUDIO_MIX

    def tile_of(self, video: VideoItem) -> int | None:
        """The index of the tile ``video`` plays in; None if it is not shown in any."""
        raise NotImplementedError

    def set_timing(
        self, video: VideoItem, trim_start_sec: float, trim_end_sec: float | None, start_at_sec: float
    ) -> None:
        """Change how much of ``video`` plays and when, as far as the mode's rules allow."""
        video.trim_start_sec, video.trim_end_sec, video.start_at_sec = trim_start_sec, trim_end_sec, start_at_sec

    @property
    def fps(self) -> float:
        """Output frame rate: that of the first video in the list."""
        return self.videos[0].media.fps if self.videos else 30.0

    def set_layout(self, width: int, height: int, tiles: list[Tile]) -> None:
        """Replace the canvas size and tiles (e.g. from a preset). The tiles are copied."""
        self.canvas_w, self.canvas_h = max(2, int(width)), max(2, int(height))
        self.tiles = [Tile(t.x, t.y, max(1, t.w), max(1, t.h), t.name) for t in tiles]

    def resize_canvas(self, width: int, height: int, scale_content: bool = False) -> None:
        """Change the canvas size. With ``scale_content``, tiles, video positions and texts scale along."""
        width, height = max(2, int(width)), max(2, int(height))
        if scale_content:
            sx, sy = width / self.canvas_w, height / self.canvas_h
            for tile in self.tiles:
                tile.x, tile.y = round(tile.x * sx), round(tile.y * sy)
                tile.w, tile.h = max(1, round(tile.w * sx)), max(1, round(tile.h * sy))
            for video in self.videos:
                if video.position is not None:
                    video.position = (round(video.position[0] * sx), round(video.position[1] * sy))
            for text in self.texts:
                text.x, text.y = round(text.x * sx), round(text.y * sy)
        self.canvas_w, self.canvas_h = width, height

    def add_tile(self) -> int:
        """Append a tile shaped like the last one, nudged so both stay visible; returns its index."""
        number = len(self.tiles) + 1
        name = f"Overlay Tile {number}" if number > 4 else f"Tile {number}"
        if self.tiles:
            last = self.tiles[-1]
            self.tiles.append(Tile(last.x + 40, last.y + 40, last.w, last.h, name))
        else:
            self.tiles.append(Tile(0, 0, max(1, self.canvas_w // 2), max(1, self.canvas_h // 2), name))
        return len(self.tiles) - 1
