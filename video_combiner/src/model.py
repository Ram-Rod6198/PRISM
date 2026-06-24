from __future__ import annotations

from dataclasses import dataclass


DEFAULT_TILE_COORDS = {
    1: (0, 0),
    2: (1920, 0),
    3: (0, 1080),
    4: (1920, 1080),
}
DEFAULT_CANVAS_W = 3840
DEFAULT_CANVAS_H = 2160
DEFAULT_TILE_RECTS_4K = [
    (0, 0, 1920, 1080),
    (1920, 0, 1920, 1080),
    (0, 1080, 1920, 1080),
    (1920, 1080, 1920, 1080),
]


@dataclass
class VideoItem:
    path: str
    duration: float
    fps: float
    width: int
    height: int
    has_audio: bool
    thumb_path: str | None = None
    include_in_mix: bool = True
    custom_position: bool = False
    pos_x: int = 0
    pos_y: int = 0
    trim_start_sec: float = 0.0
    trim_end_sec: float | None = None
    start_at_sec: float = 0.0
    layer_z: int = 1
    custom_layer_z: bool = False


@dataclass
class TextOverlaySettings:
    enabled: bool = False
    text: str = ""
    x: int = 40
    y: int = 40
    size: int = 72
    color: str = "white"
    start_at_sec: float = 0.0
    duration_sec: float | None = None


