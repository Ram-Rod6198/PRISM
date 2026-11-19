"""The Edit mode: cut clips together on a timeline and lay audio underneath."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from video_combiner.editor.clip_inspector import ClipInspector
from video_combiner.editor.composer import compose, frame_size
from video_combiner.editor.frame_preview import FramePreview
from video_combiner.editor.timeline import Timeline
from video_combiner.editor.timeline_view import TimelineView
from video_combiner.export import ExportBar
from video_combiner.media_picker import pick_media
from video_combiner.timecode import format_timecode

_FRAME_SIZES: dict[str, tuple[int, int] | None] = {
    "Same as first clip": None,
    "3840 x 2160 (4K)": (3840, 2160),
    "1920 x 1080": (1920, 1080),
    "1280 x 720": (1280, 720),
    "1080 x 1920 (vertical)": (1080, 1920),
}
_TYPING_WIDGETS = ("TEntry", "Entry", "TCombobox", "Text")


class EditorWorkspace(ttk.Frame):
    """The whole Edit tab: frame preview, clip inspector and export on top, toolbar and timeline below.

    It owns the timeline and turns buttons and keys into edits; the timeline
    view handles the mouse. After anything changes, ``_sync`` brings every
    panel back in step.
    """

    def __init__(self, master: tk.Misc, export_bar: ExportBar) -> None:
        super().__init__(master, padding=10)
        self._export_bar = export_bar
        self._timeline = Timeline()
        self._muted = tk.BooleanVar(value=False)
        self._frame_size = tk.StringVar(value=next(iter(_FRAME_SIZES)))
        self._position = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._preview = FramePreview(self)
        self._preview.grid(row=0, column=0, sticky="nsew")

        side = ttk.Frame(self)
        side.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self._inspector = ClipInspector(side, self._timeline, on_change=self._after_edit)
        self._inspector.pack(fill="x")
        export = ttk.LabelFrame(side, text="Export")
        export.pack(fill="x", pady=(10, 0))
        ttk.Label(export, text="Frame size").pack(anchor="w", padx=8, pady=(6, 0))
        self._frame_size_list = ttk.Combobox(
            export, state="readonly", values=list(_FRAME_SIZES), textvariable=self._frame_size, width=30
        )
        self._frame_size_list.pack(fill="x", padx=8, pady=(2, 8))
        self._preview_button = ttk.Button(export, text="Quick Preview", command=lambda: self._encode(draft=True))
        self._preview_button.pack(fill="x", padx=8)
        self._export_button = ttk.Button(export, text="Export MP4", command=lambda: self._encode(draft=False))
        self._export_button.pack(fill="x", padx=8, pady=(6, 8))
        ttk.Label(
            side,
            justify="left",
            foreground="#555555",
            text=(
                "Drag a clip to reorder it; drag its ends to trim.\n"
                "Click the timeline to move the playhead.\n"
                "S split   Del remove   Ctrl+Z / Ctrl+Y undo, redo\n"
                "Left / Right step one frame (Shift: one second)\n"
                "Ctrl+wheel zooms the timeline"
            ),
        ).pack(anchor="w", pady=(10, 0))

        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 6))
        self._buttons: dict[str, ttk.Button] = {}
        for name, command, gap in (
            ("Add Clips", self._add_clips, 0),
            ("Add Audio", self._add_audio, 6),
            ("Split", self._split, 18),
            ("Delete", self._delete, 6),
            ("Undo", self._undo, 18),
            ("Redo", self._redo, 6),
            ("Zoom -", lambda: self._view.zoom(0.8), 18),
            ("Zoom +", lambda: self._view.zoom(1.25), 6),
            ("Fit", lambda: self._view.zoom_to_fit(), 6),
        ):
            self._buttons[name] = ttk.Button(toolbar, text=name, command=command)
            self._buttons[name].pack(side="left", padx=(gap, 0))
        ttk.Checkbutton(
            toolbar, text="Mute the clips' own audio", variable=self._muted, command=self._toggle_mute
        ).pack(side="left", padx=(18, 0))
        ttk.Label(toolbar, textvariable=self._position, font=("Consolas", 11)).pack(side="right")

        self._view = TimelineView(self, self._timeline, on_change=self._sync)
        self._view.grid(row=2, column=0, columnspan=2, sticky="ew")

        for key, action in (
            ("<Delete>", self._delete),
            ("<BackSpace>", self._delete),
            ("<s>", self._split),
            ("<S>", self._split),
            ("<Control-z>", self._undo),
            ("<Control-y>", self._redo),
            ("<Control-Z>", self._redo),
            ("<Left>", lambda: self._step(-1, "frame")),
            ("<Right>", lambda: self._step(+1, "frame")),
            ("<Shift-Left>", lambda: self._step(-1, "second")),
            ("<Shift-Right>", lambda: self._step(+1, "second")),
            ("<Home>", lambda: self._view.set_playhead(0.0) or self._sync()),
            ("<End>", lambda: self._view.set_playhead(self._timeline.duration) or self._sync()),
        ):
            self.bind_all(key, lambda event, action=action: self._handle_key(event, action), add="+")
        export_bar.when_busy_changes(self._sync)
        self._sync()

    # --- keeping the panels in step with the timeline -------------------------

    def _sync(self) -> None:
        """Update everything outside the timeline view from the timeline, the selection and the playhead."""
        timeline, view = self._timeline, self._view
        self._inspector.show(view.selected)
        self._preview.show(timeline.frame_at(view.playhead))
        self._position.set(
            f"{format_timecode(round(view.playhead, 2))} / {format_timecode(round(timeline.duration, 2))}"
        )
        self._muted.set(timeline.video_muted)
        if timeline.video:
            width, height = frame_size(timeline)
            sizes = [f"Same as first clip ({width} x {height})", *list(_FRAME_SIZES)[1:]]
        else:
            sizes = list(_FRAME_SIZES)
        self._frame_size_list.configure(values=sizes)
        if self._frame_size_list.current() <= 0:
            self._frame_size_list.current(0)

        can_encode = bool(timeline.video) and not self._export_bar.busy
        enabled = {
            "Split": bool(timeline.video or timeline.audio),
            "Delete": view.selected is not None,
            "Add Audio": True,
        }
        for name, button in self._buttons.items():
            button.state(["!disabled"] if enabled.get(name, True) else ["disabled"])
        for button in (self._preview_button, self._export_button):
            button.state(["!disabled"] if can_encode else ["disabled"])

    def _after_edit(self) -> None:
        self._view.refresh()
        self._sync()

    def _handle_key(self, event: tk.Event, action: Callable[[], object]) -> None:
        # Shortcuts belong to this tab, and must not fire while the user is typing in a field.
        typing = getattr(event.widget, "winfo_class", str)() in _TYPING_WIDGETS
        ctrl_with_plain_key = event.keysym in ("s", "S") and event.state & 0x4  # Tk matches <s> for Ctrl+S too.
        if self.winfo_ismapped() and not typing and not ctrl_with_plain_key:
            action()

    # --- actions ----------------------------------------------------------

    def _add_clips(self) -> None:
        added = pick_media(self, "Add clips to the timeline")
        if not added:
            return
        was_empty = not self._timeline.video
        self._timeline.checkpoint()
        clips = [self._timeline.add_video(media) for media in added]
        self._view.select(clips[-1])
        if was_empty:
            self._view.zoom_to_fit()
        self._after_edit()
        self._export_bar.set_status(f"Added {len(clips)} clip(s) to the end of the timeline.")

    def _add_audio(self) -> None:
        added = pick_media(self, "Add audio (a video's sound or an audio file)", need="audio")
        if not added:
            return
        timeline = self._timeline
        timeline.checkpoint()
        note = ""
        if not timeline.audio and not timeline.video_muted and any(c.media.has_audio for c in timeline.video):
            # The usual reason to add audio is to replace the clips' own sound.
            timeline.video_muted = True
            note = " The clips' own audio was muted; untick the box to hear both."
        start = self._view.playhead
        for media in added:
            clip = timeline.add_audio(media, start)
            start = clip.end_sec
        self._view.select(clip)
        self._after_edit()
        self._export_bar.set_status(f"Audio added at {format_timecode(round(self._view.playhead, 2))}.{note}")

    def _split(self) -> None:
        timeline, playhead = self._timeline, self._view.playhead
        selected = self._view.selected
        # Prefer the selected clip when the playhead is inside it; otherwise cut the picture.
        target = (
            selected
            if selected is not None and selected.start_sec < playhead < selected.end_sec
            else timeline.video_at(playhead)
        )
        timeline.checkpoint()
        second_half = timeline.split(target, playhead) if target is not None else None
        if second_half is None:
            self._export_bar.set_status("To split, put the playhead inside a clip (not at its very edge).")
            return
        self._view.select(second_half)
        self._after_edit()
        self._export_bar.set_status(f"Split {target.media.name} at {format_timecode(round(playhead, 2))}.")

    def _delete(self) -> None:
        clip = self._view.selected
        if clip is None:
            return
        self._timeline.checkpoint()
        self._timeline.remove(clip)
        self._after_edit()
        self._export_bar.set_status(f"Removed {clip.media.name}.")

    def _undo(self) -> None:
        self._export_bar.set_status("Undone." if self._timeline.undo() else "Nothing to undo.")
        self._after_edit()

    def _redo(self) -> None:
        self._export_bar.set_status("Redone." if self._timeline.redo() else "Nothing to redo.")
        self._after_edit()

    def _toggle_mute(self) -> None:
        self._timeline.checkpoint()
        self._timeline.video_muted = self._muted.get()
        self._after_edit()

    def _step(self, direction: int, unit: str) -> None:
        fps = self._timeline.video[0].media.fps if self._timeline.video else 30.0
        self._view.set_playhead(self._view.playhead + direction * (1.0 if unit == "second" else 1.0 / fps))
        self._sync()

    def _encode(self, draft: bool) -> None:
        timeline = self._timeline
        size = list(_FRAME_SIZES.values())[max(0, self._frame_size_list.current())]
        try:
            args = compose(timeline, size, draft=draft)
        except ValueError as exc:
            messagebox.showinfo("Export", str(exc))
            return
        if draft:
            self._export_bar.preview(args, timeline.duration)
        else:
            first = Path(timeline.video[0].media.path)
            self._export_bar.export(args, timeline.duration, first.with_name(f"{first.stem}_edit.mp4"))
