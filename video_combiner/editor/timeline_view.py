"""The timeline drawn as one row per tile plus an audio row, editable with the mouse."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from PIL import Image, ImageTk

from video_combiner.editor.timeline import Clip, Timeline
from video_combiner.timecode import format_duration

_LEFT_PAD = 10
_LABEL_W = 76
_RULER_H = 26
_ROW_GAP = 4
_MIN_ROW_H, _MAX_ROW_H = 24, 96  # Rows share the view's height within these; more rows than fit scroll.
_ASKED_HEIGHT = 120  # What the view asks of its container, which may well give it more or less.
_EDGE_PX = 7  # How close to a clip's end the pointer must be to grab the edge.
_SNAP_PX = 8
_DRAG_THRESHOLD_PX = 4
_MIN_ZOOM, _MAX_ZOOM = 2.0, 600.0  # Pixels per second.
_TICK_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600)
_FONT = ("Segoe UI", 9)
_FONT_SMALL = ("Segoe UI", 8)
_VIDEO_COLORS = ("#2f5d8a", "#8fc1f0")
_AUDIO_COLORS = ("#2f7a52", "#8fe0b3")
_SELECTED_OUTLINE = "#ffd34d"


@dataclass
class _Drag:
    """A mouse gesture in progress, with the clip as it was when the button went down."""

    mode: str  # "scrub", "body", "in" or "out"
    clip: Clip | None = None
    press_x: float = 0.0
    trim_start_sec: float = 0.0
    trim_end_sec: float = 0.0
    start_sec: float = 0.0
    moved: bool = False
    # Where a dragged clip would land: (tile, start). It is only moved for real on release,
    # so the clips it will push aside stay put while the user is still choosing a spot.
    landing: tuple[int | None, float] | None = None


class TimelineView(ttk.Frame):
    """Shows a Timeline and lets the user edit it directly.

    Mouse: click a clip to select it; drag it along its row to move it, or
    onto another row to move it to that tile (the audio row keeps only its
    sound); drag either end to trim. Click or drag anywhere else to move the
    playhead. The wheel scrolls, Ctrl+wheel zooms. Every drag is one undo step.

    ``playhead`` is the time the view points at. ``on_select(clip)`` reports a
    click on a clip (None: on nothing); ``on_change()`` follows every change
    the user made to the playhead or the timeline. Call ``refresh`` after
    changing the timeline or the selection from outside.

    The view uses whatever height it is given: the rows grow and shrink to
    fill it, and scroll when there are too many to fit.
    """

    def __init__(
        self,
        master: tk.Misc,
        timeline: Timeline,
        on_select: Callable[[Clip | None], None],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._timeline = timeline
        self._on_select = on_select
        self._on_change = on_change
        self.playhead = 0.0
        self._selected: Clip | None = None
        self._zoom = 60.0
        self._row_h = _MIN_ROW_H
        self._drag: _Drag | None = None
        self._thumbnails: dict[str, tuple[int, ImageTk.PhotoImage | None]] = {}  # By file, with the height made for.

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._labels = tk.Canvas(self, width=_LABEL_W, height=_ASKED_HEIGHT, highlightthickness=0, bg="#2a2d33")
        self._labels.grid(row=0, column=0, sticky="ns")
        self._canvas = tk.Canvas(self, height=_ASKED_HEIGHT, highlightthickness=0, bg="#22252a")
        self._canvas.grid(row=0, column=1, sticky="nsew")
        x_scroll = ttk.Scrollbar(self, orient="horizontal", command=self._canvas.xview)
        x_scroll.grid(row=1, column=1, sticky="ew")
        y_scroll = ttk.Scrollbar(self, orient="vertical", command=self._scroll_rows)
        y_scroll.grid(row=0, column=2, sticky="ns")
        self._canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)

        self._canvas.bind("<Button-1>", self._handle_press)
        self._canvas.bind("<B1-Motion>", self._handle_motion)
        self._canvas.bind("<ButtonRelease-1>", self._handle_release)
        self._canvas.bind("<Motion>", self._handle_hover)
        self._canvas.bind("<Configure>", lambda _e: self._draw())
        self._canvas.bind("<MouseWheel>", lambda e: self._handle_wheel(e, 1 if e.delta > 0 else -1))
        self._canvas.bind("<Button-4>", lambda e: self._handle_wheel(e, 1))  # X11 wheel up / down.
        self._canvas.bind("<Button-5>", lambda e: self._handle_wheel(e, -1))

    # --- driven from outside -------------------------------------------------

    def refresh(self, selected: Clip | None) -> None:
        """Redraw from the timeline, with ``selected`` highlighted."""
        self._selected = selected
        self.playhead = min(self.playhead, self._timeline.extent)
        self._draw()

    def set_playhead(self, sec: float) -> None:
        """Move the playhead (kept within the timeline) and scroll it into view."""
        self.playhead = max(0.0, min(sec, self._timeline.extent))
        self._draw_playhead()
        x, left = self._x_of(self.playhead), self._canvas.canvasx(0)
        width = self._canvas.winfo_width()
        if not left + 20 <= x <= left + width - 20:
            self._scroll_to(x - width / 2)

    def zoom(self, factor: float, around_x: float | None = None) -> None:
        """Scale the time axis by ``factor``, keeping the time at widget x ``around_x`` (default: centre) in place."""
        if around_x is None:
            around_x = self._canvas.winfo_width() / 2
        anchor_sec = self._sec_at(self._canvas.canvasx(around_x))
        self._zoom = max(_MIN_ZOOM, min(self._zoom * factor, _MAX_ZOOM))
        self._draw()
        self._scroll_to(self._x_of(anchor_sec) - around_x)

    def zoom_to_fit(self) -> None:
        """Choose the zoom at which the whole timeline is visible."""
        room = max(100, self._canvas.winfo_width() - 2 * _LEFT_PAD - 30)
        self._zoom = max(_MIN_ZOOM, min(room / max(self._timeline.extent, 1.0), _MAX_ZOOM))
        self._draw()
        self._scroll_to(0)

    # --- geometry -------------------------------------------------------------

    def _rows(self) -> list[int | None]:
        """The track shown in each row, top to bottom: every tile, then the audio track (None)."""
        return [*range(len(self._timeline.tiles)), None]

    def _fit_rows(self) -> None:
        """Choose the row height at which the rows fill the view."""
        room = self._canvas.winfo_height() - _RULER_H - _ROW_GAP
        self._row_h = max(_MIN_ROW_H, min(room // len(self._rows()) - _ROW_GAP, _MAX_ROW_H))

    def _row_y(self, row: int) -> int:
        return _RULER_H + _ROW_GAP + row * (self._row_h + _ROW_GAP)

    def _row_at(self, y: float) -> int:
        """The row at canvas y, or the nearest one when y is above or below them all."""
        row = int((y - _RULER_H - _ROW_GAP / 2) // (self._row_h + _ROW_GAP))
        return max(0, min(row, len(self._rows()) - 1))

    def _content_height(self) -> int:
        return self._row_y(len(self._rows()))

    def _x_of(self, sec: float) -> float:
        return _LEFT_PAD + sec * self._zoom

    def _sec_at(self, x: float) -> float:
        return (x - _LEFT_PAD) / self._zoom

    def _total_width(self) -> float:
        return max(self._canvas.winfo_width(), self._x_of(self._timeline.extent) + 160)

    def _scroll_to(self, left_x: float) -> None:
        self._canvas.xview_moveto(max(0.0, left_x) / self._total_width())

    def _scroll_rows(self, *args: str) -> None:
        self._canvas.yview(*args)
        self._labels.yview(*args)

    def _hit(self, x: float, y: float) -> tuple[Clip, str] | None:
        """The clip under canvas point (x, y) and the part grabbed: "in", "out" or "body"."""
        row = self._row_at(y)
        if not self._row_y(row) <= y <= self._row_y(row) + self._row_h:
            return None
        for clip in reversed(self._timeline.track(self._rows()[row])):  # Later clips are drawn on top.
            left, right = self._x_of(clip.start_at_sec), self._x_of(clip.end_sec)
            if left <= x <= right:
                edge = min(_EDGE_PX, (right - left) / 3)
                return clip, "in" if x - left <= edge else "out" if right - x <= edge else "body"
        return None

    def _snapped(self, sec: float, moving: Clip | None = None) -> float:
        """``sec``, or a nearby point worth aligning to: zero, the playhead, or another clip's edge."""
        points = [0.0, self._timeline.duration]
        if moving is not None:
            points.append(self.playhead)
        for clip in self._timeline.videos:
            if clip is not moving:
                points += [clip.start_at_sec, clip.end_sec]
        nearest = min(points, key=lambda point: abs(point - sec))
        return nearest if abs(nearest - sec) * self._zoom <= _SNAP_PX else sec

    # --- drawing --------------------------------------------------------------

    def _draw(self) -> None:
        canvas, timeline = self._canvas, self._timeline
        canvas.delete("all")
        rows = self._rows()
        self._fit_rows()
        total_w, content_h = self._total_width(), self._content_height()
        canvas.configure(scrollregion=(0, 0, total_w, content_h))
        self._draw_labels(content_h)

        for row, track in enumerate(rows):
            y = self._row_y(row)
            fill = "#2a322d" if track is None else "#2b2f36"
            canvas.create_rectangle(0, y, total_w, y + self._row_h, fill=fill, outline="")
        step = next((s for s in _TICK_STEPS if s * self._zoom >= 70), _TICK_STEPS[-1])
        for tick in range(int(self._sec_at(total_w) / step) + 1):
            x = self._x_of(tick * step)
            canvas.create_line(x, _RULER_H - 8, x, _RULER_H, fill="#8a8f98")
            canvas.create_text(
                x + 3, 3, text=_ruler_label(tick * step, step), anchor="nw", fill="#b8bcc4", font=_FONT_SMALL
            )

        if not timeline.videos:
            self._draw_hint(0, "Add Video puts videos here. Drag one to move it; drag its ends to trim.")
            self._draw_hint(len(rows) - 1, "Add Audio, or drag a video down here to use only its sound.")
        dragged = self._drag.clip if self._drag is not None and self._drag.landing is not None else None
        for row, track in enumerate(rows):
            for clip in timeline.track(track):
                self._draw_clip(clip, row, clip.start_at_sec, faded=clip is dragged)
        if dragged is not None:
            tile, start = self._drag.landing
            self._draw_clip(dragged, rows.index(tile), start)

        end_x = self._x_of(timeline.duration)
        if timeline.extent > timeline.duration and timeline.duration > 0:
            # Sound past the end of the picture is not exported; show where it is cut.
            cut_off = (end_x, _RULER_H, self._x_of(timeline.extent), content_h)
            canvas.create_rectangle(*cut_off, fill="#101010", stipple="gray50", outline="")
            canvas.create_line(end_x, _RULER_H, end_x, content_h, fill="#ff8a65", dash=(4, 3))
        self._draw_playhead()

    def _draw_playhead(self) -> None:
        canvas = self._canvas
        canvas.delete("playhead")
        x = self._x_of(self.playhead)
        canvas.create_line(x, 0, x, self._content_height(), fill="#ff5252", width=2, tags="playhead")
        canvas.create_polygon(x - 6, 0, x + 6, 0, x, 9, fill="#ff5252", outline="", tags="playhead")

    def _draw_labels(self, content_h: int) -> None:
        labels = self._labels
        labels.delete("all")
        labels.configure(scrollregion=(0, 0, _LABEL_W, content_h))
        for row, track in enumerate(self._rows()):
            name = "Audio" if track is None else self._timeline.tiles[track].name
            labels.create_text(
                8, self._row_y(row) + self._row_h // 2, text=name[:11], anchor="w", fill="#d0d4da", font=_FONT
            )

    def _draw_hint(self, row: int, text: str) -> None:
        self._canvas.create_text(
            self._canvas.canvasx(0) + _LEFT_PAD + 6,
            self._row_y(row) + self._row_h // 2,
            text=text,
            anchor="w",
            fill="#7d838c",
            font=_FONT,
        )

    def _draw_clip(self, clip: Clip, row: int, start_sec: float, faded: bool = False) -> None:
        canvas = self._canvas
        on_audio_row = self._rows()[row] is None
        fill, accent = _AUDIO_COLORS if on_audio_row else _VIDEO_COLORS
        left = self._x_of(start_sec)
        right = left + (clip.end_sec - clip.start_at_sec) * self._zoom
        top, bottom = self._row_y(row) + 2, self._row_y(row) + self._row_h - 2
        selected = clip is self._selected and not faded
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=fill,
            stipple="gray25" if faded else "",
            outline=_SELECTED_OUTLINE if selected else "#15171a",
            width=3 if selected else 1,
        )
        if faded:
            return
        # Grips mark the ends that can be dragged to trim.
        for grip_x in (left + 3, right - 3):
            if right - left > 14:
                canvas.create_line(grip_x, top + 7, grip_x, bottom - 7, fill=accent, width=2)

        text_x = left + 9
        thumbnail = None if on_audio_row else self._thumbnail(clip.media.thumb_path)
        if thumbnail is not None and right - left > thumbnail.width() + 24:
            canvas.create_image(left + 7, top + 2, image=thumbnail, anchor="nw")
            text_x += thumbnail.width() + 4
        # Canvas text cannot be clipped, so only as many characters as fit are drawn.
        fitting_chars = int((right - text_x - 6) / 7)
        if fitting_chars >= 3:
            length = format_duration(clip.end_sec - clip.start_at_sec)
            canvas.create_text(
                text_x, top + 4, text=clip.media.name[:fitting_chars], anchor="nw", fill="white", font=_FONT
            )
            if bottom - top >= 34:  # Room for a second line.
                canvas.create_text(
                    text_x, top + 20, text=length[:fitting_chars], anchor="nw", fill=accent, font=_FONT_SMALL
                )

    def _thumbnail(self, thumb_path: str | None) -> ImageTk.PhotoImage | None:
        if thumb_path is None:
            return None
        height = self._row_h - 8
        if self._thumbnails.get(thumb_path, (0, None))[0] != height:
            try:
                with Image.open(thumb_path) as image:
                    width = max(1, round(image.width * height / image.height))
                    picture = ImageTk.PhotoImage(image.convert("RGB").resize((width, height)))
            except OSError:
                picture = None
            self._thumbnails[thumb_path] = (height, picture)
        return self._thumbnails[thumb_path][1]

    # --- mouse ----------------------------------------------------------------

    def _handle_press(self, event: tk.Event) -> None:
        self._canvas.focus_set()
        x, y = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
        hit = self._hit(x, y)
        if hit is None:
            self._drag = _Drag("scrub")
            if y > _RULER_H:
                self._on_select(None)
            self._scrub(x)
            return
        clip, part = hit
        trim_start, trim_end = clip.trim_bounds()
        self._drag = _Drag(part, clip, x, trim_start, trim_end, clip.start_at_sec)
        self._on_select(clip)

    def _handle_motion(self, event: tk.Event) -> None:
        drag = self._drag
        if drag is None:
            return
        x, y = self._canvas.canvasx(event.x), self._canvas.canvasy(event.y)
        if drag.mode == "scrub":
            self._scrub(x)
            return
        if not drag.moved:
            to_another_row = drag.mode == "body" and self._rows()[self._row_at(y)] != drag.clip.tile
            if abs(x - drag.press_x) < _DRAG_THRESHOLD_PX and not to_another_row:
                return
        drag.moved = True
        self._apply_drag(drag, x, y)

    def _apply_drag(self, drag: _Drag, x: float, y: float) -> None:
        timeline, clip = self._timeline, drag.clip
        assert clip is not None
        moved_sec = (x - drag.press_x) / self._zoom
        length = clip.end_sec - clip.start_at_sec
        if drag.mode == "body":
            start = drag.start_sec + moved_sec
            snapped_start = self._snapped(start, moving=clip)
            snapped_end = self._snapped(start + length, moving=clip)
            if snapped_start != start:
                start = snapped_start
            elif snapped_end != start + length:
                start = snapped_end - length
            tile = self._rows()[self._row_at(y)]
            # A file without a picture cannot sit in a tile, and one without sound is no use on the audio row.
            if (tile is None and not clip.media.has_audio) or (tile is not None and not clip.media.has_video):
                tile = clip.tile
            drag.landing = (tile, max(0.0, start))
            self._draw()
            return
        if drag.mode == "out":
            end = self._snapped(drag.start_sec + (drag.trim_end_sec - drag.trim_start_sec) + moved_sec, moving=clip)
            timeline.trim(clip, trim_end_sec=clip.trim_start_sec + (end - clip.start_at_sec))
        else:
            start = self._snapped(drag.start_sec + moved_sec, moving=clip)
            timeline.trim(clip, trim_start_sec=drag.trim_start_sec + (start - drag.start_sec))
        self._draw()
        self._on_change()

    def _handle_release(self, event: tk.Event) -> None:
        drag, self._drag = self._drag, None
        if drag is None or drag.clip is None:
            return
        if not drag.moved:
            if drag.mode == "body":
                # A plain click on a clip also parks the playhead there, ready for a split.
                self._scrub(self._canvas.canvasx(event.x))
            return
        if drag.landing is not None:
            self._timeline.place(drag.clip, *drag.landing)
        self._timeline.checkpoint()
        self._draw()
        self._on_change()

    def _handle_hover(self, event: tk.Event) -> None:
        hit = self._hit(self._canvas.canvasx(event.x), self._canvas.canvasy(event.y))
        cursor = "" if hit is None else "sb_h_double_arrow" if hit[1] in ("in", "out") else "hand2"
        self._canvas.configure(cursor=cursor)

    def _handle_wheel(self, event: tk.Event, direction: int) -> None:
        if event.state & 0x4:  # Ctrl held.
            self.zoom(1.25 if direction > 0 else 0.8, around_x=event.x)
        else:
            self._canvas.xview_scroll(-3 * direction, "units")

    def _scrub(self, x: float) -> None:
        self.playhead = max(0.0, min(self._snapped(self._sec_at(x)), self._timeline.extent))
        self._draw_playhead()
        self._on_change()


def _ruler_label(sec: float, step: float) -> str:
    minutes, seconds = divmod(sec, 60)
    return f"{int(minutes)}:{seconds:04.1f}" if step < 1 else f"{int(minutes)}:{int(seconds):02d}"
