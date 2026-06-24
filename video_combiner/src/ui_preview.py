from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageOps, ImageTk

from video_combiner.src.model import TextOverlaySettings, VideoItem


class PreviewCanvas(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        width: int = 960,
        height: int = 540,
        on_tile_click: Callable[[str | None, int | None], None] | None = None,
        on_item_drag: Callable[[str, int, int, int], None] | None = None,
    ) -> None:
        super().__init__(master, width=width, height=height, bg="#101010", highlightthickness=1)
        self.configure(highlightbackground="#303030")
        self.preview_w = width
        self.preview_h = height
        self.zoom_factor = 1.0
        self.tile_w = width // 2
        self.tile_h = height // 2
        self._on_tile_click = on_tile_click
        self._on_item_drag = on_item_drag
        self._selected_tile: int | None = None
        self._selected_text_index: int | None = None
        self._images: list[ImageTk.PhotoImage] = []
        self._video_hit_regions: list[tuple[int, int, int, int, int]] = []
        self._text_hit_regions: list[tuple[int, int, int, int, int]] = []
        self._tile_hit_regions: list[tuple[int, int, int, int, int]] = []
        self.canvas_output_w = 3840
        self.canvas_output_h = 2160
        self.selection_mode = "videos"
        self._drag_target: tuple[str, int] | None = None
        self._drag_offset_px: tuple[int, int] = (0, 0)
        self._drag_start_canvas_xy: tuple[int, int] | None = None
        self._drag_active = False
        self.bind("<Button-1>", self._handle_press)
        self.bind("<B1-Motion>", self._handle_drag_motion)
        self.bind("<ButtonRelease-1>", self._handle_release)
        self.bind("<Configure>", self._handle_configure)

    def _handle_press(self, event: tk.Event) -> None:
        if not self._on_tile_click:
            return
        ex = int(self.canvasx(event.x))
        ey = int(self.canvasy(event.y))
        hit = self._hit_test(ex, ey)
        self._drag_target = None
        self._drag_active = False
        self._drag_start_canvas_xy = (ex, ey)
        if hit is not None:
            kind, idx, x1, y1, _x2, _y2 = hit
            self._drag_target = (kind, idx)
            self._drag_offset_px = (ex - x1, ey - y1)
            self._on_tile_click(kind, idx)
            return
        self._on_tile_click(None, None)

    def _handle_drag_motion(self, event: tk.Event) -> None:
        if self._on_item_drag is None or self._drag_target is None:
            return
        ex = int(self.canvasx(event.x))
        ey = int(self.canvasy(event.y))
        if self._drag_start_canvas_xy is not None and not self._drag_active:
            sx, sy = self._drag_start_canvas_xy
            if abs(ex - sx) + abs(ey - sy) < 3:
                return
            self._drag_active = True
        kind, idx = self._drag_target
        off_x, off_y = self._drag_offset_px
        new_left_px = ex - off_x
        new_top_px = ey - off_y
        out_x, out_y = self._preview_to_output(new_left_px, new_top_px)
        self._on_item_drag(kind, idx, out_x, out_y)

    def _handle_release(self, _event: tk.Event) -> None:
        self._drag_target = None
        self._drag_start_canvas_xy = None
        self._drag_active = False

    def _hit_test(self, ex: int, ey: int) -> tuple[str, int, int, int, int, int] | None:
        # Priority mirrors click-selection behavior.
        if self.selection_mode in {"text", "both"}:
            for text_idx, x1, y1, x2, y2 in reversed(self._text_hit_regions):
                if x1 <= ex <= x2 and y1 <= ey <= y2:
                    return ("text", text_idx, x1, y1, x2, y2)
        if self.selection_mode == "tiles":
            for tile_idx, x1, y1, x2, y2 in reversed(self._tile_hit_regions):
                if x1 <= ex <= x2 and y1 <= ey <= y2:
                    return ("tile", tile_idx, x1, y1, x2, y2)
        if self.selection_mode in {"videos", "both"}:
            for tile_idx, x1, y1, x2, y2 in reversed(self._video_hit_regions):
                if x1 <= ex <= x2 and y1 <= ey <= y2:
                    return ("video", tile_idx, x1, y1, x2, y2)
        return None

    def _handle_click(self, event: tk.Event) -> None:
        # Backwards-compat shim (unused, but kept if external code binds to it).
        self._handle_press(event)

    def _handle_configure(self, event: tk.Event) -> None:
        w = max(1, int(getattr(event, "width", self.winfo_width())))
        h = max(1, int(getattr(event, "height", self.winfo_height())))
        if w != self.preview_w or h != self.preview_h:
            self.preview_w = w
            self.preview_h = h

    def set_selected_tile(self, tile_index: int | None, text_index: int | None = None) -> None:
        self._selected_tile = tile_index
        self._selected_text_index = text_index

    def set_selection_mode(self, mode: str) -> None:
        self.selection_mode = mode if mode in {"videos", "text", "both", "tiles"} else "videos"

    def render_tiles(
        self,
        items_by_slots: list[VideoItem | None],
        positions: list[tuple[int, int]] | None = None,
        tile_rects: list[tuple[int, int, int, int]] | None = None,
        tile_labels: list[str] | None = None,
        show_tile_labels: bool = True,
        video_z_levels: list[int] | None = None,
        text_overlays: list[TextOverlaySettings] | None = None,
        canvas_size: tuple[int, int] | None = None,
    ) -> None:
        self.delete("all")
        self._images.clear()
        self._video_hit_regions.clear()
        self._text_hit_regions.clear()
        self._tile_hit_regions.clear()
        if canvas_size:
            self.canvas_output_w = max(2, int(canvas_size[0]))
            self.canvas_output_h = max(2, int(canvas_size[1]))
        virtual_w, virtual_h = self._virtual_size()
        self.configure(scrollregion=(0, 0, virtual_w, virtual_h))
        self.create_rectangle(0, 0, virtual_w, virtual_h, fill="black", outline="")

        half_w = self.canvas_output_w // 2
        half_h = self.canvas_output_h // 2
        default_rects = [
            (0, 0, half_w, half_h),
            (half_w, 0, max(1, self.canvas_output_w - half_w), half_h),
            (0, half_h, half_w, max(1, self.canvas_output_h - half_h)),
            (half_w, half_h, max(1, self.canvas_output_w - half_w), max(1, self.canvas_output_h - half_h)),
        ]
        guide_rects = (
            [
                (int(r[0]), int(r[1]), max(1, int(r[2])), max(1, int(r[3])))
                for r in tile_rects
            ]
            if tile_rects and len(tile_rects) >= 1
            else default_rects
        )
        slot_count = max(1, len(items_by_slots))
        video_rects = list(guide_rects[:slot_count])
        while len(video_rects) < slot_count:
            video_rects.append(default_rects[len(video_rects)])
        draw_positions = (
            positions
            if positions and len(positions) >= slot_count
            else [(r[0], r[1]) for r in video_rects]
        )

        # Draw locked grid guides first.
        for tile_index, (gx, gy, gw, gh) in enumerate(guide_rects, start=1):
            tile_label = (
                str(tile_labels[tile_index - 1]).strip()
                if tile_labels and (tile_index - 1) < len(tile_labels) and str(tile_labels[tile_index - 1]).strip()
                else f"Tile {tile_index}"
            )
            px, py = self._to_preview(gx, gy)
            pw, ph = self._scale_wh(gw, gh)
            self._tile_hit_regions.append((tile_index, px, py, px + pw, py + ph))
            self.create_rectangle(px, py, px + pw, py + ph, outline="#3a3a3a")
            if show_tile_labels:
                self.create_rectangle(px, py, px + 70, py + 22, fill="#000000", outline="")
                self.create_text(
                    px + 8,
                    py + 11,
                    text=tile_label[:14],
                    anchor="w",
                    fill="white",
                    font=("Segoe UI", 9, "bold"),
                )
            if self._selected_tile == tile_index:
                self.create_rectangle(px + 2, py + 2, px + pw - 2, py + ph - 2, outline="#4da3ff", width=3)

        tile_draw_order = list(range(1, slot_count + 1))
        z_levels = (
            list(video_z_levels[:slot_count])
            if video_z_levels and len(video_z_levels) >= slot_count
            else [i + 1 for i in range(slot_count)]
        )
        tile_draw_order.sort(
            key=lambda t: (
                0 if items_by_slots[t - 1] is None else 1,
                (z_levels[t - 1] if items_by_slots[t - 1] is not None else -10_000),
                t,
            )
        )

        for tile_index in tile_draw_order:
            item = items_by_slots[tile_index - 1]
            x_full, y_full = draw_positions[tile_index - 1]
            _tx, _ty, tw_full, th_full = video_rects[tile_index - 1]
            x, y = self._to_preview(x_full, y_full)
            pw, ph = self._scale_wh(tw_full, th_full)
            if item is not None:
                self._video_hit_regions.append((tile_index, x, y, x + pw, y + ph))
            if item and item.thumb_path and Path(item.thumb_path).exists():
                try:
                    with Image.open(item.thumb_path) as img:
                        thumb = ImageOps.fit(
                            img.convert("RGB"),
                            (pw, ph),
                            method=_resample_lanczos(),
                        )
                    tk_image = ImageTk.PhotoImage(thumb)
                    self._images.append(tk_image)
                    self.create_image(x, y, image=tk_image, anchor="nw")
                except Exception:
                    pass
            elif item:
                self.create_rectangle(x, y, x + pw, y + ph, fill="#121212", outline="")

            if item:
                tile_label = (
                    str(tile_labels[tile_index - 1]).strip()
                    if tile_labels and (tile_index - 1) < len(tile_labels) and str(tile_labels[tile_index - 1]).strip()
                    else f"Tile {tile_index}"
                )
                if show_tile_labels:
                    self.create_rectangle(x, y, x + 70, y + 22, fill="#000000", outline="")
                    self.create_text(
                        x + 8,
                        y + 11,
                        text=tile_label[:14],
                        anchor="w",
                        fill="white",
                        font=("Segoe UI", 9, "bold"),
                    )

            if self._selected_tile == tile_index and item is not None:
                self.create_rectangle(
                    x + 2,
                    y + 2,
                    x + pw - 2,
                    y + ph - 2,
                    outline="#4da3ff",
                    width=3,
                )

        for text_index, overlay in enumerate(text_overlays or []):
            if not overlay.enabled or not overlay.text.strip():
                continue
            tx, ty = self._to_preview(overlay.x, overlay.y)
            font_px = max(8, int(overlay.size * (self.preview_h / self.canvas_output_h)))
            text_fill = (overlay.color or "white").strip() or "white"
            try:
                text_id = self.create_text(
                    tx,
                    ty,
                    text=overlay.text,
                    anchor="nw",
                    fill=text_fill,
                    font=("Segoe UI", font_px, "bold"),
                )
            except tk.TclError:
                text_id = self.create_text(
                    tx,
                    ty,
                    text=overlay.text,
                    anchor="nw",
                    fill="white",
                    font=("Segoe UI", font_px, "bold"),
                )
            bbox = self.bbox(text_id)
            if bbox:
                x1, y1, x2, y2 = bbox
                self._text_hit_regions.append((text_index, x1, y1, x2, y2))
                if self._selected_text_index == text_index:
                    self.create_rectangle(x1 - 2, y1 - 2, x2 + 2, y2 + 2, outline="#ffd34d", width=2)

        self._draw_output_bounds_overlay()

    def _to_preview(self, x: int, y: int) -> tuple[int, int]:
        scale, off_x, off_y = self._preview_transform()
        return (
            int(round(off_x + (x * scale))),
            int(round(off_y + (y * scale))),
        )

    def _scale_wh(self, w: int, h: int) -> tuple[int, int]:
        scale, _off_x, _off_y = self._preview_transform()
        return (
            max(1, int(round(w * scale))),
            max(1, int(round(h * scale))),
        )

    def _preview_to_output(self, px: int, py: int) -> tuple[int, int]:
        scale, off_x, off_y = self._preview_transform()
        if scale <= 0:
            return 0, 0
        x = int(round((px - off_x) / scale))
        y = int(round((py - off_y) / scale))
        return x, y

    def _preview_transform(self) -> tuple[float, float, float]:
        out_w = max(1, int(self.canvas_output_w))
        out_h = max(1, int(self.canvas_output_h))
        fit_scale = min(self.preview_w / out_w, self.preview_h / out_h)
        scale = fit_scale * max(0.1, float(self.zoom_factor))
        draw_w = out_w * scale
        draw_h = out_h * scale
        virtual_w = max(float(self.preview_w), draw_w)
        virtual_h = max(float(self.preview_h), draw_h)
        off_x = (virtual_w - draw_w) / 2.0
        off_y = (virtual_h - draw_h) / 2.0
        return scale, off_x, off_y

    def _output_preview_rect(self) -> tuple[int, int, int, int]:
        scale, off_x, off_y = self._preview_transform()
        out_w = max(1, int(round(self.canvas_output_w * scale)))
        out_h = max(1, int(round(self.canvas_output_h * scale)))
        x1 = int(round(off_x))
        y1 = int(round(off_y))
        x2 = x1 + out_w
        y2 = y1 + out_h
        return x1, y1, x2, y2

    def _draw_output_bounds_overlay(self) -> None:
        x1, y1, x2, y2 = self._output_preview_rect()
        virtual_w, virtual_h = self._virtual_size()

        # Mask outside the real output canvas so overflowed content looks clipped.
        mask_fill = "#e6e6e6"
        if y1 > 0:
            self.create_rectangle(0, 0, virtual_w, y1, fill=mask_fill, outline="")
        if y2 < virtual_h:
            self.create_rectangle(0, y2, virtual_w, virtual_h, fill=mask_fill, outline="")
        if x1 > 0:
            self.create_rectangle(0, y1, x1, y2, fill=mask_fill, outline="")
        if x2 < virtual_w:
            self.create_rectangle(x2, y1, virtual_w, y2, fill=mask_fill, outline="")

        # Actual render canvas boundary.
        self.create_rectangle(x1, y1, x2, y2, outline="#39d353", width=2)

    def _virtual_size(self) -> tuple[int, int]:
        out_w = max(1, int(self.canvas_output_w))
        out_h = max(1, int(self.canvas_output_h))
        fit_scale = min(self.preview_w / out_w, self.preview_h / out_h)
        scale = fit_scale * max(0.1, float(self.zoom_factor))
        draw_w = out_w * scale
        draw_h = out_h * scale
        return max(self.preview_w, int(round(draw_w))), max(self.preview_h, int(round(draw_h)))

    def set_zoom_factor(self, zoom: float) -> None:
        self.zoom_factor = max(0.25, min(float(zoom), 8.0))

    def zoom_in(self) -> None:
        self.set_zoom_factor(self.zoom_factor * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom_factor(self.zoom_factor / 1.25)

    def reset_zoom(self) -> None:
        self.set_zoom_factor(1.0)


def _resample_lanczos() -> int:
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS
