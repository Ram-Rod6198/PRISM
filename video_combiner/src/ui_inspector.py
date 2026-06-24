from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from video_combiner.src.model import TextOverlaySettings, VideoItem
from video_combiner.src.utils import format_duration, format_timecode, parse_timecode, short_name


class InspectorPanel(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_position_change: Callable[[int, int], None] | None = None,
        on_reset_position: Callable[[], None] | None = None,
        on_include_in_mix_change: Callable[[bool], None] | None = None,
        on_z_level_change: Callable[[int], None] | None = None,
        on_video_timing_change: Callable[[str, str, str], None] | None = None,
        on_text_overlay_change: Callable[[TextOverlaySettings], None] | None = None,
        on_tile_layout_change: Callable[[int, int, int, int, str], None] | None = None,
    ) -> None:
        super().__init__(master, text="Inspector")
        self._on_position_change = on_position_change
        self._on_reset_position = on_reset_position
        self._on_include_in_mix_change = on_include_in_mix_change
        self._on_z_level_change = on_z_level_change
        self._on_video_timing_change = on_video_timing_change
        self._on_text_overlay_change = on_text_overlay_change
        self._on_tile_layout_change = on_tile_layout_change
        self._suspend_events = False

        self.vars = {
            "selection": tk.StringVar(value="None"),
            "tile": tk.StringVar(value="-"),
            "z_level": tk.StringVar(value="-"),
            "default_coords": tk.StringVar(value="-"),
            "duration": tk.StringVar(value="-"),
            "fps": tk.StringVar(value="-"),
            "audio": tk.StringVar(value="-"),
            "path": tk.StringVar(value="-"),
            "pos_x": tk.StringVar(value="0"),
            "pos_y": tk.StringVar(value="0"),
            "include_in_mix": tk.BooleanVar(value=True),
            "z_input": tk.StringVar(value="1"),
            "trim_start": tk.StringVar(value="00:00:00"),
            "trim_end": tk.StringVar(value=""),
            "video_start_at": tk.StringVar(value="00:00:00"),
            "text_enabled": tk.BooleanVar(value=False),
            "text": tk.StringVar(value=""),
            "text_x": tk.StringVar(value="40"),
            "text_y": tk.StringVar(value="40"),
            "text_size": tk.StringVar(value="72"),
            "text_color": tk.StringVar(value="white"),
            "text_r": tk.IntVar(value=255),
            "text_g": tk.IntVar(value=255),
            "text_b": tk.IntVar(value=255),
            "text_start_at": tk.StringVar(value="00:00:00"),
            "text_duration": tk.StringVar(value=""),
            "tile_x": tk.StringVar(value="0"),
            "tile_y": tk.StringVar(value="0"),
            "tile_w": tk.StringVar(value="1920"),
            "tile_h": tk.StringVar(value="1080"),
            "tile_name": tk.StringVar(value="Tile 1"),
            "tile_z": tk.StringVar(value="1"),
            "preset_name": tk.StringVar(value="My Preset"),
        }

        self._selected_list_index: int | None = None
        self._selected_text_index: int | None = None
        self._selected_item_mapped = False
        self._selected_tile_index: int | None = None
        self.info_frame: ttk.Frame
        self.pos_frame: ttk.LabelFrame
        self.audio_frame: ttk.LabelFrame
        self.text_frame: ttk.LabelFrame
        self.tile_frame: ttk.LabelFrame
        self._build()
        self._bind_traces()
        self._set_inspector_mode("none")

    def _build(self) -> None:
        self.info_frame = ttk.Frame(self)
        self.info_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        self.info_frame.columnconfigure(1, weight=1)
        rows = [
            ("Selection", "selection"),
            ("Tile", "tile"),
            ("Default Coords", "default_coords"),
            ("Duration", "duration"),
            ("FPS", "fps"),
            ("Audio Stream", "audio"),
            ("Path", "path"),
        ]
        for row, (label, key) in enumerate(rows):
            ttk.Label(self.info_frame, text=f"{label}:").grid(
                row=row, column=0, sticky="nw", padx=(0, 6), pady=1
            )
            ttk.Label(self.info_frame, textvariable=self.vars[key], wraplength=300).grid(
                row=row, column=1, sticky="nw", pady=1
            )

        self.pos_frame = ttk.LabelFrame(self, text="Tile Position / Layer (Output Coordinates)")
        self.pos_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        ttk.Label(self.pos_frame, text="X").grid(row=0, column=0, padx=(8, 4), pady=6)
        self.pos_x_entry = ttk.Entry(self.pos_frame, textvariable=self.vars["pos_x"], width=10)
        self.pos_x_entry.grid(row=0, column=1, pady=6)
        ttk.Label(self.pos_frame, text="Y").grid(row=0, column=2, padx=(12, 4), pady=6)
        self.pos_y_entry = ttk.Entry(self.pos_frame, textvariable=self.vars["pos_y"], width=10)
        self.pos_y_entry.grid(row=0, column=3, pady=6)
        self.reset_pos_btn = ttk.Button(self.pos_frame, text="Reset To Tile", command=self._handle_reset_position)
        self.reset_pos_btn.grid(row=0, column=4, padx=(12, 8), pady=6)
        ttk.Label(self.pos_frame, text="Updates preview and render placement.").grid(
            row=1, column=0, columnspan=5, sticky="w", padx=8, pady=(0, 6)
        )
        ttk.Label(self.pos_frame, text="Trim From (HH:MM:SS)").grid(row=2, column=0, padx=(8, 4), pady=2, sticky="w")
        self.trim_start_entry = ttk.Entry(self.pos_frame, textvariable=self.vars["trim_start"], width=12)
        self.trim_start_entry.grid(row=2, column=1, pady=2, sticky="w")
        ttk.Label(self.pos_frame, text="Trim To (HH:MM:SS)").grid(row=2, column=2, padx=(12, 4), pady=2, sticky="w")
        self.trim_end_entry = ttk.Entry(self.pos_frame, textvariable=self.vars["trim_end"], width=12)
        self.trim_end_entry.grid(row=2, column=3, pady=2, sticky="w")
        ttk.Label(self.pos_frame, text="Start At (HH:MM:SS)").grid(row=3, column=0, padx=(8, 4), pady=2, sticky="w")
        self.video_start_at_entry = ttk.Entry(self.pos_frame, textvariable=self.vars["video_start_at"], width=12)
        self.video_start_at_entry.grid(row=3, column=1, pady=2, sticky="w")
        ttk.Button(self.pos_frame, text="Apply", command=self._emit_video_timing_change).grid(
            row=3, column=2, columnspan=3, padx=(12, 8), pady=2, sticky="w"
        )

        self.audio_frame = ttk.LabelFrame(self, text="Per-Item Audio")
        self.audio_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self.include_mix_check = ttk.Checkbutton(
            self.audio_frame,
            text="Include this item in Mix all",
            variable=self.vars["include_in_mix"],
            command=self._emit_include_in_mix_change,
        )
        self.include_mix_check.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
        ttk.Label(self.audio_frame, text="Global Audio Mode dropdown takes precedence over this setting.").grid(
            row=1, column=0, sticky="w", padx=8, pady=(0, 6)
        )

        self.text_frame = ttk.LabelFrame(self, text="Text Layer (Selected)")
        self.text_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        self.text_frame.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            self.text_frame,
            text="Enable text overlay",
            variable=self.vars["text_enabled"],
            command=self._emit_text_overlay_change,
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(6, 4))
        ttk.Label(self.text_frame, text="Text").grid(row=1, column=0, sticky="w", padx=(8, 6), pady=2)
        self.text_entry = ttk.Entry(self.text_frame, textvariable=self.vars["text"])
        self.text_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=2)
        ttk.Label(self.text_frame, text="X").grid(row=2, column=0, sticky="w", padx=(8, 6), pady=2)
        self.text_x_entry = ttk.Entry(self.text_frame, textvariable=self.vars["text_x"], width=10)
        self.text_x_entry.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(self.text_frame, text="Y").grid(row=2, column=2, sticky="w", padx=(8, 6), pady=2)
        self.text_y_entry = ttk.Entry(self.text_frame, textvariable=self.vars["text_y"], width=10)
        self.text_y_entry.grid(row=2, column=3, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(self.text_frame, text="Size").grid(row=3, column=0, sticky="w", padx=(8, 6), pady=(2, 2))
        self.text_size_entry = ttk.Entry(self.text_frame, textvariable=self.vars["text_size"], width=10)
        self.text_size_entry.grid(row=3, column=1, sticky="w", pady=(2, 2))
        ttk.Label(self.text_frame, text="Color").grid(row=3, column=2, sticky="w", padx=(8, 6), pady=(2, 2))
        self.text_color_entry = ttk.Entry(self.text_frame, textvariable=self.vars["text_color"], width=12)
        self.text_color_entry.grid(row=3, column=3, sticky="w", padx=(0, 8), pady=(2, 2))
        ttk.Label(self.text_frame, text="R").grid(row=4, column=0, sticky="w", padx=(8, 6), pady=2)
        self.text_r_scale = ttk.Scale(
            self.text_frame,
            from_=0,
            to=255,
            orient="horizontal",
            variable=self.vars["text_r"],
            command=self._on_text_rgb_slider_change,
        )
        self.text_r_scale.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=2)
        ttk.Label(self.text_frame, text="G").grid(row=5, column=0, sticky="w", padx=(8, 6), pady=2)
        self.text_g_scale = ttk.Scale(
            self.text_frame,
            from_=0,
            to=255,
            orient="horizontal",
            variable=self.vars["text_g"],
            command=self._on_text_rgb_slider_change,
        )
        self.text_g_scale.grid(row=5, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=2)
        ttk.Label(self.text_frame, text="B").grid(row=6, column=0, sticky="w", padx=(8, 6), pady=2)
        self.text_b_scale = ttk.Scale(
            self.text_frame,
            from_=0,
            to=255,
            orient="horizontal",
            variable=self.vars["text_b"],
            command=self._on_text_rgb_slider_change,
        )
        self.text_b_scale.grid(row=6, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=2)
        ttk.Label(self.text_frame, text="Start At (HH:MM:SS)").grid(row=7, column=0, sticky="w", padx=(8, 6), pady=2)
        self.text_start_at_entry = ttk.Entry(self.text_frame, textvariable=self.vars["text_start_at"], width=12)
        self.text_start_at_entry.grid(row=7, column=1, sticky="w", pady=2)
        ttk.Label(self.text_frame, text="Duration (HH:MM:SS)").grid(row=7, column=2, sticky="w", padx=(8, 6), pady=2)
        self.text_duration_entry = ttk.Entry(self.text_frame, textvariable=self.vars["text_duration"], width=12)
        self.text_duration_entry.grid(row=7, column=3, sticky="w", padx=(0, 8), pady=2)
        ttk.Button(self.text_frame, text="Apply", command=self._emit_text_overlay_change).grid(
            row=8, column=0, columnspan=4, sticky="w", padx=(8, 8), pady=(2, 6)
        )

        self.tile_frame = ttk.LabelFrame(self, text="Tile Layout (Selected Tile)")
        self.tile_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        ttk.Label(self.tile_frame, text="X").grid(row=0, column=0, padx=(8, 4), pady=(6, 2), sticky="w")
        self.tile_x_entry = ttk.Entry(self.tile_frame, textvariable=self.vars["tile_x"], width=10)
        self.tile_x_entry.grid(row=0, column=1, pady=(6, 2), sticky="w")
        ttk.Label(self.tile_frame, text="Y").grid(row=0, column=2, padx=(12, 4), pady=(6, 2), sticky="w")
        self.tile_y_entry = ttk.Entry(self.tile_frame, textvariable=self.vars["tile_y"], width=10)
        self.tile_y_entry.grid(row=0, column=3, pady=(6, 2), sticky="w")
        ttk.Label(self.tile_frame, text="W").grid(row=1, column=0, padx=(8, 4), pady=2, sticky="w")
        self.tile_w_entry = ttk.Entry(self.tile_frame, textvariable=self.vars["tile_w"], width=10)
        self.tile_w_entry.grid(row=1, column=1, pady=2, sticky="w")
        ttk.Label(self.tile_frame, text="H").grid(row=1, column=2, padx=(12, 4), pady=2, sticky="w")
        self.tile_h_entry = ttk.Entry(self.tile_frame, textvariable=self.vars["tile_h"], width=10)
        self.tile_h_entry.grid(row=1, column=3, pady=2, sticky="w")
        ttk.Label(self.tile_frame, text="Name").grid(row=2, column=0, padx=(8, 4), pady=(4, 6), sticky="w")
        self.tile_name_entry = ttk.Entry(self.tile_frame, textvariable=self.vars["tile_name"])
        self.tile_name_entry.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=(4, 6))
        ttk.Button(self.tile_frame, text="Apply Tile", command=self._emit_tile_layout_change).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 6)
        )
        ttk.Label(self.tile_frame, text="Use Tiles tab buttons to remove/reorder tiles.").grid(
            row=3, column=2, columnspan=2, sticky="w", padx=8, pady=(4, 6)
        )
        self.tile_frame.columnconfigure(3, weight=1)

        for widget in (
            self.pos_x_entry,
            self.pos_y_entry,
            self.trim_start_entry,
            self.trim_end_entry,
            self.video_start_at_entry,
            self.text_entry,
            self.text_x_entry,
            self.text_y_entry,
            self.text_size_entry,
            self.text_color_entry,
            self.text_start_at_entry,
            self.text_duration_entry,
        ):
            widget.bind("<Return>", self._handle_entry_commit)
            widget.bind("<FocusOut>", self._handle_entry_commit)
        for widget in (self.tile_x_entry, self.tile_y_entry, self.tile_w_entry, self.tile_h_entry, self.tile_name_entry):
            widget.bind("<Return>", self._handle_tile_entry_commit)
            widget.bind("<FocusOut>", self._handle_tile_entry_commit)
        # z-order is controlled by list order (Videos/Tiles/Text lists), not the Inspector.

        self.columnconfigure(0, weight=1)

    def _bind_traces(self) -> None:
        # Text updates can be live-ish; avoid spamming while we are populating.
        self.vars["text"].trace_add("write", lambda *_: self._emit_text_overlay_change())

    def set_audio_mode_label(self, audio_mode_label: str) -> None:
        is_mix_all = audio_mode_label == "Mix all"
        self.include_mix_check.state(["!disabled"] if is_mix_all and self._selected_item_mapped else ["disabled"])

    def show_list_item(
        self,
        list_index: int,
        item: VideoItem,
        effective_coords: tuple[int, int] | None,
        default_coords: tuple[int, int] | None,
        z_label: str = "-",
    ) -> None:
        self._selected_list_index = list_index
        self._selected_text_index = None
        self._selected_tile_index = None
        self._selected_item_mapped = default_coords is not None
        self.vars["selection"].set(f"List item {list_index + 1}")

        if self._selected_item_mapped:
            self.vars["tile"].set(f"Tile {list_index + 1}")
            self.vars["z_level"].set(z_label)
            self.vars["default_coords"].set(str(default_coords))
            self._set_position_entries(effective_coords or default_coords or (0, 0))
        else:
            self.vars["tile"].set("Not mapped")
            self.vars["z_level"].set("Not rendered")
            self.vars["default_coords"].set("-")
            self._set_position_entries((0, 0))

        self.vars["duration"].set(format_duration(item.duration))
        self.vars["fps"].set(f"{item.fps:.3f}".rstrip("0").rstrip("."))
        self.vars["audio"].set("Yes" if item.has_audio else "No")
        self.vars["path"].set(short_name(item.path))
        self.vars["include_in_mix"].set(bool(item.include_in_mix))
        self.vars["trim_start"].set(format_timecode(item.trim_start_sec))
        self.vars["trim_end"].set(format_timecode(item.trim_end_sec) if item.trim_end_sec is not None else "")
        self.vars["video_start_at"].set(format_timecode(item.start_at_sec))
        self.vars["z_input"].set(str(item.layer_z))
        self._set_text_editor_enabled(False)
        self._set_inspector_mode("video")

    def show_tile(
        self,
        tile_index: int,
        item: VideoItem | None,
        effective_coords: tuple[int, int] | None,
        tile_rect: tuple[int, int, int, int] | None = None,
        z_label: str = "-",
    ) -> None:
        self._selected_list_index = tile_index - 1 if item is not None else None
        self._selected_text_index = None
        self._selected_tile_index = None
        self._selected_item_mapped = item is not None
        default_coords = (tile_rect[0], tile_rect[1]) if tile_rect is not None else (0, 0)
        self.vars["selection"].set(f"Tile {tile_index}")
        self.vars["tile"].set(f"Tile {tile_index}")
        self.vars["z_level"].set(z_label)
        self.vars["default_coords"].set(str(default_coords))
        self._set_position_entries(effective_coords or default_coords)
        if item is None:
            self.vars["duration"].set("Empty")
            self.vars["fps"].set("-")
            self.vars["audio"].set("-")
            self.vars["path"].set("Empty tile")
            self.vars["include_in_mix"].set(False)
            self.vars["trim_start"].set("00:00:00")
            self.vars["trim_end"].set("")
            self.vars["video_start_at"].set("00:00:00")
            self.vars["z_input"].set(str(tile_index))
            self._set_text_editor_enabled(False)
            self._set_inspector_mode("video")
            return
        self.vars["duration"].set(format_duration(item.duration))
        self.vars["fps"].set(f"{item.fps:.3f}".rstrip("0").rstrip("."))
        self.vars["audio"].set("Yes" if item.has_audio else "No")
        self.vars["path"].set(short_name(item.path))
        self.vars["include_in_mix"].set(bool(item.include_in_mix))
        self.vars["trim_start"].set(format_timecode(item.trim_start_sec))
        self.vars["trim_end"].set(format_timecode(item.trim_end_sec) if item.trim_end_sec is not None else "")
        self.vars["video_start_at"].set(format_timecode(item.start_at_sec))
        self.vars["z_input"].set(str(item.layer_z))
        self._set_text_editor_enabled(False)
        self._set_inspector_mode("video")

    def show_tile_layout(
        self,
        tile_index: int,
        tile_rect: tuple[int, int, int, int],
        assigned_item: VideoItem | None = None,
        preset_name: str = "",
        tile_z: int = 1,
        tile_name: str = "",
    ) -> None:
        self._selected_list_index = None
        self._selected_text_index = None
        self._selected_tile_index = tile_index
        self._selected_item_mapped = False
        x, y, w, h = tile_rect
        self.vars["selection"].set(f"Tile {tile_index}")
        self.vars["tile"].set(f"Tile {tile_index}")
        self.vars["default_coords"].set(f"({x}, {y})")
        self.vars["duration"].set("Tile layout editor")
        self.vars["fps"].set("-")
        self.vars["audio"].set("-")
        self.vars["path"].set(short_name(assigned_item.path) if assigned_item is not None else "No assigned video")
        self._suspend_events = True
        try:
            self.vars["tile_x"].set(str(x))
            self.vars["tile_y"].set(str(y))
            self.vars["tile_w"].set(str(w))
            self.vars["tile_h"].set(str(h))
            self.vars["tile_name"].set(tile_name or f"Tile {tile_index}")
            self.vars["preset_name"].set(preset_name)
        finally:
            self._suspend_events = False
        self._set_inspector_mode("tile")

    def set_tile_preset_name(self, preset_name: str) -> None:
        self._suspend_events = True
        try:
            self.vars["preset_name"].set(preset_name)
        finally:
            self._suspend_events = False

    def show_text_item(self, text_index: int, settings: TextOverlaySettings, z_label: str = "-") -> None:
        self._selected_list_index = None
        self._selected_text_index = text_index
        self._selected_tile_index = None
        self._selected_item_mapped = False
        self._selected_tile_index = None
        self.vars["selection"].set(f"Text item {text_index + 1}")
        self.vars["tile"].set("Text overlay")
        self.vars["z_level"].set(z_label)
        self.vars["default_coords"].set("-")
        if settings.duration_sec is None:
            self.vars["duration"].set("Always on (when enabled)")
        else:
            self.vars["duration"].set(format_duration(settings.duration_sec))
        self.vars["fps"].set("-")
        self.vars["audio"].set("-")
        preview = settings.text.strip() or "(empty text)"
        self.vars["path"].set(preview[:48])
        self.vars["include_in_mix"].set(False)
        self._set_position_entries((0, 0))
        self.set_text_overlay(settings)
        self.vars["z_input"].set(str(text_index + 1))
        self._set_text_editor_enabled(True)
        self._set_inspector_mode("text")

    def set_text_overlay(self, settings: TextOverlaySettings) -> None:
        self._suspend_events = True
        try:
            self.vars["text_enabled"].set(settings.enabled)
            self.vars["text"].set(settings.text)
            self.vars["text_x"].set(str(settings.x))
            self.vars["text_y"].set(str(settings.y))
            self.vars["text_size"].set(str(settings.size))
            self.vars["text_color"].set((settings.color or "white").strip() or "white")
            self._sync_text_color_sliders_from_value(self.vars["text_color"].get())
            self.vars["text_start_at"].set(format_timecode(settings.start_at_sec))
            self.vars["text_duration"].set(
                format_timecode(settings.duration_sec) if settings.duration_sec is not None else ""
            )
        finally:
            self._suspend_events = False

    def clear(self) -> None:
        self._selected_list_index = None
        self._selected_text_index = None
        self._selected_item_mapped = False
        self.vars["selection"].set("None")
        for key in ("tile", "z_level", "default_coords", "duration", "fps", "audio", "path"):
            self.vars[key].set("-")
        self._set_position_entries((0, 0))
        self.vars["include_in_mix"].set(False)
        self.vars["z_input"].set("1")
        self._set_text_editor_enabled(False)
        self._set_inspector_mode("none")

    def activate_text_overlay_editor(self) -> None:
        self._set_text_editor_enabled(True)
        self._suspend_events = True
        try:
            self.vars["text_enabled"].set(True)
        finally:
            self._suspend_events = False
        self._emit_text_overlay_change()
        self.text_entry.focus_set()
        try:
            self.text_entry.selection_range(0, tk.END)
            self.text_entry.icursor(tk.END)
        except Exception:
            pass

    def _set_text_editor_enabled(self, enabled: bool) -> None:
        state = "!disabled" if enabled else "disabled"
        for widget in (
            self.text_entry,
            self.text_x_entry,
            self.text_y_entry,
            self.text_size_entry,
            self.text_color_entry,
            self.text_r_scale,
            self.text_g_scale,
            self.text_b_scale,
            self.text_start_at_entry,
            self.text_duration_entry,
        ):
            try:
                widget.state([state])
            except Exception:
                pass

    def _set_inspector_mode(self, mode: str) -> None:
        if mode == "text":
            self.info_frame.grid_remove()
            self.pos_frame.grid_remove()
            self.audio_frame.grid_remove()
            self.tile_frame.grid_remove()
            self.text_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 8))
            return
        if mode == "video":
            self.info_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
            self.text_frame.grid_remove()
            self.tile_frame.grid_remove()
            self.pos_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
            self.audio_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
            return
        if mode == "tile":
            self.info_frame.grid_remove()
            self.pos_frame.grid_remove()
            self.audio_frame.grid_remove()
            self.text_frame.grid_remove()
            self.tile_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 8))
            return
        self.info_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        self.pos_frame.grid_remove()
        self.audio_frame.grid_remove()
        self.text_frame.grid_remove()
        self.tile_frame.grid_remove()

    def _set_position_entries(self, coords: tuple[int, int]) -> None:
        self._suspend_events = True
        try:
            self.vars["pos_x"].set(str(int(coords[0])))
            self.vars["pos_y"].set(str(int(coords[1])))
        finally:
            self._suspend_events = False

    def _handle_entry_commit(self, _event: object) -> None:
        widget = getattr(_event, "widget", None)
        if widget in {self.pos_x_entry, self.pos_y_entry}:
            self._emit_position_change()
            return
        if widget in {self.trim_start_entry, self.trim_end_entry, self.video_start_at_entry}:
            self._emit_video_timing_change()
            return
        if widget == self.text_color_entry:
            self._sync_text_color_sliders_from_value(self.vars["text_color"].get())
        if widget in {
            self.text_entry,
            self.text_x_entry,
            self.text_y_entry,
            self.text_size_entry,
            self.text_color_entry,
            self.text_start_at_entry,
            self.text_duration_entry,
        }:
            self._emit_text_overlay_change()

    def _handle_tile_entry_commit(self, _event: object) -> None:
        self._emit_tile_layout_change()

    def _emit_position_change(self) -> None:
        if self._suspend_events or not self._selected_item_mapped or self._on_position_change is None:
            return
        try:
            x = int(self.vars["pos_x"].get().strip())
            y = int(self.vars["pos_y"].get().strip())
        except ValueError:
            return
        self._on_position_change(x, y)

    def _handle_reset_position(self) -> None:
        if self._on_reset_position is None or not self._selected_item_mapped:
            return
        self._on_reset_position()

    def _emit_include_in_mix_change(self) -> None:
        if self._suspend_events or not self._selected_item_mapped or self._on_include_in_mix_change is None:
            return
        self._on_include_in_mix_change(bool(self.vars["include_in_mix"].get()))

    def _emit_text_overlay_change(self) -> None:
        if self._suspend_events or self._on_text_overlay_change is None:
            return
        try:
            text_start = parse_timecode(self.vars["text_start_at"].get())
            text_duration_raw = self.vars["text_duration"].get().strip()
            text_duration = None if text_duration_raw == "" else parse_timecode(text_duration_raw)
            if text_start is None or (text_duration_raw != "" and text_duration is None):
                return
            settings = TextOverlaySettings(
                enabled=bool(self.vars["text_enabled"].get()),
                text=self.vars["text"].get(),
                x=int(self.vars["text_x"].get().strip() or "0"),
                y=int(self.vars["text_y"].get().strip() or "0"),
                size=max(1, int(self.vars["text_size"].get().strip() or "1")),
                color=(self.vars["text_color"].get().strip() or "white"),
                start_at_sec=text_start,
                duration_sec=text_duration,
            )
        except ValueError:
            return
        self._on_text_overlay_change(settings)

    def _on_text_rgb_slider_change(self, _value: str | None = None) -> None:
        if self._suspend_events:
            return
        r = max(0, min(255, int(round(float(self.vars["text_r"].get())))))
        g = max(0, min(255, int(round(float(self.vars["text_g"].get())))))
        b = max(0, min(255, int(round(float(self.vars["text_b"].get())))))
        self._suspend_events = True
        try:
            self.vars["text_color"].set(f"#{r:02x}{g:02x}{b:02x}")
        finally:
            self._suspend_events = False
        self._emit_text_overlay_change()

    def _sync_text_color_sliders_from_value(self, color_value: str) -> None:
        color = (color_value or "").strip()
        if not color:
            return
        try:
            r16, g16, b16 = self.winfo_rgb(color)
        except tk.TclError:
            return
        r = int(round(r16 / 257))
        g = int(round(g16 / 257))
        b = int(round(b16 / 257))
        self._suspend_events = True
        try:
            self.vars["text_r"].set(r)
            self.vars["text_g"].set(g)
            self.vars["text_b"].set(b)
        finally:
            self._suspend_events = False

    def _emit_video_timing_change(self) -> None:
        if self._suspend_events or not self._selected_item_mapped or self._on_video_timing_change is None:
            return
        self._on_video_timing_change(
            self.vars["trim_start"].get(),
            self.vars["trim_end"].get(),
            self.vars["video_start_at"].get(),
        )

    def _emit_z_level_change(self) -> None:
        if self._suspend_events or self._on_z_level_change is None:
            return
        try:
            z = int(self.vars["z_input"].get().strip())
        except ValueError:
            return
        self._on_z_level_change(z)

    def _emit_tile_layout_change(self) -> None:
        if self._suspend_events or self._on_tile_layout_change is None or self._selected_tile_index is None:
            return
        try:
            x = int(self.vars["tile_x"].get().strip())
            y = int(self.vars["tile_y"].get().strip())
            w = int(self.vars["tile_w"].get().strip())
            h = int(self.vars["tile_h"].get().strip())
        except ValueError:
            return
        self._on_tile_layout_change(x, y, w, h, self.vars["tile_name"].get())
