"""The panel that shows and edits whichever layer of the combiner is selected."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from video_combiner.combiner.project import AUDIO_MIX, CombinerProject, Selection
from video_combiner.timecode import format_duration, format_timecode, parse_timecode

_OnChange = Callable[[str], None]


class Inspector(ttk.LabelFrame):
    """Edits the selected video, tile or text layer in place.

    After each edit that changed the project, ``on_change(message)`` is called
    with a short note for the status line. Input that cannot be understood is
    left in the field and changes nothing.
    """

    def __init__(self, master: tk.Misc, project: CombinerProject, on_change: _OnChange) -> None:
        super().__init__(master, text="Inspector")
        self.columnconfigure(0, weight=1)
        self._editors = {
            "video": _VideoEditor(self, project, on_change),
            "tile": _TileEditor(self, project, on_change),
            "text": _TextEditor(self, project, on_change),
        }
        self._nothing = ttk.Label(self, text="Select a video, tile or text layer to edit it.")
        self._shown: tk.Widget | None = None

    def show(self, selection: Selection) -> None:
        """Display the editor for ``selection``, filled in from the project."""
        if selection is None:
            editor: tk.Widget = self._nothing
        else:
            kind, index = selection
            editor = self._editors[kind]
            editor.load(index)
        if editor is not self._shown:
            if self._shown is not None:
                self._shown.grid_remove()
            editor.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 8))
            self._shown = editor

    def focus_text(self) -> None:
        """Put the cursor in the text field with its content selected, ready to be typed over."""
        self._editors["text"].focus_text()


class _Editor(ttk.Frame):
    """Shared plumbing of the three editors.

    Subclasses fill their fields in ``_fill`` and register every widget
    callback through ``_when_edited``, which drops the callbacks Tk fires at
    the wrong moment: while the fields are being filled in, and focus-out
    events that arrive after the editor has been swapped out.
    """

    def __init__(self, master: tk.Misc, project: CombinerProject, on_change: _OnChange) -> None:
        super().__init__(master)
        self._project = project
        self._on_change = on_change
        self._index = 0
        self._loading = False

    def load(self, index: int) -> None:
        """Show layer ``index`` of this editor's kind."""
        self._index = index
        self._loading = True
        try:
            self._fill()
        finally:
            self._loading = False

    def _fill(self) -> None:
        raise NotImplementedError

    def _when_edited(self, commit: Callable[[], None]) -> Callable[..., None]:
        def guarded(*_tk_arguments: object) -> None:
            if not self._loading and self.winfo_ismapped():
                commit()

        return guarded

    def _entry(self, master: tk.Misc, variable: tk.Variable, commit: Callable[[], None], width: int = 10) -> ttk.Entry:
        """An entry that commits on Return and when focus leaves it."""
        entry = ttk.Entry(master, textvariable=variable, width=width)
        entry.bind("<Return>", self._when_edited(commit))
        entry.bind("<FocusOut>", self._when_edited(commit))
        return entry


