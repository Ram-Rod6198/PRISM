from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from video_combiner.src.composer import FFmpegComposer
from video_combiner.src.model import TextOverlaySettings, VideoItem, VideoListModel
from video_combiner.src.probe import ProbeError, ProbeService
from video_combiner.src.render import FFmpegRenderer
from video_combiner.src.thumbs import ThumbnailError, ThumbnailService
from video_combiner.src.ui_inspector import InspectorPanel
from video_combiner.src.ui_list import TextListPanel, TileListPanel, VideoListPanel
from video_combiner.src.ui_preview import PreviewCanvas
from video_combiner.src.utils import format_duration, parse_timecode, short_name


AUDIO_LABEL_TO_MODE = {
    "Mix all": "mix_all",
    "Tile 1 only": "tile_1",
    "Tile 2 only": "tile_2",
    "Tile 3 only": "tile_3",
    "Tile 4 only": "tile_4",
    "None": "none",
}
PREVIEW_SELECT_MODE_MAP = {
    "Videos Only": "videos",
    "Text Only": "text",
    "Tiles Only": "tiles",
    "Videos + Text": "both",
}


class VideoCombinerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Video Multiplux Combiner")
        self.root.geometry("1520x820")
        self.root.minsize(1320, 760)

        self.model = VideoListModel()
        self.probe_service = ProbeService()
        self.thumb_service = ThumbnailService()
        self.composer = FFmpegComposer()
        self.renderer = FFmpegRenderer()

        self.status_var = tk.StringVar(value="Add videos to begin.")
        self.audio_choice_var = tk.StringVar(value="Mix all")
        self.debug_var = tk.BooleanVar(value=False)
        self.preview_select_mode_var = tk.StringVar(value="Videos Only")
        self.hide_tile_names_var = tk.BooleanVar(value=True)
        self.preview_drag_enabled_var = tk.BooleanVar(value=False)
        self.canvas_w_var = tk.StringVar(value=str(self.model.output_width))
        self.canvas_h_var = tk.StringVar(value=str(self.model.output_height))
        self.canvas_auto_resize_var = tk.BooleanVar(value=False)
        self.canvas_preset_name_var = tk.StringVar(value="My Preset")
        self.is_rendering = False
        self.debug_enabled_for_run = False
        self.selected_preview_tile: int | None = None
        self.selected_preview_kind: str | None = None
        self.selected_canvas_tile_index: int | None = None
        self.selected_text_index: int | None = None
        self._preview_configure_after_id: str | None = None

        self.preview: PreviewCanvas
        self.preview_x_scroll: ttk.Scrollbar
        self.preview_y_scroll: ttk.Scrollbar
        self.inspector: InspectorPanel
        self.inspector_host: ttk.Frame
        self.inspector_scroll_canvas: tk.Canvas
        self.inspector_scrollbar: ttk.Scrollbar
        self.inspector_scroll_inner: ttk.Frame
        self.video_list_panel: VideoListPanel
        self.layer_notebook: ttk.Notebook
        self.video_tab: ttk.Frame
        self.tiles_tab: ttk.Frame
        self.tile_list_panel: TileListPanel
        self.text_list_panel: TextListPanel
        self.audio_combo: ttk.Combobox
        self.render_btn: ttk.Button
        self.preview_select_combo: ttk.Combobox
        self.canvas_preset_combo: ttk.Combobox
        self.tile_listbox: tk.Listbox
        self.command_window: tk.Toplevel | None = None
        self.command_text: tk.Text | None = None
        self.stderr_window: tk.Toplevel | None = None
        self.stderr_text: tk.Text | None = None
        self.last_exact_command_str = ""
        self.canvas_presets: list[dict[str, object]] = []

        self._init_canvas_presets()
        self._load_user_canvas_presets()
        self._build_ui()
        self.refresh_ui()
        self.root.after_idle(self.refresh_preview)

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=10)
        root_frame.pack(fill="both", expand=True)

        pane = ttk.Panedwindow(root_frame, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=3)
        pane.add(right, weight=2)

        preview_header = ttk.Frame(left)
        preview_header.pack(fill="x", pady=(0, 6))
        ttk.Label(preview_header, text="Static Preview").pack(side="left")
        ttk.Button(preview_header, text="-", width=3, command=self._preview_zoom_out).pack(side="left", padx=(8, 2))
        ttk.Button(preview_header, text="+", width=3, command=self._preview_zoom_in).pack(side="left", padx=(0, 2))
        ttk.Button(preview_header, text="Reset Zoom", command=self._preview_zoom_reset).pack(side="left", padx=(0, 8))
        ttk.Label(preview_header, text="Selectable:").pack(side="left", padx=(12, 4))
        self.preview_select_combo = ttk.Combobox(
            preview_header,
            state="readonly",
            values=list(PREVIEW_SELECT_MODE_MAP.keys()),
            textvariable=self.preview_select_mode_var,
            width=14,
        )
        self.preview_select_combo.pack(side="left")
        self.preview_select_combo.bind("<<ComboboxSelected>>", self._on_preview_select_mode_changed)
        ttk.Checkbutton(
            preview_header,
            text="Allow Dragging",
            variable=self.preview_drag_enabled_var,
        ).pack(side="left", padx=(8, 0))
        preview_frame = ttk.Frame(left)
        preview_frame.pack(fill="both", expand=True, anchor="nw")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview = PreviewCanvas(
            preview_frame,
            width=960,
            height=540,
            on_tile_click=self.on_preview_tile_click,
            on_item_drag=self.on_preview_item_drag,
        )
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview_y_scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview.yview)
        self.preview_y_scroll.grid(row=0, column=1, sticky="ns")
        self.preview_x_scroll = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.preview.xview)
        self.preview_x_scroll.grid(row=1, column=0, sticky="ew")
        self.preview.configure(xscrollcommand=self.preview_x_scroll.set, yscrollcommand=self.preview_y_scroll.set)
        self.preview.bind("<Configure>", self._on_preview_widget_configure, add="+")
        self.preview.set_selection_mode(PREVIEW_SELECT_MODE_MAP[self.preview_select_mode_var.get()])

        presets_frame = ttk.LabelFrame(left, text="Canvas Presets / Output Canvas")
        presets_frame.pack(fill="x", pady=(10, 0))
        top_row = ttk.Frame(presets_frame)
        top_row.pack(fill="x", padx=8, pady=(8, 6))
        ttk.Label(top_row, text="Preset").pack(side="left")
        self.canvas_preset_combo = ttk.Combobox(top_row, state="readonly", width=22)
        self.canvas_preset_combo.pack(side="left", padx=(4, 8))
        self.canvas_preset_combo.bind("<<ComboboxSelected>>", self._on_canvas_preset_selected)
        ttk.Button(top_row, text="Load Preset", command=self.apply_selected_canvas_preset).pack(side="left")
        ttk.Label(top_row, text="Width").pack(side="left")
        self.canvas_w_entry = ttk.Entry(top_row, textvariable=self.canvas_w_var, width=8)
        self.canvas_w_entry.pack(side="left", padx=(4, 8))
        ttk.Label(top_row, text="Height").pack(side="left")
        self.canvas_h_entry = ttk.Entry(top_row, textvariable=self.canvas_h_var, width=8)
        self.canvas_h_entry.pack(side="left", padx=(4, 8))
        ttk.Checkbutton(top_row, text="Auto resize", variable=self.canvas_auto_resize_var).pack(
            side="left", padx=(4, 8)
        )
        ttk.Button(top_row, text="Apply Canvas", command=self.apply_canvas_size).pack(side="left")

        preset_actions = ttk.Frame(presets_frame)
        preset_actions.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(preset_actions, text="Preset Name").pack(side="left")
        ttk.Entry(preset_actions, textvariable=self.canvas_preset_name_var, width=20).pack(
            side="left", padx=(4, 8)
        )
        ttk.Button(preset_actions, text="Save/Update", command=self.save_canvas_preset).pack(side="left")
        ttk.Button(preset_actions, text="Delete", command=self.delete_canvas_preset).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            presets_frame,
            text="Preset dropdown selects/saves canvas + tile rectangles. Edit tile rows from the Tiles tab on the right (videos render into available tiles in list order).",
            wraplength=940,
        ).pack(anchor="w", padx=8, pady=(0, 8))
        self._refresh_canvas_preset_rows()
        self._build_menu()

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self.inspector_host = ttk.Frame(right, height=360)
        self.inspector_host.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.inspector_host.grid_propagate(False)
        self.inspector_host.columnconfigure(0, weight=1)
        self.inspector_host.rowconfigure(0, weight=1)

        self.inspector_scroll_canvas = tk.Canvas(
            self.inspector_host,
            highlightthickness=0,
            borderwidth=0,
            background=self.root.cget("background"),
        )
        self.inspector_scrollbar = ttk.Scrollbar(
            self.inspector_host, orient="vertical", command=self.inspector_scroll_canvas.yview
        )
        self.inspector_scroll_inner = ttk.Frame(self.inspector_scroll_canvas)
        self.inspector_scroll_canvas.configure(yscrollcommand=self.inspector_scrollbar.set)
        self.inspector_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.inspector_scrollbar.grid(row=0, column=1, sticky="ns")
        self.inspector_host.columnconfigure(0, weight=1)
        self.inspector_host.columnconfigure(1, weight=0)
        self.inspector_scroll_inner.columnconfigure(0, weight=1)
        self.inspector_scroll_inner.rowconfigure(0, weight=1)
        self._inspector_window_id = self.inspector_scroll_canvas.create_window(
            (0, 0), window=self.inspector_scroll_inner, anchor="nw"
        )
        self.inspector_scroll_inner.bind("<Configure>", self._on_inspector_inner_configure)
        self.inspector_scroll_canvas.bind("<Configure>", self._on_inspector_canvas_configure)
        self.inspector_scroll_canvas.bind_all("<MouseWheel>", self._on_inspector_mousewheel, add="+")

        self.inspector = InspectorPanel(
            self.inspector_scroll_inner,
            on_position_change=self.on_inspector_position_change,
            on_reset_position=self.on_inspector_reset_position,
            on_include_in_mix_change=self.on_inspector_include_in_mix_change,
            on_z_level_change=self.on_inspector_z_level_change,
            on_video_timing_change=self.on_inspector_video_timing_change,
            on_text_overlay_change=self.on_inspector_text_overlay_change,
            on_tile_layout_change=self.on_inspector_tile_layout_change,
        )
        self.inspector.grid(row=0, column=0, sticky="nsew")

        lists_frame = ttk.Frame(right)
        lists_frame.grid(row=1, column=0, sticky="nsew")
        lists_frame.columnconfigure(0, weight=1)
        lists_frame.columnconfigure(1, weight=1)
        lists_frame.rowconfigure(0, weight=1)

        self.layer_notebook = ttk.Notebook(lists_frame)
        self.layer_notebook.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.video_tab = ttk.Frame(self.layer_notebook)
        self.tiles_tab = ttk.Frame(self.layer_notebook)
        self.video_tab.columnconfigure(0, weight=1)
        self.video_tab.rowconfigure(0, weight=1)
        self.tiles_tab.columnconfigure(0, weight=1)
        self.tiles_tab.rowconfigure(0, weight=1)
        self.layer_notebook.add(self.video_tab, text="Videos")
        self.layer_notebook.add(self.tiles_tab, text="Tiles")

        self.video_list_panel = VideoListPanel(
            self.video_tab,
            on_add=self.add_videos,
            on_remove=self.remove_selected_video,
            on_up=self.move_selected_video_up,
            on_down=self.move_selected_video_down,
            on_select=self.on_video_list_selection,
        )
        self.video_list_panel.grid(row=0, column=0, sticky="nsew")

        self.tile_list_panel = TileListPanel(
            self.tiles_tab,
            on_add_tile=self.add_tile_layout,
            on_remove=self.remove_selected_tile,
            on_up=self.move_selected_tile_up,
            on_down=self.move_selected_tile_down,
            on_select=self.on_tile_list_selection,
        )
        self.tile_list_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        self.text_list_panel = TextListPanel(
            lists_frame,
            on_add_text=self.add_text_overlay,
            on_remove=self.remove_selected_text,
            on_up=self.move_selected_text_up,
            on_down=self.move_selected_text_down,
            on_select=self.on_text_list_selection,
        )
        self.text_list_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._refresh_tile_rows()

        audio_frame = ttk.LabelFrame(right, text="Audio Mode")
        audio_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.audio_combo = ttk.Combobox(
            audio_frame,
            state="readonly",
            values=list(AUDIO_LABEL_TO_MODE.keys()),
            textvariable=self.audio_choice_var,
        )
        self.audio_combo.pack(fill="x", padx=8, pady=8)
        self.audio_combo.bind("<<ComboboxSelected>>", self._on_audio_mode_changed)

        actions = ttk.Frame(right)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.render_btn = ttk.Button(actions, text="Render MP4", command=self.start_render)
        self.render_btn.pack(side="left")
        ttk.Button(actions, text="Show Last Command", command=self.show_last_command_window).pack(
            side="left", padx=(10, 0)
        )

        ttk.Label(right, textvariable=self.status_var, wraplength=500).grid(
            row=4, column=0, sticky="ew", pady=(8, 4)
        )

    def _on_inspector_inner_configure(self, _event: object) -> None:
        if not hasattr(self, "inspector_scroll_canvas"):
            return
        self.inspector_scroll_canvas.configure(scrollregion=self.inspector_scroll_canvas.bbox("all"))

    def _on_inspector_canvas_configure(self, event: tk.Event) -> None:
        if not hasattr(self, "inspector_scroll_canvas") or not hasattr(self, "_inspector_window_id"):
            return
        self.inspector_scroll_canvas.itemconfigure(self._inspector_window_id, width=event.width)

    def _on_inspector_mousewheel(self, event: tk.Event) -> None:
        try:
            if not self.inspector_host.winfo_exists():
                return
            widget_under = self.root.winfo_containing(event.x_root, event.y_root)
            if widget_under is None:
                return
            parent = widget_under
            within_inspector = False
            while parent is not None:
                if parent == self.inspector_host:
                    within_inspector = True
                    break
                try:
                    parent = parent.master
                except Exception:
                    parent = None
            if not within_inspector:
                return
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return
            self.inspector_scroll_canvas.yview_scroll(int(-1 * (delta / 120)), "units")
        except Exception:
            return

    def _on_preview_widget_configure(self, _event: object) -> None:
        # Debounce resize-driven redraws so the preview stabilizes after startup/layout changes.
        try:
            if self._preview_configure_after_id is not None:
                self.root.after_cancel(self._preview_configure_after_id)
        except Exception:
            pass
        self._preview_configure_after_id = self.root.after(30, self._refresh_preview_after_configure)

    def _refresh_preview_after_configure(self) -> None:
        self._preview_configure_after_id = None
        self.refresh_preview()

    def add_videos(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select one or more videos",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return

        added: list[VideoItem] = []
        warnings: list[str] = []
        for path in paths:
            if not os.path.isfile(path):
                warnings.append(f"Skipped invalid file: {path}")
                continue
            try:
                item = self.probe_service.probe(path)
            except FileNotFoundError:
                messagebox.showerror(
                    "ffprobe Not Found",
                    "ffprobe was not found (bundled binary missing and not on PATH).",
                )
                self.status_var.set("ffprobe not found.")
                break
            except ProbeError as exc:
                warnings.append(f"Probe failed for {short_name(path)}: {exc}")
                continue
            try:
                item.thumb_path = self.thumb_service.generate(path)
            except FileNotFoundError:
                messagebox.showerror(
                    "ffmpeg Not Found",
                    "ffmpeg was not found (bundled binary missing and not on PATH).",
                )
                self.status_var.set("ffmpeg not found.")
                item.thumb_path = None
                break
            except ThumbnailError:
                warnings.append(f"Thumbnail failed for {short_name(path)}")
                item.thumb_path = None
            added.append(item)

        if added:
            self.model.add_items(added)
            self.status_var.set(f"Added {len(added)} video(s).")
            self.refresh_ui(select_video_index=len(self.model.items) - 1)
        else:
            self.refresh_ui()

        if warnings:
            messagebox.showwarning("Warnings", "\n".join(warnings[:20]))

    def add_text_overlay(self) -> None:
        idx = self.model.add_text_overlay(TextOverlaySettings(enabled=True, text="Your Text"))
        self.status_var.set("Text layer added. Edit it in the Inspector.")
        self.refresh_ui(select_text_index=idx)
        self.inspector.activate_text_overlay_editor()

    def remove_selected_video(self) -> None:
        index = self.video_list_panel.selected_index()
        if index is None:
            return
        self.model.remove(index)
        self.selected_preview_tile = None
        next_index = None if not self.model.items else min(index, len(self.model.items) - 1)
        self.refresh_ui(select_video_index=next_index)

    def move_selected_video_up(self) -> None:
        index = self.video_list_panel.selected_index()
        if index is None:
            return
        new_index = self.model.move_up(index)
        self.refresh_ui(select_video_index=new_index)

    def move_selected_video_down(self) -> None:
        index = self.video_list_panel.selected_index()
        if index is None:
            return
        new_index = self.model.move_down(index)
        self.refresh_ui(select_video_index=new_index)

    def remove_selected_text(self) -> None:
        index = self.text_list_panel.selected_index()
        if index is None:
            return
        self.model.remove_text_overlay(index)
        self.selected_text_index = None
        next_index = None if not self.model.text_overlays else min(index, len(self.model.text_overlays) - 1)
        self.refresh_ui(select_text_index=next_index)

    def move_selected_text_up(self) -> None:
        index = self.text_list_panel.selected_index()
        if index is None:
            return
        new_index = self.model.move_text_overlay_up(index)
        self.refresh_ui(select_text_index=new_index)

    def move_selected_text_down(self) -> None:
        index = self.text_list_panel.selected_index()
        if index is None:
            return
        new_index = self.model.move_text_overlay_down(index)
        self.refresh_ui(select_text_index=new_index)

    def on_video_list_selection(self, index: int | None) -> None:
        if index is not None:
            self._show_layers_tab("videos")
            self.text_list_panel.clear_selection()
            self.selected_text_index = None
            self.selected_canvas_tile_index = None
            self.selected_preview_tile = (index + 1) if index < self.model.rendered_slot_count() else None
            self.selected_preview_kind = "video" if index < self.model.rendered_slot_count() else None
        else:
            self.selected_preview_tile = None
            self.selected_canvas_tile_index = None
            self.selected_preview_kind = None
        self.refresh_preview()
        self.refresh_inspector()

    def on_text_list_selection(self, index: int | None) -> None:
        if index is not None:
            self.video_list_panel.clear_selection()
            self.selected_text_index = index
            self.selected_canvas_tile_index = None
            self.selected_preview_tile = None
            self.selected_preview_kind = "text"
        else:
            self.selected_text_index = None
            self.selected_canvas_tile_index = None
            self.selected_preview_kind = None
        self.refresh_preview()
        self.refresh_inspector()

    def on_tile_list_selection(self, index: int | None) -> None:
        if index is None:
            return
        self._show_layers_tab("tiles")
        self.selected_canvas_tile_index = index
        self.selected_preview_kind = "tile"
        self.selected_preview_tile = (index + 1) if index < self.model.rendered_slot_count() else None
        self.selected_text_index = None
        self.video_list_panel.clear_selection()
        self.text_list_panel.clear_selection()
        self.refresh_preview()
        self.refresh_inspector()

    def on_preview_tile_click(self, selection_kind: str | None, selection_index: int | None) -> None:
        if selection_kind is None or selection_index is None:
            self.selected_preview_tile = None
            self.selected_preview_kind = None
            self.selected_canvas_tile_index = None
            self.selected_text_index = None
            self.video_list_panel.clear_selection()
            self.text_list_panel.clear_selection()
            self.refresh_preview()
            self.refresh_inspector()
            return
        if selection_kind == "text":
            self.selected_preview_tile = None
            self.selected_preview_kind = "text"
            self.selected_canvas_tile_index = None
            self.selected_text_index = selection_index
            self.video_list_panel.clear_selection()
            self.text_list_panel.select_index(selection_index)
        elif selection_kind == "tile":
            self._show_layers_tab("tiles")
            self.selected_preview_tile = selection_index
            self.selected_preview_kind = "tile"
            self.selected_canvas_tile_index = selection_index - 1
            self.selected_text_index = None
            self.video_list_panel.clear_selection()
            self.text_list_panel.clear_selection()
            self._select_tile_list_index(selection_index - 1)
        elif selection_kind == "video":
            self._show_layers_tab("videos")
            tile_index = selection_index
            self.selected_preview_tile = tile_index
            self.selected_preview_kind = "video"
            self.selected_canvas_tile_index = None
            self.selected_text_index = None
            self.text_list_panel.clear_selection()
            if tile_index - 1 < len(self.model.items):
                self.video_list_panel.select_index(tile_index - 1)
            else:
                self.video_list_panel.clear_selection()
        self.refresh_preview()
        self.refresh_inspector()

    def on_preview_item_drag(self, kind: str, index: int, x: int, y: int) -> None:
        if not bool(self.preview_drag_enabled_var.get()):
            return
        if kind == "video":
            tile_idx = index - 1
            if tile_idx < 0 or tile_idx >= min(self.model.rendered_slot_count(), len(self.model.items)):
                return
            item = self.model.items[tile_idx]
            item.pos_x = int(x)
            item.pos_y = int(y)
            item.custom_position = True
        elif kind == "text":
            if index < 0 or index >= len(self.model.text_overlays):
                return
            overlay = self.model.text_overlays[index]
            overlay.x = int(x)
            overlay.y = int(y)
        elif kind == "tile":
            tile_idx = index - 1
            rect = self.model.tile_rect(tile_idx)
            if rect is None:
                return
            _old_x, _old_y, w, h = rect
            self.model.update_tile_rect(tile_idx, int(x), int(y), int(w), int(h))
        else:
            return
        self.refresh_preview()
        self.refresh_inspector()

    def refresh_ui(
        self,
        select_video_index: int | None = None,
        select_text_index: int | None = None,
    ) -> None:
        self.video_list_panel.set_rows(self._build_video_rows())
        self.text_list_panel.set_rows(self._build_text_rows())

        if select_video_index is not None:
            self._show_layers_tab("videos")
            self.text_list_panel.clear_selection()
            self.video_list_panel.select_index(select_video_index)
            self.selected_text_index = None
            self.selected_canvas_tile_index = None
            self.selected_preview_kind = "video" if select_video_index < self.model.rendered_slot_count() else None
        if select_text_index is not None:
            self.video_list_panel.clear_selection()
            self.text_list_panel.select_index(select_text_index)
            self.selected_text_index = select_text_index
            self.selected_canvas_tile_index = None
            self.selected_preview_kind = "text"

        self.refresh_preview()
        self.refresh_inspector()
        self._update_render_state()
        self.inspector.set_audio_mode_label(self.audio_choice_var.get())
        self._refresh_canvas_preset_rows()
        self._refresh_tile_rows()

    def refresh_preview(self) -> None:
        selected_index = self.video_list_panel.selected_index()
        if selected_index is not None and selected_index < self.model.rendered_slot_count():
            self.preview.set_selected_tile(selected_index + 1, None)
        elif (
            self.selected_preview_kind == "tile"
            and self.selected_canvas_tile_index is not None
            and 0 <= self.selected_canvas_tile_index < self.model.rendered_slot_count()
        ):
            self.preview.set_selected_tile(self.selected_canvas_tile_index + 1, None)
        else:
            self.preview.set_selected_tile(self.selected_preview_tile, self.text_list_panel.selected_index())
        self.preview.set_selection_mode(PREVIEW_SELECT_MODE_MAP.get(self.preview_select_mode_var.get(), "videos"))
        self.preview.render_tiles(
            self.model.mapped_items(),
            positions=self.model.effective_mapped_positions(),
            tile_rects=self.model.get_tile_rects_copy(),
            tile_labels=self.model.get_tile_names_copy(),
            show_tile_labels=not bool(self.hide_tile_names_var.get()),
            video_z_levels=self.model.effective_mapped_video_z_levels(),
            text_overlays=self.model.text_overlays,
            canvas_size=(self.model.output_width, self.model.output_height),
        )

    def refresh_inspector(self) -> None:
        text_index = self.text_list_panel.selected_index()
        if text_index is not None and 0 <= text_index < len(self.model.text_overlays):
            self.inspector.show_text_item(
                text_index,
                self.model.text_overlays[text_index],
                z_label=self._text_z_label(text_index),
            )
            self.inspector.set_audio_mode_label(self.audio_choice_var.get())
            return

        video_index = self.video_list_panel.selected_index()
        if video_index is not None and 0 <= video_index < len(self.model.items):
            self.inspector.show_list_item(
                video_index,
                self.model.items[video_index],
                effective_coords=self.model.effective_item_coords(video_index),
                default_coords=self.model.default_tile_coords(video_index),
                z_label=self._video_z_label(video_index),
            )
            self.inspector.set_audio_mode_label(self.audio_choice_var.get())
            return

        if self.selected_preview_kind == "tile" and self.selected_canvas_tile_index is not None:
            tile_idx0 = self.selected_canvas_tile_index
            tile_rect = self.model.tile_rect(tile_idx0)
            if tile_rect is not None:
                assigned_item = self.model.items[tile_idx0] if tile_idx0 < len(self.model.items) else None
                self.inspector.show_tile_layout(
                    tile_idx0 + 1,
                    tile_rect,
                    assigned_item=assigned_item,
                    preset_name=self.canvas_preset_name_var.get(),
                    tile_z=self.model.tile_z_level(tile_idx0),
                    tile_name=self.model.tile_name(tile_idx0),
                )
                self.inspector.set_audio_mode_label(self.audio_choice_var.get())
                return

        if self.selected_preview_tile is not None:
            tile_idx = self.selected_preview_tile
            mapped = self.model.mapped_items()
            item = mapped[tile_idx - 1] if (tile_idx - 1) < len(mapped) else None
            tile_rect = self.model.tile_rect(tile_idx - 1)
            if self.selected_preview_kind == "tile" and tile_rect is not None:
                self.inspector.show_tile_layout(
                    tile_idx,
                    tile_rect,
                    assigned_item=item,
                    preset_name=self.canvas_preset_name_var.get(),
                    tile_z=self.model.tile_z_level(tile_idx - 1),
                    tile_name=self.model.tile_name(tile_idx - 1),
                )
                self.inspector.set_audio_mode_label(self.audio_choice_var.get())
                return
            self.inspector.show_tile(
                tile_idx,
                item,
                effective_coords=(
                    self.model.effective_item_coords(tile_idx - 1)
                    if tile_idx - 1 < len(self.model.items)
                    else None
                ),
                tile_rect=tile_rect,
                z_label=self._video_z_label(tile_idx - 1) if item is not None else "Tile empty",
            )
            self.inspector.set_audio_mode_label(self.audio_choice_var.get())
            return

        self.inspector.clear()
        self.inspector.set_audio_mode_label(self.audio_choice_var.get())

    def _update_render_state(self) -> None:
        self.render_btn.config(state="normal" if (self.model.items and not self.is_rendering) else "disabled")

    def _build_current_compose_args(self) -> dict[str, object]:
        return {
            "items_by_slots": self.model.mapped_items(),
            "audio_mode": AUDIO_LABEL_TO_MODE.get(self.audio_choice_var.get(), "mix_all"),
            "fps": self.model.items[0].fps if self.model.items else 30.0,
            "max_duration": self.model.max_duration_mapped(),
            "tile_positions": self.model.effective_mapped_positions(),
            "tile_rects": self.model.effective_mapped_tile_rects(),
            "video_z_levels": self.model.effective_mapped_video_z_levels(),
            "text_overlays": self.model.text_overlays,
            "canvas_size": (self.model.output_width, self.model.output_height),
        }

    def start_render(self) -> None:
        if self.is_rendering:
            return
        if not self.model.items:
            messagebox.showerror("No Videos", "Add at least one video before rendering.")
            return

        default_dir = Path(__file__).resolve().parents[1] / "tmp" / "renders"
        default_dir.mkdir(parents=True, exist_ok=True)
        output_path = filedialog.asksaveasfilename(
            title="Save output MP4",
            initialdir=str(default_dir),
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
        )
        if not output_path:
            return

        try:
            command = self.composer.build_command(
                output_path=output_path,
                **self._build_current_compose_args(),
            )
        except ValueError as exc:
            messagebox.showerror("Render Error", str(exc))
            return

        self.is_rendering = True
        self.debug_enabled_for_run = bool(self.debug_var.get())
        self._update_render_state()
        self.status_var.set("Rendering...")
        self._clear_progress()
        exact_command = self.renderer.resolve_runtime_command(command)
        self.last_exact_command_str = self._format_command_for_display(exact_command)
        self.show_last_command_window()
        if self.debug_enabled_for_run:
            self.show_stderr_window()
            self._append_progress(self.last_exact_command_str)

        threading.Thread(target=self._render_worker, args=(command, output_path), daemon=True).start()

    def _render_worker(self, command: list[str], output_path: str) -> None:
        try:
            exit_code = self.renderer.run(command, on_stderr_line=self._enqueue_progress_line)
        except FileNotFoundError:
            self.root.after(
                0,
                lambda: self._finish_render_error(
                    "ffmpeg Not Found",
                    "ffmpeg was not found (bundled binary missing and not on PATH).",
                ),
            )
            return
        except Exception as exc:
            self.root.after(0, lambda: self._finish_render_error("Render Error", str(exc)))
            return

        if exit_code != 0:
            self.root.after(
                0,
                lambda: self._finish_render_error(
                    "Render Failed",
                    f"ffmpeg exited with code {exit_code}. See debug stderr window for details.",
                ),
            )
            return
        self.root.after(0, lambda: self._finish_render_success(output_path))

    def _enqueue_progress_line(self, line: str) -> None:
        self.root.after(0, lambda l=line: self._handle_progress_line(l))

    def _handle_progress_line(self, line: str) -> None:
        if not line:
            return
        self.status_var.set(line[:220])
        if self.debug_enabled_for_run:
            self._append_progress(line)

    def _append_progress(self, line: str) -> None:
        if self.stderr_text is None or not self.stderr_text.winfo_exists():
            return
        self.stderr_text.configure(state="normal")
        self.stderr_text.insert("end", line + "\n")
        self.stderr_text.see("end")
        self.stderr_text.configure(state="disabled")

    def _clear_progress(self) -> None:
        if self.stderr_text is None or not self.stderr_text.winfo_exists():
            return
        self.stderr_text.configure(state="normal")
        self.stderr_text.delete("1.0", "end")
        self.stderr_text.configure(state="disabled")

    def show_last_command_window(self) -> None:
        if self.command_window is None or not self.command_window.winfo_exists():
            self.command_window = tk.Toplevel(self.root)
            self.command_window.title("Exact FFmpeg Command")
            self.command_window.geometry("980x340")
            container = ttk.Frame(self.command_window, padding=8)
            container.pack(fill="both", expand=True)
            ttk.Label(
                container,
                text="Exact command executed by the app (copy/paste into terminal if needed):",
                wraplength=940,
            ).pack(anchor="w", pady=(0, 6))
            text_frame = ttk.Frame(container)
            text_frame.pack(fill="both", expand=True)
            self.command_text = tk.Text(text_frame, wrap="none")
            self.command_text.pack(side="left", fill="both", expand=True)
            yscroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.command_text.yview)
            yscroll.pack(side="right", fill="y")
            self.command_text.configure(yscrollcommand=yscroll.set)
            xscroll = ttk.Scrollbar(container, orient="horizontal", command=self.command_text.xview)
            xscroll.pack(fill="x")
            self.command_text.configure(xscrollcommand=xscroll.set)
            button_row = ttk.Frame(container)
            button_row.pack(fill="x", pady=(6, 0))
            ttk.Button(button_row, text="Copy", command=self._copy_last_command).pack(side="left")
            ttk.Button(button_row, text="Close", command=self.command_window.destroy).pack(side="right")

        if self.command_text is not None:
            self.command_text.configure(state="normal")
            self.command_text.delete("1.0", "end")
            self.command_text.insert("1.0", self.last_exact_command_str or "No render command generated yet.")
            self.command_text.configure(state="disabled")
        self.command_window.lift()
        self.command_window.focus_force()

    def _copy_last_command(self) -> None:
        if not self.last_exact_command_str:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_exact_command_str)

    def show_stderr_window(self) -> None:
        if self.stderr_window is None or not self.stderr_window.winfo_exists():
            self.stderr_window = tk.Toplevel(self.root)
            self.stderr_window.title("FFmpeg stderr (Debug)")
            self.stderr_window.geometry("980x380")
            container = ttk.Frame(self.stderr_window, padding=8)
            container.pack(fill="both", expand=True)
            ttk.Label(container, text="Live ffmpeg stderr output for the current render.").pack(
                anchor="w", pady=(0, 6)
            )
            text_frame = ttk.Frame(container)
            text_frame.pack(fill="both", expand=True)
            self.stderr_text = tk.Text(text_frame, wrap="none")
            self.stderr_text.pack(side="left", fill="both", expand=True)
            self.stderr_text.configure(state="disabled")
            yscroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.stderr_text.yview)
            yscroll.pack(side="right", fill="y")
            self.stderr_text.configure(yscrollcommand=yscroll.set)
            xscroll = ttk.Scrollbar(container, orient="horizontal", command=self.stderr_text.xview)
            xscroll.pack(fill="x")
            self.stderr_text.configure(xscrollcommand=xscroll.set)
            ttk.Button(container, text="Close", command=self.stderr_window.destroy).pack(anchor="e", pady=(6, 0))
        self.stderr_window.lift()
        self.stderr_window.focus_force()

    @staticmethod
    def _format_command_for_display(command: list[str]) -> str:
        try:
            return subprocess.list2cmdline(command)
        except Exception:
            return " ".join(command)

    def _build_video_rows(self) -> list[str]:
        rows: list[str] = []
        for i, item in enumerate(self.model.items):
            if i < self.model.rendered_slot_count():
                rows.append(f"{short_name(item.path)} ({format_duration(self.model.video_timeline_duration(item))})")
            else:
                rows.append(
                    f"{short_name(item.path)} ({format_duration(self.model.video_timeline_duration(item))}) [not rendered]"
                )
        return rows

    def _build_text_rows(self) -> list[str]:
        rows: list[str] = []
        for i, _overlay in enumerate(self.model.text_overlays):
            rows.append(f"Text {i + 1}")
        return rows

    def _video_z_label(self, video_index: int) -> str:
        if video_index < 0 or video_index >= len(self.model.items):
            return "-"
        if video_index >= self.model.rendered_slot_count():
            return f"Not rendered (outside first {self.model.rendered_slot_count()} tiles)"
        item = self.model.items[video_index]
        z_levels = self.model.effective_mapped_video_z_levels()
        z = z_levels[video_index]
        top_z = max(z_levels, default=z)
        top = "top video layer" if z >= top_z else "below higher z videos"
        inherit = "" if item.custom_layer_z else "; inherited from tile"
        return f"{z} ({top}{inherit}; higher z is on top)"

    def _text_z_label(self, text_index: int) -> str:
        if text_index < 0 or text_index >= len(self.model.text_overlays):
            return "-"
        z = text_index + 1
        top = "top text layer" if z == len(self.model.text_overlays) else "below later text rows"
        return f"{z} ({top}; text layers render above all videos)"

    def _on_audio_mode_changed(self, _event: object) -> None:
        self.inspector.set_audio_mode_label(self.audio_choice_var.get())

    def _on_preview_select_mode_changed(self, _event: object) -> None:
        self.preview.set_selection_mode(PREVIEW_SELECT_MODE_MAP.get(self.preview_select_mode_var.get(), "videos"))
        self.refresh_preview()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        options_menu = tk.Menu(menubar, tearoff=False)
        options_menu.add_checkbutton(label="Debug (stderr window)", variable=self.debug_var)
        options_menu.add_checkbutton(
            label="Hide Tile Names on Canvas",
            variable=self.hide_tile_names_var,
            command=self.refresh_preview,
        )
        menubar.add_cascade(label="Options", menu=options_menu)
        self.root.configure(menu=menubar)

    def _preview_zoom_in(self) -> None:
        self.preview.zoom_in()
        self.refresh_preview()

    def _preview_zoom_out(self) -> None:
        self.preview.zoom_out()
        self.refresh_preview()

    def _preview_zoom_reset(self) -> None:
        self.preview.reset_zoom()
        self.preview.xview_moveto(0.0)
        self.preview.yview_moveto(0.0)
        self.refresh_preview()

    def _init_canvas_presets(self) -> None:
        def tiles_for(w: int, h: int) -> list[dict[str, int]]:
            half_w = max(1, w // 2)
            half_h = max(1, h // 2)
            return [
                {"x": 0, "y": 0, "w": half_w, "h": half_h, "z": 1, "label": "Tile 1"},
                {"x": half_w, "y": 0, "w": max(1, w - half_w), "h": half_h, "z": 2, "label": "Tile 2"},
                {"x": 0, "y": half_h, "w": half_w, "h": max(1, h - half_h), "z": 3, "label": "Tile 3"},
                {"x": half_w, "y": half_h, "w": max(1, w - half_w), "h": max(1, h - half_h), "z": 4, "label": "Tile 4"},
            ]

        def tiles_for_3_top_2_centered_1080() -> list[dict[str, int]]:
            # Canvas: 5760x2160 (3 * 1920 wide, 2 * 1080 high)
            # Layout:
            # XXX
            #  XX   (bottom two centered with 960px side margins)
            return [
                {"x": 0, "y": 0, "w": 1920, "h": 1080, "z": 1, "label": "Tile 1"},
                {"x": 1920, "y": 0, "w": 1920, "h": 1080, "z": 2, "label": "Tile 2"},
                {"x": 3840, "y": 0, "w": 1920, "h": 1080, "z": 3, "label": "Tile 3"},
                {"x": 960, "y": 1080, "w": 1920, "h": 1080, "z": 4, "label": "Tile 4"},
                {"x": 2880, "y": 1080, "w": 1920, "h": 1080, "z": 5, "label": "Tile 5"},
            ]

        self.canvas_presets = [
            {"name": "2x2 for 4K", "w": 3840, "h": 2160, "tiles": tiles_for(3840, 2160), "builtin": True},
            {"name": "2x2 1080p", "w": 1920, "h": 1080, "tiles": tiles_for(1920, 1080), "builtin": True},
            {"name": "2x2 720p", "w": 1280, "h": 720, "tiles": tiles_for(1280, 720), "builtin": True},
            {
                "name": "3 Top + 2 Centered (1080p tiles)",
                "w": 5760,
                "h": 2160,
                "tiles": tiles_for_3_top_2_centered_1080(),
                "builtin": True,
            },
        ]

    def _canvas_preset_store_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "data" / "canvas_presets.user.json"
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "VideoCombiner" / "canvas_presets.user.json"
        return Path.home() / ".video_combiner" / "canvas_presets.user.json"

    def _canvas_preset_seed_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "assets" / "canvas_presets.user.json"

    def _load_user_canvas_presets(self) -> None:
        existing_names = {str(p.get("name", "")).strip().lower() for p in self.canvas_presets}
        for path in (self._canvas_preset_seed_path(), self._canvas_preset_store_path()):
            try:
                if not path.exists():
                    continue
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, list):
                continue

            for entry in raw:
                preset = self._normalize_loaded_canvas_preset(entry)
                if preset is None:
                    continue
                key = str(preset["name"]).strip().lower()
                if not key or key in existing_names:
                    continue
                self.canvas_presets.append(preset)
                existing_names.add(key)

    def _save_user_canvas_presets(self) -> None:
        path = self._canvas_preset_store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        user_presets = []
        for preset in self.canvas_presets:
            if bool(preset.get("builtin")):
                continue
            normalized = self._normalize_loaded_canvas_preset(preset)
            if normalized is None:
                continue
            user_presets.append(normalized)
        path.write_text(json.dumps(user_presets, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_loaded_canvas_preset(entry: object) -> dict[str, object] | None:
        if not isinstance(entry, dict):
            return None
        try:
            name = str(entry.get("name", "")).strip()
            w = max(2, int(entry.get("w", 0)))
            h = max(2, int(entry.get("h", 0)))
        except Exception:
            return None
        if not name:
            return None

        tiles_raw = entry.get("tiles")
        if not isinstance(tiles_raw, list):
            return None
        tiles: list[dict[str, object]] = []
        for idx, tile in enumerate(tiles_raw):
            if not isinstance(tile, dict):
                continue
            try:
                x = int(tile.get("x", 0))
                y = int(tile.get("y", 0))
                tw = max(1, int(tile.get("w", 1)))
                th = max(1, int(tile.get("h", 1)))
                z = max(1, int(tile.get("z", idx + 1)))
                label = str(tile.get("label", "")).strip() or f"Tile {idx + 1}"
            except Exception:
                continue
            tiles.append({"x": x, "y": y, "w": tw, "h": th, "z": z, "label": label})
        if not tiles:
            return None
        return {"name": name, "w": w, "h": h, "tiles": tiles, "builtin": False}

    def _refresh_canvas_preset_rows(self) -> None:
        if not hasattr(self, "canvas_preset_combo"):
            return
        values = [f"{p['name']} ({p['w']}x{p['h']})" for p in self.canvas_presets]
        self.canvas_preset_combo.configure(values=values)
        if values and not self.canvas_preset_combo.get():
            self.canvas_preset_combo.current(0)

    def _on_canvas_preset_selected(self, _event: object) -> None:
        idx = self._selected_canvas_preset_index()
        if idx is None:
            return
        preset = self.canvas_presets[idx]
        self.canvas_preset_name_var.set(str(preset["name"]))
        self.inspector.set_tile_preset_name(self.canvas_preset_name_var.get())
        self.canvas_w_var.set(str(preset["w"]))
        self.canvas_h_var.set(str(preset["h"]))
        self._load_preset_tiles_into_model_preview(preset)
        self._refresh_tile_rows()

    def _selected_canvas_preset_index(self) -> int | None:
        if not hasattr(self, "canvas_preset_combo"):
            return None
        cur = self.canvas_preset_combo.current()
        return int(cur) if cur is not None and cur >= 0 else None

    def apply_selected_canvas_preset(self) -> None:
        idx = self._selected_canvas_preset_index()
        if idx is None:
            return
        preset = self.canvas_presets[idx]
        tile_rects = self._tile_rects_from_preset(preset)
        tile_z_levels = self._tile_z_levels_from_preset(preset)
        tile_names = self._tile_names_from_preset(preset)
        self.model.set_canvas_layout(
            int(preset["w"]),
            int(preset["h"]),
            tile_rects=tile_rects,
            tile_z_levels=tile_z_levels,
            tile_names=tile_names,
        )
        self.canvas_w_var.set(str(self.model.output_width))
        self.canvas_h_var.set(str(self.model.output_height))
        self._refresh_tile_rows()
        self.refresh_ui(
            select_video_index=self.video_list_panel.selected_index(),
            select_text_index=self.text_list_panel.selected_index(),
        )
        self.status_var.set(f"Applied canvas preset: {preset['name']}")

    def save_canvas_preset(self) -> None:
        try:
            width = self._parse_int_math(self.canvas_w_var.get())
            height = self._parse_int_math(self.canvas_h_var.get())
        except ValueError:
            messagebox.showerror("Canvas Preset", "Width and Height must be integers or basic math expressions.")
            return
        name = self.canvas_preset_name_var.get().strip() or f"{width}x{height}"
        existing_idx = next(
            (i for i, p in enumerate(self.canvas_presets) if str(p["name"]).lower() == name.lower()),
            None,
        )
        preset = {
            "name": name,
            "w": width,
            "h": height,
            "tiles": self._current_tile_preset_dicts(),
            "builtin": False,
        }
        if existing_idx is None:
            self.canvas_presets.append(preset)
            idx = len(self.canvas_presets) - 1
            self.status_var.set(f"Saved canvas preset: {name}")
        else:
            builtin = bool(self.canvas_presets[existing_idx].get("builtin"))
            self.canvas_presets[existing_idx].update(preset)
            self.canvas_presets[existing_idx]["builtin"] = builtin
            idx = existing_idx
            self.status_var.set(f"Updated canvas preset: {name}")
        self._refresh_canvas_preset_rows()
        self.canvas_preset_combo.current(idx)
        self.canvas_preset_name_var.set(name)
        self.inspector.set_tile_preset_name(self.canvas_preset_name_var.get())
        try:
            self._save_user_canvas_presets()
        except Exception as exc:
            messagebox.showwarning("Canvas Preset", f"Saved in session, but failed to persist preset file:\n{exc}")

    def delete_canvas_preset(self) -> None:
        idx = self._selected_canvas_preset_index()
        if idx is None:
            return
        preset = self.canvas_presets[idx]
        if bool(preset.get("builtin")):
            messagebox.showinfo("Canvas Preset", "Built-in presets cannot be deleted.")
            return
        name = str(preset["name"])
        self.canvas_presets.pop(idx)
        self._refresh_canvas_preset_rows()
        if self.canvas_presets:
            next_idx = max(0, min(idx, len(self.canvas_presets) - 1))
            self.canvas_preset_combo.current(next_idx)
            next_preset = self.canvas_presets[next_idx]
            self.canvas_preset_name_var.set(str(next_preset["name"]))
        else:
            self.canvas_preset_name_var.set("My Preset")
        self.inspector.set_tile_preset_name(self.canvas_preset_name_var.get())
        try:
            self._save_user_canvas_presets()
        except Exception as exc:
            messagebox.showwarning("Canvas Preset", f"Deleted in session, but failed to update preset file:\n{exc}")
        self.status_var.set(f"Deleted canvas preset: {name}")

    def apply_canvas_size(self) -> None:
        try:
            width = self._parse_int_math(self.canvas_w_var.get())
            height = self._parse_int_math(self.canvas_h_var.get())
        except ValueError:
            messagebox.showerror("Canvas Size", "Width and Height must be integers or basic math expressions.")
            return
        if width < 2 or height < 2:
            messagebox.showerror("Canvas Size", "Width and Height must be at least 2.")
            return
        old_w = max(1, int(self.model.output_width))
        old_h = max(1, int(self.model.output_height))
        auto_resize = bool(self.canvas_auto_resize_var.get())
        if auto_resize and (old_w != width or old_h != height):
            sx = width / old_w
            sy = height / old_h
            existing_rects = self.model.get_tile_rects_copy()
            for idx, (x, y, w, h) in enumerate(existing_rects):
                self.model.update_tile_rect(
                    idx,
                    int(round(x * sx)),
                    int(round(y * sy)),
                    max(1, int(round(w * sx))),
                    max(1, int(round(h * sy))),
                )
            for item in self.model.items[: self.model.rendered_slot_count()]:
                if item.custom_position:
                    item.pos_x = int(round(item.pos_x * sx))
                    item.pos_y = int(round(item.pos_y * sy))
            for overlay in self.model.text_overlays:
                overlay.x = int(round(overlay.x * sx))
                overlay.y = int(round(overlay.y * sy))
        self.model.set_canvas_size(width, height)
        self.canvas_w_var.set(str(self.model.output_width))
        self.canvas_h_var.set(str(self.model.output_height))
        self._refresh_tile_rows()
        resize_note = " (auto-resized layout)" if auto_resize else ""
        self.status_var.set(
            f"Output canvas set to {self.model.output_width}x{self.model.output_height}{resize_note}."
        )
        self.refresh_ui(
            select_video_index=self.video_list_panel.selected_index(),
            select_text_index=self.text_list_panel.selected_index(),
        )

    def add_tile_layout(self) -> None:
        self._show_layers_tab("tiles")
        new_index = self.model.add_tile_rect()
        self.selected_canvas_tile_index = new_index
        self.selected_preview_kind = "tile"
        self.selected_preview_tile = (new_index + 1) if new_index < self.model.rendered_slot_count() else None
        self.video_list_panel.clear_selection()
        self.text_list_panel.clear_selection()
        self._refresh_tile_rows()
        self._select_tile_list_index(new_index)
        self.refresh_preview()
        self.refresh_inspector()
        self.status_var.set(
            f"Added Tile {new_index + 1}. Videos render into available tiles in list order."
        )

    def remove_selected_tile(self) -> None:
        index = self.tile_list_panel.selected_index()
        if index is None:
            return
        self.selected_canvas_tile_index = index
        self.selected_preview_kind = "tile"
        self.on_inspector_tile_delete()

    def move_selected_tile_up(self) -> None:
        index = self.tile_list_panel.selected_index()
        if index is None:
            return
        new_index = self.model.move_tile_rect_up(index)
        self.selected_canvas_tile_index = new_index
        self.selected_preview_kind = "tile"
        self.selected_preview_tile = (new_index + 1) if new_index < self.model.rendered_slot_count() else None
        self._refresh_tile_rows()
        self.tile_list_panel.select_index(new_index)
        self.refresh_preview()
        self.refresh_inspector()
        self.status_var.set(f"Moved Tile {index + 1} to position {new_index + 1}. Tile order now controls tile z.")

    def move_selected_tile_down(self) -> None:
        index = self.tile_list_panel.selected_index()
        if index is None:
            return
        new_index = self.model.move_tile_rect_down(index)
        self.selected_canvas_tile_index = new_index
        self.selected_preview_kind = "tile"
        self.selected_preview_tile = (new_index + 1) if new_index < self.model.rendered_slot_count() else None
        self._refresh_tile_rows()
        self.tile_list_panel.select_index(new_index)
        self.refresh_preview()
        self.refresh_inspector()
        self.status_var.set(f"Moved Tile {index + 1} to position {new_index + 1}. Tile order now controls tile z.")

    def on_inspector_tile_layout_change(self, x: int, y: int, w: int, h: int, name: str) -> None:
        if self.selected_preview_kind != "tile" or self.selected_canvas_tile_index is None:
            return
        tile_idx = self.selected_canvas_tile_index
        if tile_idx < 0:
            return
        self.model.update_tile_rect(tile_idx, x, y, w, h)
        self.model.set_tile_name(tile_idx, name)
        self._refresh_tile_rows()
        self.refresh_preview()
        self.refresh_inspector()
        self.status_var.set(f"Tile {tile_idx + 1} layout updated.")

    def on_inspector_tile_delete(self) -> None:
        if self.selected_preview_kind != "tile" or self.selected_canvas_tile_index is None:
            return
        tile_idx = self.selected_canvas_tile_index
        if self.model.remove_tile_rect(tile_idx) is None:
            return
        if self.model.get_tile_rects_copy():
            next_idx = min(tile_idx, len(self.model.get_tile_rects_copy()) - 1)
            self.selected_canvas_tile_index = next_idx
            self.selected_preview_tile = (next_idx + 1) if next_idx < self.model.rendered_slot_count() else None
            self.selected_preview_kind = "tile"
            self._select_tile_list_index(next_idx)
            msg = f"Deleted Tile {tile_idx + 1}. Selected Tile {next_idx + 1}."
        else:
            self.selected_canvas_tile_index = None
            self.selected_preview_tile = None
            self.selected_preview_kind = None
            msg = f"Deleted Tile {tile_idx + 1}."
        self.refresh_ui(
            select_video_index=self.video_list_panel.selected_index(),
            select_text_index=self.text_list_panel.selected_index(),
        )
        self.status_var.set(msg)

    def _refresh_tile_rows(self) -> None:
        if not hasattr(self, "tile_list_panel"):
            return
        selected_index = self.tile_list_panel.selected_index()
        prev = (
            self.selected_canvas_tile_index
            if self.selected_canvas_tile_index is not None
            else (selected_index if selected_index is not None else 0)
        )
        names = self.model.get_tile_names_copy()
        rows = []
        for i, _ in enumerate(self.model.get_tile_rects_copy(), start=1):
            label = names[i - 1].strip() if (i - 1) < len(names) else ""
            rows.append(label or f"Tile {i}")
        self.tile_list_panel.set_rows(rows)
        if not rows:
            return
        idx = max(0, min(prev, len(rows) - 1))
        self.tile_list_panel.select_index(idx)

    def _select_tile_list_index(self, idx: int) -> None:
        if not hasattr(self, "tile_list_panel"):
            return
        self.tile_list_panel.select_index(idx)

    def _show_layers_tab(self, tab_name: str) -> None:
        if not hasattr(self, "layer_notebook"):
            return
        try:
            if tab_name == "tiles":
                self.layer_notebook.select(self.tiles_tab)
            else:
                self.layer_notebook.select(self.video_tab)
        except Exception:
            return

    @staticmethod
    def _parse_int_math(text: str) -> int:
        expr = (text or "").strip()
        if not expr:
            raise ValueError("empty expression")
        tree = ast.parse(expr, mode="eval")

        def _eval(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                val = _eval(node.operand)
                return val if isinstance(node.op, ast.UAdd) else -val
            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
            ):
                left = _eval(node.left)
                right = _eval(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right
                if isinstance(node.op, ast.FloorDiv):
                    return left // right
                return left % right
            raise ValueError("unsupported expression")

        value = _eval(tree)
        if not float(value).is_integer():
            raise ValueError("result must be integer")
        return int(value)

    def _tile_rects_from_preset(self, preset: dict[str, object]) -> list[tuple[int, int, int, int]]:
        tiles = preset.get("tiles")
        if not isinstance(tiles, list):
            return []
        rects: list[tuple[int, int, int, int]] = []
        for tile in tiles:
            if not isinstance(tile, dict):
                continue
            rects.append(
                (
                    int(tile.get("x", 0)),
                    int(tile.get("y", 0)),
                    max(1, int(tile.get("w", 1))),
                    max(1, int(tile.get("h", 1))),
                )
            )
        return rects

    def _tile_z_levels_from_preset(self, preset: dict[str, object]) -> list[int]:
        tiles = preset.get("tiles")
        if not isinstance(tiles, list):
            return []
        return [
            max(1, int(tile.get("z", idx + 1))) if isinstance(tile, dict) else (idx + 1)
            for idx, tile in enumerate(tiles)
        ]

    def _tile_names_from_preset(self, preset: dict[str, object]) -> list[str]:
        tiles = preset.get("tiles")
        if not isinstance(tiles, list):
            return []
        out: list[str] = []
        for idx, tile in enumerate(tiles):
            if isinstance(tile, dict):
                name = str(tile.get("label", "")).strip()
                out.append(name or f"Tile {idx + 1}")
            else:
                out.append(f"Tile {idx + 1}")
        return out

    def _current_tile_preset_dicts(self) -> list[dict[str, object]]:
        rects = self.model.get_tile_rects_copy()
        zs = self.model.get_tile_z_levels_copy()
        names = self.model.get_tile_names_copy()
        out: list[dict[str, int]] = []
        for i, (x, y, w, h) in enumerate(rects):
            out.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "w": int(w),
                    "h": int(h),
                    "z": int(zs[i]),
                    "label": str(names[i]).strip() or f"Tile {i + 1}",
                }
            )
        return out

    def _load_preset_tiles_into_model_preview(self, preset: dict[str, object]) -> None:
        # Preview the selected preset values in the tile list/editor without applying video/text changes yet.
        tile_rects = self._tile_rects_from_preset(preset)
        tile_z_levels = self._tile_z_levels_from_preset(preset)
        tile_names = self._tile_names_from_preset(preset)
        if len(tile_rects) >= 1:
            self.model.set_canvas_layout(
                int(preset["w"]),
                int(preset["h"]),
                tile_rects=tile_rects,
                tile_z_levels=tile_z_levels,
                tile_names=tile_names,
            )
            self.refresh_preview()

    def on_inspector_z_level_change(self, z_level: int) -> None:
        if z_level < 1:
            return
        text_index = self.text_list_panel.selected_index()
        if text_index is not None and 0 <= text_index < len(self.model.text_overlays):
            new_index = self.model.set_text_z_level(text_index, z_level)
            self.selected_text_index = new_index
            self.refresh_ui(select_text_index=new_index)
            self.status_var.set(f"Text layer moved to z={new_index + 1}.")
            return

        video_index = self.video_list_panel.selected_index()
        if video_index is not None and 0 <= video_index < len(self.model.items):
            new_index = self.model.set_video_z_level(video_index, z_level)
            self.selected_preview_tile = (
                (video_index + 1) if video_index < self.model.rendered_slot_count() else None
            )
            self.refresh_ui(select_video_index=new_index)
            self.status_var.set(
                f"Video layer z override set to {self.model.items[new_index].layer_z} (tile z inheritance disabled for this video)."
            )

    def on_inspector_video_timing_change(self, trim_start_s: str, trim_end_s: str, start_at_s: str) -> None:
        index = self._current_video_editable_index()
        if index is None:
            return
        item = self.model.items[index]
        trim_start = self._parse_video_time_user_input(trim_start_s, item.duration)
        trim_end = None if trim_end_s.strip() == "" else self._parse_video_time_user_input(trim_end_s, item.duration)
        start_at = self._parse_video_time_user_input(start_at_s, None)
        if trim_start is None or (trim_end_s.strip() and trim_end is None) or start_at is None:
            return

        item.trim_start_sec = trim_start
        item.trim_end_sec = trim_end
        item.start_at_sec = start_at
        self.refresh_preview()
        self.refresh_inspector()
        self.video_list_panel.set_rows(self._build_video_rows())
        self.video_list_panel.select_index(index)
        self.status_var.set("Video timing updated.")

    def on_inspector_position_change(self, x: int, y: int) -> None:
        index = self._current_video_editable_index()
        if index is None:
            return
        item = self.model.items[index]
        item.pos_x = x
        item.pos_y = y
        item.custom_position = True
        self.refresh_preview()
        self.refresh_inspector()

    def on_inspector_reset_position(self) -> None:
        index = self._current_video_editable_index()
        if index is None:
            return
        self.model.items[index].custom_position = False
        self.refresh_preview()
        self.refresh_inspector()

    def on_inspector_include_in_mix_change(self, enabled: bool) -> None:
        index = self._current_video_editable_index()
        if index is None:
            return
        self.model.items[index].include_in_mix = enabled
        self.refresh_inspector()

    def on_inspector_text_overlay_change(self, settings: TextOverlaySettings) -> None:
        index = self._current_text_index()
        if index is None:
            return
        self.model.text_overlays[index] = settings
        self.refresh_preview()
        self.refresh_inspector()
        self.text_list_panel.set_rows(self._build_text_rows())
        self.text_list_panel.select_index(index)
        self.status_var.set("Text layer updated.")

    @staticmethod
    def _parse_video_time_user_input(value: str, video_duration: float | None) -> float | None:
        parsed = parse_timecode(value)
        if parsed is None:
            return None
        text = value.strip()
        if text.count(":") == 2:
            parts = text.split(":")
            if all(part.isdigit() for part in parts):
                a, b, c = (int(parts[0]), int(parts[1]), int(parts[2]))
                alt = (a * 60) + b + (c / 100.0)
                if video_duration is not None and parsed > (video_duration + 0.001) and alt <= (video_duration + 0.001):
                    return alt
        return parsed

    def _current_video_editable_index(self) -> int | None:
        index = self.video_list_panel.selected_index()
        if index is None and self.selected_preview_tile is not None:
            index = self.selected_preview_tile - 1
        if index is None or index < 0 or index >= len(self.model.items) or index >= self.model.rendered_slot_count():
            return None
        return index

    def _current_text_index(self) -> int | None:
        index = self.text_list_panel.selected_index()
        if index is None:
            return self.selected_text_index
        if index < 0 or index >= len(self.model.text_overlays):
            return None
        return index

    def _finish_render_success(self, output_path: str) -> None:
        self.is_rendering = False
        self.debug_enabled_for_run = False
        self._update_render_state()
        self.status_var.set(f"Done: {output_path}")
        if messagebox.askyesno("Done", f"Render complete:\n{output_path}\n\nOpen the video now?"):
            self._open_output_video(output_path)

    def _finish_render_error(self, title: str, message: str) -> None:
        self.is_rendering = False
        self.debug_enabled_for_run = False
        self._update_render_state()
        self.status_var.set("Render failed.")
        messagebox.showerror(title, message)

    def _open_output_video(self, output_path: str) -> None:
        try:
            if os.name == "nt":
                os.startfile(output_path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", output_path])
        except Exception as exc:
            messagebox.showwarning("Open Failed", f"Could not open video:\n{exc}")
