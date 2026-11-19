"""The Combine mode: several videos tiled on one canvas."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from video_combiner.combiner.canvas_bar import CanvasBar
from video_combiner.combiner.composer import compose
from video_combiner.combiner.inspector import Inspector
from video_combiner.combiner.preview import PreviewPane
from video_combiner.combiner.project import AUDIO_MIX, AUDIO_NONE, CombinerProject, Selection, TextOverlay, VideoItem
from video_combiner.export import ExportBar
from video_combiner.media_picker import pick_media
from video_combiner.timecode import format_duration
from video_combiner.widgets import LayerListPanel, ScrollableFrame

_RENDERS_DIR = Path(__file__).resolve().parents[1] / "tmp" / "renders"


class CombinerWorkspace(ttk.Frame):
    """The whole Combine tab: preview and canvas controls on the left, layers and render on the right.

    It owns the project and the current selection, and keeps every panel in
    step with them; the panels do the editing.
    """

    def __init__(self, master: tk.Misc, export_bar: ExportBar) -> None:
        super().__init__(master, padding=10)
        self._export_bar = export_bar
        self._project = CombinerProject()
        self._selection: Selection = None

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        self._preview = PreviewPane(left, self._project, on_select=self._select, on_move=self._refresh)
        self._preview.pack(fill="both", expand=True)
        CanvasBar(left, self._project, on_change=self._after_edit).pack(fill="x", pady=(10, 0))

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        inspector_area = ScrollableFrame(right, height=360)
        inspector_area.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._inspector = Inspector(inspector_area.body, self._project, on_change=self._after_edit)
        self._inspector.grid(row=0, column=0, sticky="nsew")

        lists = ttk.Frame(right)
        lists.grid(row=1, column=0, sticky="nsew")
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        lists.rowconfigure(0, weight=1)
        self._tabs = ttk.Notebook(lists)
        self._tabs.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._lists = {
            "video": LayerListPanel(
                self._tabs,
                "Videos (Tile Assignment)",
                "Add Video",
                items=lambda: self._project.videos,
                on_add=self._add_videos,
                on_select=lambda index: self._select(("video", index)),
                on_edit=lambda index: self._after_list_edit("video", index),
            ),
            "tile": LayerListPanel(
                self._tabs,
                "Tiles",
                "Add Tile",
                items=lambda: self._project.tiles,
                on_add=self._add_tile,
                on_select=lambda index: self._select(("tile", index)),
                on_edit=lambda index: self._after_list_edit("tile", index),
            ),
            "text": LayerListPanel(
                lists,
                "Text Layers",
                "Add Text",
                items=lambda: self._project.texts,
                on_add=self._add_text,
                on_select=lambda index: self._select(("text", index)),
                on_edit=lambda index: self._after_list_edit("text", index),
            ),
        }
        self._tabs.add(self._lists["video"], text="Videos")
        self._tabs.add(self._lists["tile"], text="Tiles")
        self._lists["text"].grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        audio_frame = ttk.LabelFrame(right, text="Audio")
        audio_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self._audio_choice = ttk.Combobox(audio_frame, state="readonly")
        self._audio_choice.pack(fill="x", padx=8, pady=8)
        self._audio_choice.bind("<<ComboboxSelected>>", self._handle_audio_choice)

        self._render_button = ttk.Button(right, text="Render MP4", command=self._render)
        self._render_button.grid(row=3, column=0, sticky="w", pady=(8, 0))
        export_bar.when_busy_changes(self._enable_render_button)

        self._refresh()

    # --- keeping the panels in step with the project ---------------------------

    def _select(self, selection: Selection) -> None:
        self._selection = selection
        if selection is not None and selection[0] != "text":
            self._tabs.select(self._lists[selection[0]])
        self._refresh()

    def _refresh(self) -> None:
        """Redraw every panel from the project and the current selection."""
        project = self._project
        layers = {"video": project.videos, "tile": project.tiles, "text": project.texts}
        if self._selection is not None and self._selection[1] >= len(layers[self._selection[0]]):
            self._selection = None

        rendered = len(project.tiles)
        labels = {
            "video": [
                f"{video.media.name} ({format_duration(video.end_sec)})"
                + ("" if index < rendered else " [not rendered]")
                for index, video in enumerate(project.videos)
            ],
            "tile": [tile.name for tile in project.tiles],
            "text": [text.text.strip()[:28] or f"Text {number}" for number, text in enumerate(project.texts, start=1)],
        }
        for kind, panel in self._lists.items():
            selected = self._selection[1] if self._selection is not None and self._selection[0] == kind else None
            panel.show(labels[kind], selected)

        if isinstance(project.audio, int) and project.audio >= len(project.tiles):
            project.audio = AUDIO_MIX
        self._audio_choice.configure(values=["Mix all", *(f"{tile.name} only" for tile in project.tiles), "No audio"])
        if project.audio == AUDIO_MIX:
            self._audio_choice.current(0)
        elif project.audio == AUDIO_NONE:
            self._audio_choice.current(len(project.tiles) + 1)
        else:
            self._audio_choice.current(project.audio + 1)

        self._preview.refresh(self._selection)
        self._inspector.show(self._selection)
        self._enable_render_button()

    def _after_edit(self, message: str) -> None:
        self._refresh()
        self._export_bar.set_status(message)

    def _after_list_edit(self, kind: str, index: int | None) -> None:
        self._select((kind, index) if index is not None else None)

    def _enable_render_button(self) -> None:
        ready = bool(self._project.videos) and not self._export_bar.busy
        self._render_button.state(["!disabled"] if ready else ["disabled"])

    # --- actions -----------------------------------------------------------

    def _add_videos(self) -> None:
        added = pick_media(self, "Select one or more videos")
        if added:
            self._project.videos.extend(VideoItem(media) for media in added)
            self._select(("video", len(self._project.videos) - 1))
            self._export_bar.set_status(f"Added {len(added)} video(s).")

    def _add_tile(self) -> None:
        index = self._project.add_tile()
        self._select(("tile", index))
        self._export_bar.set_status(f"Added {self._project.tiles[index].name}. Videos fill the tiles in list order.")

    def _add_text(self) -> None:
        self._project.texts.append(TextOverlay(enabled=True, text="Your Text"))
        self._select(("text", len(self._project.texts) - 1))
        self._inspector.focus_text()
        self._export_bar.set_status("Text layer added. Edit it in the Inspector.")

    def _handle_audio_choice(self, _event: object) -> None:
        choice = self._audio_choice.current()
        if choice == 0:
            self._project.audio = AUDIO_MIX
        elif choice == len(self._project.tiles) + 1:
            self._project.audio = AUDIO_NONE
        else:
            self._project.audio = choice - 1
        self._refresh()

    def _render(self) -> None:
        try:
            args = compose(self._project)
        except ValueError as exc:
            messagebox.showerror("Render", str(exc))
            return
        _RENDERS_DIR.mkdir(parents=True, exist_ok=True)
        self._export_bar.export(args, self._project.duration, _RENDERS_DIR / "combined.mp4")