class _VideoEditor(_Editor):
    def __init__(self, master: tk.Misc, project: CombinerProject, on_change: _OnChange) -> None:
        super().__init__(master, project, on_change)
        self.columnconfigure(0, weight=1)
        self._facts = {
            name: tk.StringVar() for name in ("Video", "Tile", "Tile Corner", "Duration", "FPS", "Audio", "File")
        }
        self._x, self._y = tk.StringVar(), tk.StringVar()
        self._trim_start, self._trim_end, self._start_at = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._in_mix = tk.BooleanVar()

        facts = ttk.Frame(self)
        facts.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        facts.columnconfigure(1, weight=1)
        for row, (name, variable) in enumerate(self._facts.items()):
            ttk.Label(facts, text=f"{name}:").grid(row=row, column=0, sticky="nw", padx=(0, 6), pady=1)
            ttk.Label(facts, textvariable=variable, wraplength=300).grid(row=row, column=1, sticky="nw", pady=1)

        placing = ttk.LabelFrame(self, text="Position / Timing (Output Coordinates)")
        placing.grid(row=1, column=0, sticky="ew", pady=4)
        ttk.Label(placing, text="X").grid(row=0, column=0, padx=(8, 4), pady=6)
        self._entry(placing, self._x, self._commit_position).grid(row=0, column=1, pady=6)
        ttk.Label(placing, text="Y").grid(row=0, column=2, padx=(12, 4), pady=6)
        self._entry(placing, self._y, self._commit_position).grid(row=0, column=3, pady=6)
        ttk.Button(placing, text="Reset To Tile", command=self._when_edited(self._reset_position)).grid(
            row=0, column=4, padx=(12, 8), pady=6
        )
        ttk.Label(placing, text="Trim From (HH:MM:SS)").grid(row=1, column=0, padx=(8, 4), pady=2, sticky="w")
        self._entry(placing, self._trim_start, self._commit_timing, width=12).grid(row=1, column=1, pady=2, sticky="w")
        ttk.Label(placing, text="Trim To (HH:MM:SS)").grid(row=1, column=2, padx=(12, 4), pady=2, sticky="w")
        self._entry(placing, self._trim_end, self._commit_timing, width=12).grid(row=1, column=3, pady=2, sticky="w")
        ttk.Label(placing, text="Start At (HH:MM:SS)").grid(row=2, column=0, padx=(8, 4), pady=(2, 6), sticky="w")
        self._entry(placing, self._start_at, self._commit_timing, width=12).grid(
            row=2, column=1, pady=(2, 6), sticky="w"
        )
        ttk.Button(placing, text="Apply", command=self._when_edited(self._commit_timing)).grid(
            row=2, column=2, columnspan=3, padx=(12, 8), pady=(2, 6), sticky="w"
        )

        audio = ttk.LabelFrame(self, text="Audio")
        audio.grid(row=2, column=0, sticky="ew", pady=4)
        self._in_mix_check = ttk.Checkbutton(
            audio,
            text='Include this video in "Mix all"',
            variable=self._in_mix,
            command=self._when_edited(self._commit_in_mix),
        )
        self._in_mix_check.grid(row=0, column=0, sticky="w", padx=8, pady=6)

    def _fill(self) -> None:
        project, video = self._project, self._project.videos[self._index]
        slot = project.slots()[self._index] if self._index < len(project.tiles) else None
        self._facts["Video"].set(f"{self._index + 1} of {len(project.videos)}")
        self._facts["Tile"].set(slot.tile.name if slot else "None (more videos than tiles; not rendered)")
        self._facts["Tile Corner"].set(f"({slot.tile.x}, {slot.tile.y})" if slot else "-")
        self._facts["Duration"].set(format_duration(video.media.duration))
        self._facts["FPS"].set(f"{video.media.fps:.3f}".rstrip("0").rstrip("."))
        self._facts["Audio"].set("Yes" if video.media.has_audio else "No")
        self._facts["File"].set(video.media.name)
        x, y = self._shown_position()
        self._x.set(str(x))
        self._y.set(str(y))
        self._trim_start.set(format_timecode(video.trim_start_sec))
        self._trim_end.set(format_timecode(video.trim_end_sec))
        self._start_at.set(format_timecode(video.start_at_sec))
        self._in_mix.set(video.include_in_mix)
        self._in_mix_check.state(["!disabled"] if project.audio == AUDIO_MIX else ["disabled"])

    def _shown_position(self) -> tuple[int, int]:
        """Where the video sits now: its own position, else its tile's corner, else the origin."""
        video = self._project.videos[self._index]
        if video.position is not None:
            return video.position
        if self._index < len(self._project.tiles):
            tile = self._project.tiles[self._index]
            return tile.x, tile.y
        return 0, 0

    def _commit_position(self) -> None:
        try:
            position = (int(self._x.get().strip()), int(self._y.get().strip()))
        except ValueError:
            return
        # Merely tabbing through the fields must not detach the video from its tile.
        if position != self._shown_position():
            self._project.videos[self._index].position = position
            self._on_change("Video position updated.")

    def _reset_position(self) -> None:
        self._project.videos[self._index].position = None
        self._on_change("Video position reset to its tile.")

    def _commit_timing(self) -> None:
        video = self._project.videos[self._index]
        trim_start = parse_timecode(self._trim_start.get(), limit=video.media.duration)
        trim_end = parse_timecode(self._trim_end.get(), limit=video.media.duration)
        start_at = parse_timecode(self._start_at.get())
        if trim_start is None or start_at is None or (trim_end is None and self._trim_end.get().strip()):
            return
        timing = (trim_start, trim_end, start_at)
        if timing != (video.trim_start_sec, video.trim_end_sec, video.start_at_sec):
            video.trim_start_sec, video.trim_end_sec, video.start_at_sec = timing
            self._on_change("Video timing updated.")

    def _commit_in_mix(self) -> None:
        self._project.videos[self._index].include_in_mix = self._in_mix.get()
        self._on_change("Audio mix updated.")


