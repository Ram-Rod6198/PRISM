"""The timeline drawn as two tracks that can be edited with the mouse."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from PIL import Image, ImageTk

from video_combiner.editor.timeline import Clip, Timeline
from video_combiner.timecode import format_duration

_LEFT_PAD = 10
_RULER_H = 26
_TRACK_H = 62
_VIDEO_Y = _RULER_H + 6
_AUDIO_Y = _VIDEO_Y + _TRACK_H + 10
_HEIGHT = _AUDIO_Y + _TRACK_H + 8
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
    in_sec: float = 0.0
    out_sec: float = 0.0
    start_sec: float = 0.0
    moved: bool = False


class TimelineView(ttk.Frame):
    """Shows a Timeline and lets the user edit it directly.

    Mouse: click a clip to select it, drag it to reorder (video) or reposition
    (audio), drag either end to trim; click or drag anywhere else to move the
    playhead. The wheel scrolls, Ctrl+wheel zooms. Every drag is one undo step.

    ``selected`` and ``playhead`` hold the view's state. ``on_change()`` is
    called after the user changed either of them or the timeline. Call
    ``refresh()`` after changing the timeline from outside.
    """

    def __init__(self, master: tk.Misc, timeline: Timeline, on_change: Callable[[], None]) -> None:
        super().__init__(master)
        self._timeline = timeline
        self._on_change = on_change
        self.selected: Clip | None = None
        self.playhead = 0.0
        self._zoom = 60.0
        self._drag: _Drag | None = None
        self._thumbnails: dict[str, ImageTk.PhotoImage | None] = {}

        self.columnconfigure(1, weight=1)
        labels = tk.Canvas(self, width=52, height=_HEIGHT, highlightthickness=0, bg="#2a2d33")
        labels.grid(row=0, column=0, sticky="ns")
        for text, y in (("Video", _VIDEO_Y), ("Audio", _AUDIO_Y)):
            labels.create_text(26, y + _TRACK_H // 2, text=text, fill="#d0d4da", font=_FONT)

        self._canvas = tk.Canvas(self, height=_HEIGHT, highlightthickness=0, bg="#22252a")
        self._canvas.grid(row=0, column=1, sticky="ew")
        scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self._canvas.xview)
        scrollbar.grid(row=1, column=1, sticky="ew")
        self._canvas.configure(xscrollcommand=scrollbar.set)

        self._canvas.bind("<Button-1>", self._handle_press)
        self._canvas.bind("<B1-Motion>", self._handle_motion)
        self._canvas.bind("<ButtonRelease-1>", self._handle_release)
        self._canvas.bind("<Motion>", self._handle_hover)
        self._canvas.bind("<Configure>", lambda _e: self._draw())
        self._canvas.bind("<MouseWheel>", lambda e: self._handle_wheel(e, 1 if e.delta > 0 else -1))
        self._canvas.bind("<Button-4>", lambda e: self._handle_wheel(e, 1))  # X11 wheel up / down.
        self._canvas.bind("<Button-5>", lambda e: self._handle_wheel(e, -1))

    # --- driven from outside -------------------------------------------------

    def refresh(self) -> None:
        """Redraw after the timeline was changed elsewhere; a selected clip that is gone is deselected."""
        clips = self._timeline.video + self._timeline.audio
        if not any(self.selected is clip for clip in clips):
            self.selected = None
        self.playhead = min(self.playhead, self._timeline.extent)
        self._draw()

    def select(self, clip: Clip | None) -> None:
        self.selected = clip
        self._draw()

    def set_playhead(self, sec: float) -> None:
        """Move the playhead (kept within the timeline) and scroll it into view."""
        self.playhead = max(0.0, min(sec, self._timeline.extent))
        self._draw()
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

    def _x_of(self, sec: float) -> float:
        return _LEFT_PAD + sec * self._zoom

    def _sec_at(self, x: float) -> float:
        return (x - _LEFT_PAD) / self._zoom

    def _total_width(self) -> float:
        return max(self._canvas.winfo_width(), self._x_of(self._timeline.extent) + 160)

    def _scroll_to(self, left_x: float) -> None:
        self._canvas.xview_moveto(max(0.0, left_x) / self._total_width())

    def _hit(self, x: float, y: float) -> tuple[Clip, str] | None:
        """The clip under canvas point (x, y) and the part grabbed: "in", "out" or "body"."""
        if _VIDEO_Y <= y <= _VIDEO_Y + _TRACK_H:
            track = self._timeline.video
        elif _AUDIO_Y <= y <= _AUDIO_Y + _TRACK_H:
            track = self._timeline.audio
        else:
            return None
        for clip in reversed(track):  # Later clips are drawn on top.
            left, right = self._x_of(clip.start_sec), self._x_of(clip.end_sec)
            if left <= x <= right:
                edge = min(_EDGE_PX, (right - left) / 3)
                return clip, "in" if x - left <= edge else "out" if right - x <= edge else "body"
        return None

    def _snapped(self, sec: float, moving: Clip | None = None) -> float:
        """``sec``, or a nearby point worth aligning to: zero, the playhead, or another clip's edge."""
        points = [0.0, self._timeline.duration]
        if moving is not None:
            points.append(self.playhead)
        for clip in self._timeline.video + self._timeline.audio:
            if clip is not moving:
                points += [clip.start_sec, clip.end_sec]
        nearest = min(points, key=lambda point: abs(point - sec))
        return nearest if abs(nearest - sec) * self._zoom <= _SNAP_PX else sec

    # --- drawing --------------------------------------------------------------

    def _draw(self) -> None:
        canvas, timeline = self._canvas, self._timeline
        canvas.delete("all")
        total_w = self._total_width()
        canvas.configure(scrollregion=(0, 0, total_w, _HEIGHT))
        canvas.create_rectangle(0, _VIDEO_Y, total_w, _VIDEO_Y + _TRACK_H, fill="#2b2f36", outline="")
        canvas.create_rectangle(0, _AUDIO_Y, total_w, _AUDIO_Y + _TRACK_H, fill="#2a322d", outline="")

        step = next((s for s in _TICK_STEPS if s * self._zoom >= 70), _TICK_STEPS[-1])
        for tick in range(int(self._sec_at(total_w) / step) + 1):
            x = self._x_of(tick * step)
            canvas.create_line(x, _RULER_H - 8, x, _RULER_H, fill="#8a8f98")
            canvas.create_text(
                x + 3, 3, text=_ruler_label(tick * step, step), anchor="nw", fill="#b8bcc4", font=_FONT_SMALL
            )

        if not timeline.video:
            self._draw_hint(_VIDEO_Y, "Add Clips: they play one after another, in this order")
        if not timeline.audio:
            self._draw_hint(_AUDIO_Y, "Add Audio: a video or audio file whose sound plays under the clips")
        for clip in timeline.video:
            self._draw_clip(clip, _VIDEO_Y, _VIDEO_COLORS, with_thumbnail=True)
        for clip in timeline.audio:
            self._draw_clip(clip, _AUDIO_Y, _AUDIO_COLORS, with_thumbnail=False)

        end_x = self._x_of(timeline.duration)
        if timeline.extent > timeline.duration and timeline.video:
            # Audio past the end of the picture is not exported; show where it is cut.
            cut_off = (end_x, _AUDIO_Y, self._x_of(timeline.extent), _AUDIO_Y + _TRACK_H)
            canvas.create_rectangle(*cut_off, fill="#101010", stipple="gray50", outline="")
            canvas.create_line(end_x, _RULER_H, end_x, _HEIGHT, fill="#ff8a65", dash=(4, 3))

        x = self._x_of(self.playhead)
        canvas.create_line(x, 0, x, _HEIGHT, fill="#ff5252", width=2)
        canvas.create_polygon(x - 6, 0, x + 6, 0, x, 9, fill="#ff5252", outline="")

    def _draw_hint(self, track_y: int, text: str) -> None:
        self._canvas.create_text(
            self._canvas.canvasx(0) + _LEFT_PAD + 6,
            track_y + _TRACK_H // 2,
            text=text,
            anchor="w",
            fill="#7d838c",
            font=_FONT,
        )

    def _draw_clip(self, clip: Clip, track_y: int, colors: tuple[str, str], with_thumbnail: bool) -> None:
        canvas = self._canvas
        fill, accent = colors
        left, right = self._x_of(clip.start_sec), self._x_of(clip.end_sec)
        top, bottom = track_y + 2, track_y + _TRACK_H - 2
        selected = clip is self.selected
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=fill,
            outline=_SELECTED_OUTLINE if selected else "#15171a",
            width=3 if selected else 1,
        )
        # Grips mark the ends that can be dragged to trim.
        for grip_x in (left + 3, right - 3):
            if right - left > 14:
                canvas.create_line(grip_x, top + 8, grip_x, bottom - 8, fill=accent, width=2)

        text_x = left + 9
        thumbnail = self._thumbnail(clip.media.thumb_path) if with_thumbnail else None
        if thumbnail is not None and right - left > thumbnail.width() + 24:
            canvas.create_image(left + 7, top + 2, image=thumbnail, anchor="nw")
            text_x += thumbnail.width() + 4
        # Canvas text cannot be clipped, so only as many characters as fit are drawn.
        fitting_chars = int((right - text_x - 6) / 7)
        if fitting_chars >= 3:
            details = format_duration(clip.duration)
            if clip.volume != 1.0:
                details += f"   vol {clip.volume:.0%}"
            canvas.create_text(
                text_x, top + 5, text=clip.media.name[:fitting_chars], anchor="nw", fill="white", font=_FONT
            )
            canvas.create_text(
                text_x, top + 24, text=details[:fitting_chars], anchor="nw", fill=accent, font=_FONT_SMALL
            )

    def _thumbnail(self, thumb_path: str | None) -> ImageTk.PhotoImage | None:
        if thumb_path is None:
            return None
        if thumb_path not in self._thumbnails:
            try:
                with Image.open(thumb_path) as image:
                    height = _TRACK_H - 8
                    width = max(1, round(image.width * height / image.height))
                    self._thumbnails[thumb_path] = ImageTk.PhotoImage(image.convert("RGB").resize((width, height)))
            except OSError:
                self._thumbnails[thumb_path] = None
        return self._thumbnails[thumb_path]

    # --- mouse ----------------------------------------------------------------

    def _handle_press(self, event: tk.Event) -> None:
        self._canvas.focus_set()
        x = self._canvas.canvasx(event.x)
        hit = self._hit(x, event.y)
        if hit is None:
            self._drag = _Drag("scrub")
            if event.y > _RULER_H:
                self.selected = None
            self._scrub(x)
            return
        clip, part = hit
        self._drag = _Drag(part, clip, x, clip.in_sec, clip.out_sec, clip.start_sec)
        self.selected = clip
        self._draw()
        self._on_change()

    def _handle_motion(self, event: tk.Event) -> None:
        drag = self._drag
        if drag is None:
            return
        x = self._canvas.canvasx(event.x)
        if drag.mode == "scrub":
            self._scrub(x)
            return
        if not drag.moved:
            if abs(x - drag.press_x) < _DRAG_THRESHOLD_PX:
                return
            drag.moved = True
            self._timeline.checkpoint()
        self._apply_drag(drag, x)
        self._draw()
        self._on_change()

    def _apply_drag(self, drag: _Drag, x: float) -> None:
        timeline, clip = self._timeline, drag.clip
        assert clip is not None
        moved_sec = (x - drag.press_x) / self._zoom
        is_audio = timeline.is_audio(clip)
        if drag.mode == "out":
            end = self._snapped(drag.start_sec + (drag.out_sec - drag.in_sec) + moved_sec, moving=clip)
            timeline.trim(clip, out_sec=clip.in_sec + (end - clip.start_sec))
        elif drag.mode == "in" and is_audio:
            start = self._snapped(drag.start_sec + moved_sec, moving=clip)
            timeline.trim(clip, in_sec=drag.in_sec + (start - drag.start_sec))
        elif drag.mode == "in":
            # A video clip's start is pinned by the clip before it, so the drag maps straight to file time.
            timeline.trim(clip, in_sec=drag.in_sec + moved_sec)
        elif is_audio:
            start = drag.start_sec + moved_sec
            snapped_start = self._snapped(start, moving=clip)
            snapped_end = self._snapped(start + clip.duration, moving=clip)
            if snapped_start != start:
                start = snapped_start
            elif snapped_end != start + clip.duration:
                start = snapped_end - clip.duration
            timeline.slide(clip, start)
        else:
            # The clip goes before the first neighbour whose middle the pointer has not passed.
            # Judging against the row *without* the dragged clip keeps the result steady under the pointer.
            pointer_sec, position, index = self._sec_at(x), 0.0, 0
            for other in timeline.video:
                if other is clip:
                    continue
                if pointer_sec < position + other.duration / 2:
                    break
                position += other.duration
                index += 1
            timeline.reorder(clip, index)

    def _handle_release(self, event: tk.Event) -> None:
        drag, self._drag = self._drag, None
        if drag is not None and drag.mode == "body" and not drag.moved:
            # A plain click on a clip also parks the playhead there, ready for a split.
            self._scrub(self._canvas.canvasx(event.x))

    def _handle_hover(self, event: tk.Event) -> None:
        hit = self._hit(self._canvas.canvasx(event.x), event.y)
        cursor = "" if hit is None else "sb_h_double_arrow" if hit[1] in ("in", "out") else "hand2"
        self._canvas.configure(cursor=cursor)

    def _handle_wheel(self, event: tk.Event, direction: int) -> None:
        if event.state & 0x4:  # Ctrl held.
            self.zoom(1.25 if direction > 0 else 0.8, around_x=event.x)
        else:
            self._canvas.xview_scroll(-3 * direction, "units")

    def _scrub(self, x: float) -> None:
        self.playhead = max(0.0, min(self._snapped(self._sec_at(x)), self._timeline.extent))
        self._draw()
        self._on_change()


def _ruler_label(sec: float, step: float) -> str:
    minutes, seconds = divmod(sec, 60)
    return f"{int(minutes)}:{seconds:04.1f}" if step < 1 else f"{int(minutes)}:{int(seconds):02d}"