class VideoListModel:
    def __init__(self) -> None:
        self.items: list[VideoItem] = []
        self.text_overlays: list[TextOverlaySettings] = []
        self.output_width: int = DEFAULT_CANVAS_W
        self.output_height: int = DEFAULT_CANVAS_H
        self.tile_rects: list[tuple[int, int, int, int]] = self._default_tile_rects_for_canvas(
            self.output_width, self.output_height
        )
        self.tile_z_levels: list[int] = [1, 2, 3, 4]
        self.tile_names: list[str] = [f"Tile {i}" for i in range(1, 5)]

    def add_items(self, new_items: list[VideoItem]) -> None:
        for offset, item in enumerate(new_items, start=1):
            idx = len(self.items) + offset - 1
            item.layer_z = self.tile_z_level(idx)
            item.custom_layer_z = False
        self.items.extend(new_items)

    def remove(self, index: int) -> VideoItem:
        return self.items.pop(index)

    def move(self, src: int, dst: int) -> int:
        if not self.items:
            return 0
        src = max(0, min(src, len(self.items) - 1))
        dst = max(0, min(dst, len(self.items) - 1))
        if src == dst:
            return dst
        item = self.items.pop(src)
        self.items.insert(dst, item)
        return dst

    def move_up(self, index: int) -> int:
        if index <= 0 or index >= len(self.items):
            return index
        return self.move(index, index - 1)

    def move_down(self, index: int) -> int:
        if index < 0 or index >= len(self.items) - 1:
            return index
        return self.move(index, index + 1)

    def top_four(self) -> list[VideoItem | None]:
        top = self.items[:4]
        return top + [None] * (4 - len(top))

    def max_duration_top_four(self) -> float:
        durations = [self.video_timeline_duration(item) for item in self.items[:4]]
        return max(durations, default=0.0)

    def rendered_slot_count(self) -> int:
        return max(1, len(self.tile_rects))

    def mapped_items(self) -> list[VideoItem | None]:
        count = self.rendered_slot_count()
        out: list[VideoItem | None] = []
        for idx in range(count):
            out.append(self.items[idx] if idx < len(self.items) else None)
        return out

    def max_duration_mapped(self) -> float:
        count = self.rendered_slot_count()
        durations = [self.video_timeline_duration(item) for item in self.items[:count]]
        return max(durations, default=0.0)

    def default_tile_coords(self, list_index: int) -> tuple[int, int] | None:
        rect = self.tile_rect(list_index)
        if rect is None:
            return None
        return (rect[0], rect[1])

    def tile_rect(self, list_index: int) -> tuple[int, int, int, int] | None:
        if list_index < 0 or list_index >= len(self.tile_rects):
            return None
        return self.tile_rects[list_index]

    def tile_name(self, tile_index: int) -> str:
        if 0 <= tile_index < len(self.tile_names):
            return self.tile_names[tile_index] or f"Tile {tile_index + 1}"
        return f"Tile {tile_index + 1}"

    def get_tile_names_copy(self) -> list[str]:
        names = list(self.tile_names)
        while len(names) < len(self.tile_rects):
            names.append(f"Tile {len(names) + 1}")
        return names

    def effective_item_coords(self, list_index: int) -> tuple[int, int] | None:
        if list_index < 0 or list_index >= len(self.items):
            return None
        item = self.items[list_index]
        if item.custom_position:
            return (int(item.pos_x), int(item.pos_y))
        return self.default_tile_coords(list_index)

    def effective_top_four_positions(self) -> list[tuple[int, int]]:
        positions: list[tuple[int, int]] = []
        for idx in range(4):
            if idx < len(self.items):
                coords = self.effective_item_coords(idx)
                positions.append(coords if coords is not None else (self.default_tile_coords(idx) or (0, 0)))
            else:
                positions.append(self.default_tile_coords(idx) or (0, 0))
        return positions

    def effective_mapped_positions(self) -> list[tuple[int, int]]:
        count = self.rendered_slot_count()
        positions: list[tuple[int, int]] = []
        for idx in range(count):
            if idx < len(self.items):
                coords = self.effective_item_coords(idx)
                positions.append(coords if coords is not None else (self.default_tile_coords(idx) or (0, 0)))
            else:
                positions.append(self.default_tile_coords(idx) or (0, 0))
        return positions

    def effective_top_four_tile_rects(self) -> list[tuple[int, int, int, int]]:
        rects: list[tuple[int, int, int, int]] = []
        for idx in range(4):
            rect = self.tile_rect(idx) or (0, 0, max(1, self.output_width // 2), max(1, self.output_height // 2))
            x, y, w, h = rect
            if idx < len(self.items):
                item = self.items[idx]
                if item.custom_position:
                    x, y = int(item.pos_x), int(item.pos_y)
            rects.append((int(x), int(y), max(1, int(w)), max(1, int(h))))
        return rects

    def effective_mapped_tile_rects(self) -> list[tuple[int, int, int, int]]:
        count = self.rendered_slot_count()
        rects: list[tuple[int, int, int, int]] = []
        for idx in range(count):
            rect = self.tile_rect(idx) or (0, 0, max(1, self.output_width // 2), max(1, self.output_height // 2))
            x, y, w, h = rect
            if idx < len(self.items):
                item = self.items[idx]
                if item.custom_position:
                    x, y = int(item.pos_x), int(item.pos_y)
            rects.append((int(x), int(y), max(1, int(w)), max(1, int(h))))
        return rects

    def tile_z_level(self, tile_index: int) -> int:
        if tile_index < 0:
            return 1
        if tile_index < len(self.tile_z_levels):
            return max(1, int(self.tile_z_levels[tile_index]))
        return max(1, tile_index + 1)

    def get_tile_z_levels_copy(self) -> list[int]:
        levels = [max(1, int(z)) for z in self.tile_z_levels]
        if len(levels) < len(self.tile_rects):
            for i in range(len(levels), len(self.tile_rects)):
                levels.append(max(1, i + 1))
        return levels

    def effective_top_four_video_z_levels(self) -> list[int]:
        out: list[int] = []
        for idx in range(4):
            item = self.items[idx] if idx < len(self.items) else None
            if item is None:
                out.append(self.tile_z_level(idx))
                continue
            out.append(int(item.layer_z) if item.custom_layer_z else self.tile_z_level(idx))
        return out

    def effective_mapped_video_z_levels(self) -> list[int]:
        count = self.rendered_slot_count()
        out: list[int] = []
        for idx in range(count):
            item = self.items[idx] if idx < len(self.items) else None
            if item is None:
                out.append(self.tile_z_level(idx))
                continue
            out.append(int(item.layer_z) if item.custom_layer_z else self.tile_z_level(idx))
        return out

    def tile_size(self) -> tuple[int, int]:
        rect = self.tile_rect(0)
        if rect is not None:
            return max(1, int(rect[2])), max(1, int(rect[3]))
        return max(1, self.output_width // 2), max(1, self.output_height // 2)

    def set_canvas_size(self, width: int, height: int) -> None:
        self.output_width = max(2, int(width))
        self.output_height = max(2, int(height))
        if not self.tile_rects:
            self.tile_rects = self._default_tile_rects_for_canvas(self.output_width, self.output_height)
        if not self.tile_z_levels:
            self.tile_z_levels = [i + 1 for i in range(len(self.tile_rects))]

    def set_canvas_layout(
        self,
        width: int,
        height: int,
        tile_rects: list[tuple[int, int, int, int]] | None = None,
        tile_z_levels: list[int] | None = None,
        tile_names: list[str] | None = None,
    ) -> None:
        self.output_width = max(2, int(width))
        self.output_height = max(2, int(height))
        if tile_rects and len(tile_rects) >= 1:
            self.tile_rects = [
                (
                    int(r[0]),
                    int(r[1]),
                    max(1, int(r[2])),
                    max(1, int(r[3])),
                )
                for r in tile_rects
            ]
        else:
            self.tile_rects = self._default_tile_rects_for_canvas(self.output_width, self.output_height)
        if tile_z_levels:
            self.tile_z_levels = [max(1, int(z)) for z in tile_z_levels[: len(self.tile_rects)]]
        else:
            self.tile_z_levels = [i + 1 for i in range(len(self.tile_rects))]
        while len(self.tile_z_levels) < len(self.tile_rects):
            self.tile_z_levels.append(len(self.tile_z_levels) + 1)
        if tile_names:
            self.tile_names = [str(n).strip() or f"Tile {i + 1}" for i, n in enumerate(tile_names[: len(self.tile_rects)])]
        else:
            self.tile_names = [f"Tile {i + 1}" for i in range(len(self.tile_rects))]
        while len(self.tile_names) < len(self.tile_rects):
            self.tile_names.append(f"Tile {len(self.tile_names) + 1}")
        self._normalize_tile_z_order()
        self._sync_inherited_video_z_levels()

    def update_tile_rect(self, tile_index: int, x: int, y: int, w: int, h: int) -> None:
        if tile_index < 0:
            return
        while len(self.tile_rects) <= tile_index:
            self.tile_rects.append((0, 0, 1, 1))
            self.tile_z_levels.append(len(self.tile_z_levels) + 1)
            self.tile_names.append(f"Tile {len(self.tile_names) + 1}")
        self.tile_rects[tile_index] = (int(x), int(y), max(1, int(w)), max(1, int(h)))

    def get_tile_rects_copy(self) -> list[tuple[int, int, int, int]]:
        return [tuple(rect) for rect in self.tile_rects]

    def add_tile_rect(self, rect: tuple[int, int, int, int] | None = None) -> int:
        if rect is None:
            if self.tile_rects:
                lx, ly, lw, lh = self.tile_rects[-1]
                rect = (lx + 40, ly + 40, lw, lh)
            else:
                rect = (0, 0, max(1, self.output_width // 2), max(1, self.output_height // 2))
        x, y, w, h = rect
        self.tile_rects.append((int(x), int(y), max(1, int(w)), max(1, int(h))))
        self.tile_z_levels.append(len(self.tile_z_levels) + 1)
        default_name = f"Overlay Tile {len(self.tile_rects)}" if len(self.tile_rects) > 4 else f"Tile {len(self.tile_rects)}"
        self.tile_names.append(default_name)
        self._normalize_tile_z_order()
        return len(self.tile_rects) - 1

    def remove_tile_rect(self, tile_index: int) -> tuple[int, int, int, int] | None:
        if tile_index < 0 or tile_index >= len(self.tile_rects):
            return None
        removed = self.tile_rects.pop(tile_index)
        if tile_index < len(self.tile_z_levels):
            self.tile_z_levels.pop(tile_index)
        if tile_index < len(self.tile_names):
            self.tile_names.pop(tile_index)
        if not self.tile_z_levels and self.tile_rects:
            self.tile_z_levels = [i + 1 for i in range(len(self.tile_rects))]
        if not self.tile_names and self.tile_rects:
            self.tile_names = [f"Tile {i + 1}" for i in range(len(self.tile_rects))]
        while len(self.tile_z_levels) < len(self.tile_rects):
            self.tile_z_levels.append(len(self.tile_z_levels) + 1)
        while len(self.tile_names) < len(self.tile_rects):
            self.tile_names.append(f"Tile {len(self.tile_names) + 1}")
        self._normalize_tile_z_order()
        self._sync_inherited_video_z_levels()
        return removed

    def move_tile_rect_up(self, index: int) -> int:
        if index <= 0 or index >= len(self.tile_rects):
            return index
        self.tile_rects[index - 1], self.tile_rects[index] = self.tile_rects[index], self.tile_rects[index - 1]
        if index < len(self.tile_z_levels):
            self.tile_z_levels[index - 1], self.tile_z_levels[index] = self.tile_z_levels[index], self.tile_z_levels[index - 1]
        if index < len(self.tile_names):
            self.tile_names[index - 1], self.tile_names[index] = self.tile_names[index], self.tile_names[index - 1]
        self._normalize_tile_z_order()
        self._sync_inherited_video_z_levels()
        return index - 1

    def move_tile_rect_down(self, index: int) -> int:
        if index < 0 or index >= len(self.tile_rects) - 1:
            return index
        self.tile_rects[index + 1], self.tile_rects[index] = self.tile_rects[index], self.tile_rects[index + 1]
        if (index + 1) < len(self.tile_z_levels):
            self.tile_z_levels[index + 1], self.tile_z_levels[index] = self.tile_z_levels[index], self.tile_z_levels[index + 1]
        if (index + 1) < len(self.tile_names):
            self.tile_names[index + 1], self.tile_names[index] = self.tile_names[index], self.tile_names[index + 1]
        self._normalize_tile_z_order()
        self._sync_inherited_video_z_levels()
        return index + 1

    def set_tile_name(self, tile_index: int, name: str) -> None:
        if tile_index < 0:
            return
        while len(self.tile_names) <= tile_index:
            self.tile_names.append(f"Tile {len(self.tile_names) + 1}")
        cleaned = (name or "").strip()
        self.tile_names[tile_index] = cleaned or f"Tile {tile_index + 1}"

    def set_tile_z_level(self, tile_index: int, z_level: int) -> None:
        if tile_index < 0:
            return
        while len(self.tile_z_levels) <= tile_index:
            self.tile_z_levels.append(len(self.tile_z_levels) + 1)
        self.tile_z_levels[tile_index] = max(1, int(z_level))
        self._sync_inherited_video_z_levels()

    def add_text_overlay(self, overlay: TextOverlaySettings | None = None) -> int:
        self.text_overlays.append(overlay or TextOverlaySettings())
        return len(self.text_overlays) - 1

    def remove_text_overlay(self, index: int) -> TextOverlaySettings:
        return self.text_overlays.pop(index)

    def move_text_overlay_up(self, index: int) -> int:
        if index <= 0 or index >= len(self.text_overlays):
            return index
        item = self.text_overlays.pop(index)
        self.text_overlays.insert(index - 1, item)
        return index - 1

    def move_text_overlay_down(self, index: int) -> int:
        if index < 0 or index >= len(self.text_overlays) - 1:
            return index
        item = self.text_overlays.pop(index)
        self.text_overlays.insert(index + 1, item)
        return index + 1

    @staticmethod
    def video_trim_bounds(item: VideoItem) -> tuple[float, float]:
        start = max(0.0, float(item.trim_start_sec or 0.0))
        end_raw = item.duration if item.trim_end_sec is None else float(item.trim_end_sec)
        end = min(max(0.0, end_raw), max(0.0, item.duration))
        if end < start:
            end = start
        return start, end

    @classmethod
    def video_segment_duration(cls, item: VideoItem) -> float:
        start, end = cls.video_trim_bounds(item)
        return max(0.0, end - start)

    @classmethod
    def video_timeline_duration(cls, item: VideoItem) -> float:
        return max(0.0, float(item.start_at_sec or 0.0)) + cls.video_segment_duration(item)

    def set_video_z_level(self, index: int, z_level: int) -> int:
        if not self.items or index < 0 or index >= len(self.items):
            return 0
        self.items[index].layer_z = max(1, int(z_level))
        self.items[index].custom_layer_z = True
        return index

    def set_text_z_level(self, index: int, z_level: int) -> int:
        if not self.text_overlays:
            return 0
        dst = max(0, min(int(z_level) - 1, len(self.text_overlays) - 1))
        if index == dst:
            return dst
        item = self.text_overlays.pop(index)
        self.text_overlays.insert(dst, item)
        return dst

    def _sync_inherited_video_z_levels(self) -> None:
        for idx, item in enumerate(self.items[: self.rendered_slot_count()]):
            if not item.custom_layer_z:
                item.layer_z = self.tile_z_level(idx)

    def _normalize_tile_z_order(self) -> None:
        # Lower in the tile list should be on top (higher z).
        self.tile_z_levels = [i + 1 for i in range(len(self.tile_rects))]

    @staticmethod
    def _default_tile_rects_for_canvas(width: int, height: int) -> list[tuple[int, int, int, int]]:
        w = max(2, int(width))
        h = max(2, int(height))
        half_w = max(1, w // 2)
        half_h = max(1, h // 2)
        return [
            (0, 0, half_w, half_h),
            (half_w, 0, max(1, w - half_w), half_h),
            (0, half_h, half_w, max(1, h - half_h)),
            (half_w, half_h, max(1, w - half_w), max(1, h - half_h)),
        ]