class _TileEditor(_Editor):
    def __init__(self, master: tk.Misc, project: CombinerProject, on_change: _OnChange) -> None:
        super().__init__(master, project, on_change)
        self.columnconfigure(3, weight=1)
        self._x, self._y, self._tile_w, self._tile_h = (tk.StringVar() for _ in range(4))
        self._tile_name = tk.StringVar()
        self._video = tk.StringVar()

        for label, variable, row, column in (
            ("X", self._x, 0, 0),
            ("Y", self._y, 0, 2),
            ("W", self._tile_w, 1, 0),
            ("H", self._tile_h, 1, 2),
        ):
            ttk.Label(self, text=label).grid(row=row, column=column, padx=(12 if column else 0, 4), pady=2, sticky="w")
            self._entry(self, variable, self._commit).grid(row=row, column=column + 1, pady=2, sticky="w")
        ttk.Label(self, text="Name").grid(row=2, column=0, padx=(0, 4), pady=(4, 2), sticky="w")
        self._entry(self, self._tile_name, self._commit).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(4, 2))
        ttk.Label(self, text="Video").grid(row=3, column=0, padx=(0, 4), pady=2, sticky="w")
        ttk.Label(self, textvariable=self._video).grid(row=3, column=1, columnspan=3, sticky="w", pady=2)
        ttk.Button(self, text="Apply Tile", command=self._when_edited(self._commit)).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Label(self, text="Add, remove and reorder tiles in the Tiles tab.").grid(
            row=4, column=2, columnspan=2, sticky="w", padx=8, pady=(4, 0)
        )

    def _fill(self) -> None:
        tile = self._project.tiles[self._index]
        for variable, value in ((self._x, tile.x), (self._y, tile.y), (self._tile_w, tile.w), (self._tile_h, tile.h)):
            variable.set(str(value))
        self._tile_name.set(tile.name)
        videos = self._project.videos
        self._video.set(videos[self._index].media.name if self._index < len(videos) else "None")

    def _commit(self) -> None:
        try:
            x, y, w, h = (int(variable.get().strip()) for variable in (self._x, self._y, self._tile_w, self._tile_h))
        except ValueError:
            return
        tile = self._project.tiles[self._index]
        edited = (x, y, max(1, w), max(1, h), self._tile_name.get().strip() or f"Tile {self._index + 1}")
        if edited != (tile.x, tile.y, tile.w, tile.h, tile.name):
            tile.x, tile.y, tile.w, tile.h, tile.name = edited
            self._on_change(f"{tile.name} updated.")


