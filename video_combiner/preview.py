"""A scaled, clickable drawing of a project's output canvas."""

from __future__ import annotations

import io
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from video_combiner.ffmpeg import FFmpegError, still_frame
from video_combiner.project import Selection, Slot, TileProject
from video_combiner.widgets import UiThread

_PICKABLE_KINDS = {
    "Videos Only": ("video",),
    "Text Only": ("text",),
    "Tiles Only": ("tile",),
    "Videos + Text": ("text", "video"),
}
_SELECTED_OUTLINE = "#4da3ff"
_SELECTED_TEXT_OUTLINE = "#ffd34d"
_OUTSIDE_CANVAS_FILL = "#e6e6e6"
_LABEL_FONT = ("Segoe UI", 9, "bold")
_STILL_HEIGHT = 540
_REMEMBERED_STILLS = 40


class PreviewPane(ttk.Frame):
    """Shows what the render will look like: the tiles, the video in each, and the text on top.

    ``slots()`` says which video is in which tile right now. A slot that names
    a moment of its video is drawn with that exact frame (fetched in the
    background; the pane redraws itself when it arrives), any other with the
    video's thumbnail.

    Clicking a layer reports it through ``on_select`` (None for a click on
    nothing). With "Allow Dragging" ticked, dragging a layer moves it in the
    project and then calls ``on_move``. Which kinds of layer react to the mouse,
    the zoom level and whether tile names are drawn are the pane's own business.
    """

    def __init__(
        self,
        master: tk.Misc,
        project: TileProject,
        slots: Callable[[], list[Slot]],
        on_select: Callable[[Selection], None],
        on_move: Callable[[], None],
        title: str = "Static Preview",
    ) -> None:
        super().__init__(master)
        self._project = project
        self._slots = slots
        self._on_select = on_select
        self._on_move = on_move
        self._stills = _Stills(self, on_arrival=self._draw)
        self._last_still: dict[int, Image.Image] = {}  # Per tile; shown while a newer frame is on its way.
        self._playing: Image.Image | None = None
        self._selection: Selection = None
        self._zoom = 1.0
        self._pickable = tk.StringVar(value="Videos Only")
        self._allow_drag = tk.BooleanVar(value=False)
        self._hide_tile_names = tk.BooleanVar(value=True)
        # Everything under the pointer can be found here: (kind, index, x1, y1, x2, y2), bottom-most first.
        self._hit_boxes: list[tuple[str, int, int, int, int, int]] = []
        self._dragging: tuple[str, int, int, int] | None = None  # kind, index, grab offset x, y
        self._press_xy = (0, 0)
        self._drag_started = False
        self._thumbnails: dict[str, Image.Image | None] = {}
        self._photos: list[ImageTk.PhotoImage] = []  # Tk drops images that Python no longer references.
        self._redraw_job: str | None = None

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text=title).pack(side="left")
        ttk.Button(header, text="-", width=3, command=lambda: self._set_zoom(self._zoom / 1.25)).pack(
            side="left", padx=(8, 2)
        )
        ttk.Button(header, text="+", width=3, command=lambda: self._set_zoom(self._zoom * 1.25)).pack(
            side="left", padx=(0, 2)
        )
        ttk.Button(header, text="Reset Zoom", command=self._reset_zoom).pack(side="left", padx=(0, 8))
        ttk.Label(header, text="Selectable:").pack(side="left", padx=(12, 4))
        ttk.Combobox(
            header, state="readonly", values=list(_PICKABLE_KINDS), textvariable=self._pickable, width=14
        ).pack(side="left")
        ttk.Checkbutton(header, text="Allow Dragging", variable=self._allow_drag).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(header, text="Hide Tile Names", variable=self._hide_tile_names, command=self._draw).pack(
            side="left", padx=(8, 0)
        )

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self._canvas = tk.Canvas(body, width=960, height=540, bg="#101010", highlightthickness=1)
        self._canvas.configure(highlightbackground="#303030")
        self._canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(body, orient="horizontal", command=self._canvas.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self._canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self._canvas.bind("<Button-1>", self._handle_press)
        self._canvas.bind("<B1-Motion>", self._handle_drag)
        self._canvas.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_dragging", None))
        self._canvas.bind("<Configure>", self._handle_resize)

    def refresh(self, selection: Selection) -> None:
        """Redraw from the project, outlining ``selection``."""
        self._selection = selection
        self._playing = None
        self._draw()

    def show_playing(self, picture: Image.Image) -> None:
        """Show a finished picture of the whole canvas instead of the layers, until the next ``refresh``."""
        self._playing = picture
        self._draw()

    def picture_size(self) -> tuple[int, int]:
        """The size, in screen pixels, at which the output canvas is currently drawn."""
        scale = self._layout()[0]
        return max(2, round(self._project.canvas_w * scale)), max(2, round(self._project.canvas_h * scale))

    # --- geometry -------------------------------------------------------------

    def _layout(self) -> tuple[float, float, float, int, int]:
        """(scale, x offset, y offset, drawing width, drawing height) of the output canvas in widget pixels.

        The canvas is fitted to the widget, times the zoom, and centred; once
        zoomed past the widget's size the drawing grows and scrollbars take over.
        """
        view_w, view_h = max(1, self._canvas.winfo_width()), max(1, self._canvas.winfo_height())
        out_w, out_h = self._project.canvas_w, self._project.canvas_h
        scale = min(view_w / out_w, view_h / out_h) * self._zoom
        total_w, total_h = max(view_w, round(out_w * scale)), max(view_h, round(out_h * scale))
        return scale, (total_w - out_w * scale) / 2, (total_h - out_h * scale) / 2, total_w, total_h

    def _set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.25, min(zoom, 8.0))
        self._draw()

    def _reset_zoom(self) -> None:
        self._canvas.xview_moveto(0.0)
        self._canvas.yview_moveto(0.0)
        self._set_zoom(1.0)

    def _handle_resize(self, _event: object) -> None:
        # Resizing fires a burst of events; redraw once it settles.
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(30, self._draw)

    # --- drawing --------------------------------------------------------------

    def _draw(self) -> None:
        self._redraw_job = None
        canvas, project = self._canvas, self._project
        scale, off_x, off_y, total_w, total_h = self._layout()

        def box(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
            left, top = round(off_x + x * scale), round(off_y + y * scale)
            return left, top, left + max(1, round(w * scale)), top + max(1, round(h * scale))

        canvas.delete("all")
        self._photos.clear()
        canvas.configure(scrollregion=(0, 0, total_w, total_h))
        canvas.create_rectangle(0, 0, total_w, total_h, fill="black", outline="")
        if self._playing is not None:
            left, top, right, bottom = box(0, 0, project.canvas_w, project.canvas_h)
            picture = self._playing
            if picture.size != (right - left, bottom - top):
                picture = picture.resize((right - left, bottom - top), Image.Resampling.BILINEAR)
            self._photos.append(ImageTk.PhotoImage(picture))
            canvas.create_image(left, top, image=self._photos[-1], anchor="nw")
            self._draw_frame_around_output(box, total_w, total_h)
            return

        tile_boxes, video_boxes, text_boxes = [], [], []
        show_names = not self._hide_tile_names.get()
        slots = self._slots()
        self._stills.want([(slot.video.media.path, slot.frame_sec) for slot in slots if _has_moment(slot)])

        for slot in slots:
            x1, y1, x2, y2 = box(slot.tile.x, slot.tile.y, slot.tile.w, slot.tile.h)
            tile_boxes.append(("tile", slot.index, x1, y1, x2, y2))
            canvas.create_rectangle(x1, y1, x2, y2, outline="#3a3a3a")
            if show_names:
                self._draw_name(slot.tile.name, x1, y1)

        for slot in slots:
            if slot.video is None:
                continue
            x1, y1, x2, y2 = box(slot.x, slot.y, slot.tile.w, slot.tile.h)
            video_index = next(i for i, video in enumerate(project.videos) if video is slot.video)
            video_boxes.append(("video", video_index, x1, y1, x2, y2))
            photo = self._picture_of(slot, x2 - x1, y2 - y1)
            if photo is not None:
                canvas.create_image(x1, y1, image=photo, anchor="nw")
            else:
                canvas.create_rectangle(x1, y1, x2, y2, fill="#121212", outline="")
            if show_names:
                self._draw_name(slot.tile.name, x1, y1)

        for index, text in enumerate(project.texts):
            if not text.enabled or not text.text.strip():
                continue
            x, y, _, _ = box(text.x, text.y, 1, 1)
            font = ("Segoe UI", -max(8, round(text.size * scale)), "bold")  # Negative: size in pixels.
            try:
                item = canvas.create_text(
                    x, y, text=text.text, anchor="nw", fill=text.color.strip() or "white", font=font
                )
            except tk.TclError:  # Not a colour Tk knows; FFmpeg may still accept it.
                item = canvas.create_text(x, y, text=text.text, anchor="nw", fill="white", font=font)
            x1, y1, x2, y2 = canvas.bbox(item)
            text_boxes.append(("text", index, x1, y1, x2, y2))

        self._hit_boxes = tile_boxes + video_boxes + text_boxes
        # The selection is outlined last so no layer can hide it.
        for kind, index, x1, y1, x2, y2 in self._hit_boxes:
            if self._selection == (kind, index):
                if kind == "text":
                    canvas.create_rectangle(x1 - 2, y1 - 2, x2 + 2, y2 + 2, outline=_SELECTED_TEXT_OUTLINE, width=2)
                else:
                    canvas.create_rectangle(x1 + 2, y1 + 2, x2 - 2, y2 - 2, outline=_SELECTED_OUTLINE, width=3)

        self._draw_frame_around_output(box, total_w, total_h)

    def _draw_frame_around_output(
        self, box: Callable[..., tuple[int, int, int, int]], total_w: int, total_h: int
    ) -> None:
        """Grey out everything beyond the output frame, so overflowing layers read as cropped."""
        canvas, project = self._canvas, self._project
        left, top, right, bottom = box(0, 0, project.canvas_w, project.canvas_h)
        for x1, y1, x2, y2 in (
            (0, 0, total_w, top),
            (0, bottom, total_w, total_h),
            (0, top, left, bottom),
            (right, top, total_w, bottom),
        ):
            if x2 > x1 and y2 > y1:
                canvas.create_rectangle(x1, y1, x2, y2, fill=_OUTSIDE_CANVAS_FILL, outline="")
        canvas.create_rectangle(left, top, right, bottom, outline="#39d353", width=2)

    def _draw_name(self, name: str, x: int, y: int) -> None:
        self._canvas.create_rectangle(x, y, x + 70, y + 22, fill="#000000", outline="")
        self._canvas.create_text(x + 8, y + 11, text=name[:14], anchor="w", fill="white", font=_LABEL_FONT)

    def _picture_of(self, slot: Slot, width: int, height: int) -> ImageTk.PhotoImage | None:
        """The slot's video cropped to fill ``width`` x ``height``, as the render crops it; None if unavailable."""
        assert slot.video is not None
        source, resampling = None, Image.Resampling.BILINEAR
        if _has_moment(slot):
            source = self._stills.get(slot.video.media.path, slot.frame_sec) or self._last_still.get(slot.index)
            if source is not None:
                self._last_still[slot.index] = source
        if source is None:
            source, resampling = self._thumbnail(slot.video.media.thumb_path), Image.Resampling.LANCZOS
        if source is None:
            return None
        photo = ImageTk.PhotoImage(ImageOps.fit(source, (width, height), method=resampling))
        self._photos.append(photo)
        return photo

    def _thumbnail(self, thumb_path: str | None) -> Image.Image | None:
        if thumb_path is None:
            return None
        if thumb_path not in self._thumbnails:
            try:
                with Image.open(thumb_path) as image:
                    self._thumbnails[thumb_path] = image.convert("RGB")
            except OSError:
                self._thumbnails[thumb_path] = None
        return self._thumbnails[thumb_path]

    # --- mouse ----------------------------------------------------------------

    def _handle_press(self, event: tk.Event) -> None:
        x, y = round(self._canvas.canvasx(event.x)), round(self._canvas.canvasy(event.y))
        self._dragging = None
        self._press_xy = (event.x, event.y)
        self._drag_started = False
        for kind in _PICKABLE_KINDS[self._pickable.get()]:
            # Later boxes were drawn on top, so they win.
            for box_kind, index, x1, y1, x2, y2 in reversed(self._hit_boxes):
                if box_kind == kind and x1 <= x <= x2 and y1 <= y <= y2:
                    self._dragging = (kind, index, x - x1, y - y1)
                    self._on_select((kind, index))
                    return
        self._on_select(None)

    def _handle_drag(self, event: tk.Event) -> None:
        if self._dragging is None or not self._allow_drag.get():
            return
        if not self._drag_started:
            # A click with a slightly unsteady hand is not a drag.
            if abs(event.x - self._press_xy[0]) + abs(event.y - self._press_xy[1]) < 3:
                return
            self._drag_started = True
        kind, index, grab_x, grab_y = self._dragging
        scale, off_x, off_y, _, _ = self._layout()
        x = round((self._canvas.canvasx(event.x) - grab_x - off_x) / scale)
        y = round((self._canvas.canvasy(event.y) - grab_y - off_y) / scale)
        if kind == "video":
            self._project.videos[index].position = (x, y)
        elif kind == "tile":
            self._project.tiles[index].x, self._project.tiles[index].y = x, y
        else:
            self._project.texts[index].x, self._project.texts[index].y = x, y
        self._on_move()


def _has_moment(slot: Slot) -> bool:
    return slot.video is not None and slot.frame_sec is not None


class _Stills:
    """Exact frames of videos, fetched in the background and remembered for a while.

    ``want`` names the frames that matter now; anything asked for earlier and
    not yet fetched is dropped, so scrubbing never works through a backlog.
    ``on_arrival()`` is called on the Tk thread whenever a wanted frame came in.
    """

    def __init__(self, widget: tk.Misc, on_arrival: Callable[[], None]) -> None:
        self._on_arrival = on_arrival
        self._ui = UiThread(widget)
        self._frames: dict[tuple[str, float], Image.Image | None] = {}
        self._wanted: list[tuple[str, float]] = []
        self._fetching = False

    def want(self, frames: list[tuple[str, float]]) -> None:
        self._wanted = [key for key in map(_key, frames) if key not in self._frames]
        self._fetch_next()

    def get(self, path: str, sec: float) -> Image.Image | None:
        """The frame if it has been fetched; None if not yet, or if it cannot be had."""
        return self._frames.get(_key((path, sec)))

    def _fetch_next(self) -> None:
        if self._fetching or not self._wanted:
            return
        self._fetching = True
        key = self._wanted.pop(0)

        def work() -> None:
            try:
                image: Image.Image | None = Image.open(io.BytesIO(still_frame(*key, max_height=_STILL_HEIGHT)))
                image.load()
            except (FFmpegError, OSError):
                image = None  # Drawn from the thumbnail instead.
            self._ui.call(self._fetched, key, image)

        threading.Thread(target=work, daemon=True).start()

    def _fetched(self, key: tuple[str, float], image: Image.Image | None) -> None:
        self._fetching = False
        self._frames[key] = image.convert("RGB") if image is not None else None
        while len(self._frames) > _REMEMBERED_STILLS:
            del self._frames[next(iter(self._frames))]
        # Redrawing asks again for whatever is still missing, which starts the next fetch.
        self._on_arrival()
        self._fetch_next()


def _key(frame: tuple[str, float]) -> tuple[str, float]:
    return frame[0], round(frame[1], 3)
