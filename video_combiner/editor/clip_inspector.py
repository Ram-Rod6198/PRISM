"""The panel for exact edits to the selected timeline clip."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from video_combiner.editor.timeline import Clip, Timeline
from video_combiner.timecode import format_timecode, parse_timecode


class ClipInspector(ttk.LabelFrame):
    """Shows the selected clip and lets its trim, position and volume be typed exactly.

    Edits go through the timeline (each an undo step) and are followed by
    ``on_change()``. Text that is not a time is ignored.
    """

    def __init__(self, master: tk.Misc, timeline: Timeline, on_change: Callable[[], None]) -> None:
        super().__init__(master, text="Selected Clip")
        self._timeline = timeline
        self._on_change = on_change
        self._clip: Clip | None = None
        self._loading = False
        self._title = tk.StringVar()
        self._source = tk.StringVar()
        self._in, self._out, self._start = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._length = tk.StringVar()
        self._volume = tk.DoubleVar(value=100.0)
        self._volume_text = tk.StringVar()

        self.columnconfigure(1, weight=1)
        ttk.Label(self, textvariable=self._title, wraplength=280, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 0)
        )
        ttk.Label(self, textvariable=self._source, wraplength=280).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6)
        )
        self._entries = []
        for row, (label, variable) in enumerate(
            (("Trim from", self._in), ("Trim to", self._out), ("Starts at", self._start)), start=2
        ):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=(8, 6), pady=2)
            entry = ttk.Entry(self, textvariable=variable, width=14)
            entry.grid(row=row, column=1, sticky="w", pady=2)
            entry.bind("<Return>", lambda _e: self._commit_times())
            entry.bind("<FocusOut>", lambda _e: self._commit_times())
            self._entries.append(entry)
        ttk.Label(self, text="Length").grid(row=5, column=0, sticky="w", padx=(8, 6), pady=2)
        ttk.Label(self, textvariable=self._length).grid(row=5, column=1, sticky="w", pady=2)
        ttk.Label(self, text="Volume").grid(row=6, column=0, sticky="w", padx=(8, 6), pady=(2, 8))
        self._volume_scale = ttk.Scale(self, from_=0, to=200, variable=self._volume, command=self._commit_volume)
        self._volume_scale.grid(row=6, column=1, sticky="ew", pady=(2, 8))
        self._volume_scale.bind("<ButtonPress-1>", lambda _e: self._timeline.checkpoint(), add="+")
        ttk.Label(self, textvariable=self._volume_text, width=5).grid(row=6, column=2, padx=(6, 8), pady=(2, 8))
        self.show(None)

    def show(self, clip: Clip | None) -> None:
        """Display ``clip`` (None: nothing selected) as it is now."""
        self._clip = clip
        self._loading = True
        try:
            for widget in (*self._entries, self._volume_scale):
                widget.state(["disabled"] if clip is None else ["!disabled"])
            if clip is None:
                self._title.set("Nothing selected")
                self._source.set("Click a clip on the timeline.")
                for variable in (self._in, self._out, self._start, self._length, self._volume_text):
                    variable.set("")
                return
            is_audio = self._timeline.is_audio(clip)
            self._title.set(clip.media.name)
            self._source.set(f"{'Audio' if is_audio else 'Video'} clip from a {_shown(clip.media.duration)} file")
            self._in.set(_shown(clip.in_sec))
            self._out.set(_shown(clip.out_sec))
            self._start.set(_shown(clip.start_sec))
            # Video clips follow one another; only audio clips can be placed.
            self._entries[2].state(["!disabled"] if is_audio else ["disabled"])
            self._length.set(_shown(clip.duration))
            self._volume.set(clip.volume * 100)
            self._volume_text.set(f"{clip.volume:.0%}")
        finally:
            self._loading = False

    def _commit_times(self) -> None:
        clip = self._clip
        if self._loading or clip is None:
            return
        timeline = self._timeline
        before = (clip.in_sec, clip.out_sec, clip.start_sec)
        timeline.checkpoint()
        # Only fields the user actually retyped are applied, so rounding in the display never nudges a clip.
        if self._start.get() != _shown(clip.start_sec) and timeline.is_audio(clip):
            typed = parse_timecode(self._start.get())
            if typed is not None:
                timeline.slide(clip, typed)
        if self._in.get() != _shown(clip.in_sec):
            typed = parse_timecode(self._in.get(), limit=clip.media.duration)
            if typed is not None:
                timeline.trim(clip, in_sec=typed)
        if self._out.get() != _shown(clip.out_sec):
            typed = parse_timecode(self._out.get(), limit=clip.media.duration)
            if typed is not None:
                timeline.trim(clip, out_sec=typed)
        if before != (clip.in_sec, clip.out_sec, clip.start_sec):
            self._on_change()

    def _commit_volume(self, _value: str) -> None:
        if self._loading or self._clip is None:
            return
        self._timeline.set_volume(self._clip, round(self._volume.get()) / 100)
        self._volume_text.set(f"{self._clip.volume:.0%}")
        self._on_change()


def _shown(seconds: float) -> str:
    """A time as displayed in this panel: a timecode to the millisecond."""
    return format_timecode(round(seconds, 3))