class _TextEditor(_Editor):
    def __init__(self, master: tk.Misc, project: CombinerProject, on_change: _OnChange) -> None:
        super().__init__(master, project, on_change)
        self.columnconfigure(1, weight=1)
        self._enabled = tk.BooleanVar()
        self._text = tk.StringVar()
        self._x, self._y, self._size, self._color = (tk.StringVar() for _ in range(4))
        self._start_at, self._duration = tk.StringVar(), tk.StringVar()
        self._rgb = [tk.IntVar(value=255) for _ in "RGB"]

        ttk.Checkbutton(
            self, text="Enable text overlay", variable=self._enabled, command=self._when_edited(self._commit)
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        ttk.Label(self, text="Text").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        self._text_entry = self._entry(self, self._text, self._commit)
        self._text_entry.grid(row=1, column=1, columnspan=3, sticky="ew", pady=2)
        self._text.trace_add("write", self._when_edited(self._commit))  # The preview follows typing.
        ttk.Label(self, text="X").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        self._entry(self, self._x, self._commit).grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(self, text="Y").grid(row=2, column=2, sticky="w", padx=(8, 6), pady=2)
        self._entry(self, self._y, self._commit).grid(row=2, column=3, sticky="w", pady=2)
        ttk.Label(self, text="Size").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        self._entry(self, self._size, self._commit).grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(self, text="Color").grid(row=3, column=2, sticky="w", padx=(8, 6), pady=2)
        self._entry(self, self._color, self._commit_typed_color, width=12).grid(row=3, column=3, sticky="w", pady=2)
        for row, (channel, variable) in enumerate(zip("RGB", self._rgb), start=4):
            ttk.Label(self, text=channel).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Scale(
                self,
                from_=0,
                to=255,
                orient="horizontal",
                variable=variable,
                command=self._when_edited(self._commit_slider_color),
            ).grid(row=row, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Label(self, text="Start At (HH:MM:SS)").grid(row=7, column=0, sticky="w", padx=(0, 6), pady=2)
        self._entry(self, self._start_at, self._commit, width=12).grid(row=7, column=1, sticky="w", pady=2)
        ttk.Label(self, text="Duration (HH:MM:SS)").grid(row=7, column=2, sticky="w", padx=(8, 6), pady=2)
        self._entry(self, self._duration, self._commit, width=12).grid(row=7, column=3, sticky="w", pady=2)
        ttk.Button(self, text="Apply", command=self._when_edited(self._commit)).grid(
            row=8, column=0, columnspan=4, sticky="w", pady=(2, 0)
        )

    def focus_text(self) -> None:
        self._text_entry.focus_set()
        self._text_entry.selection_range(0, tk.END)
        self._text_entry.icursor(tk.END)

    def _fill(self) -> None:
        text = self._project.texts[self._index]
        self._enabled.set(text.enabled)
        self._text.set(text.text)
        self._x.set(str(text.x))
        self._y.set(str(text.y))
        self._size.set(str(text.size))
        self._color.set(text.color)
        self._show_color_on_sliders()
        self._start_at.set(format_timecode(text.start_at_sec))
        self._duration.set(format_timecode(text.duration_sec))

    def _commit(self) -> None:
        start_at = parse_timecode(self._start_at.get())
        duration = parse_timecode(self._duration.get())
        if start_at is None or (duration is None and self._duration.get().strip()):
            return
        try:
            x, y = int(self._x.get().strip() or "0"), int(self._y.get().strip() or "0")
            size = max(1, int(self._size.get().strip() or "1"))
        except ValueError:
            return
        text = self._project.texts[self._index]
        color = self._color.get().strip() or "white"
        edited = (self._enabled.get(), self._text.get(), x, y, size, color, start_at, duration)
        current = (text.enabled, text.text, text.x, text.y, text.size, text.color, text.start_at_sec, text.duration_sec)
        if edited != current:
            (text.enabled, text.text, text.x, text.y, text.size, text.color, text.start_at_sec, text.duration_sec) = (
                edited
            )
            self._on_change("Text layer updated.")

    def _commit_typed_color(self) -> None:
        self._show_color_on_sliders()
        self._commit()

    def _commit_slider_color(self) -> None:
        red, green, blue = (max(0, min(255, round(float(variable.get())))) for variable in self._rgb)
        self._color.set(f"#{red:02x}{green:02x}{blue:02x}")
        self._commit()

    def _show_color_on_sliders(self) -> None:
        """Move the RGB sliders to the colour in the Color field, if Tk can interpret it."""
        try:
            channels = self.winfo_rgb(self._color.get().strip())
        except tk.TclError:
            return
        was_loading, self._loading = self._loading, True  # Moving a slider must not write the colour back.
        try:
            for variable, value in zip(self._rgb, channels):
                variable.set(round(value / 257))
        finally:
            self._loading = was_loading
