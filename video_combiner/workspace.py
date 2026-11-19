"""The page both modes share: preview and canvas on the left, inspector, layers, audio and render on the right."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from video_combiner.canvas_bar import CanvasBar
from video_combiner.export import ExportBar
from video_combiner.inspector import Inspector
from video_combiner.preview import PreviewPane
from video_combiner.project import AUDIO_MIX, AUDIO_NONE, Selection, Slot, TextOverlay, TileProject
from video_combiner.widgets import LayerListPanel, ScrollableFrame, SplitPanes


class TileWorkspace(ttk.Frame):
    """A mode's whole tab, built from the panels every mode has.

    It owns the selection and keeps every panel in step with it and with the
    project; the panels do the editing. A mode passes its project and fills in
    what differs: which video is in which tile (``_slots``), how videos are
    listed and added (``_video_labels``, ``_add_videos``) and how the result is
    rendered (``_render``). Anything a mode has on top goes into
    ``add_lower_pane()`` or into ``audio_frame``. The user can drag the bars
    between the panels to resize them.
    """

    def __init__(
        self,
        master: tk.Misc,
        export_bar: ExportBar,
        project: TileProject,
        preview_title: str = "Static Preview",
        videos_reorder: bool = True,
        inspector_share: float = 1.6,
    ) -> None:
        super().__init__(master, padding=10)
        self._export_bar = export_bar
        self._project = project
        self._selection: Selection = None

        self._stack = SplitPanes(self, orient="vertical")
        self._stack.pack(fill="both", expand=True)
        panes = SplitPanes(self._stack, orient="horizontal")
        self._stack.add_pane(panes, share=7, min_size=200)
        left, right = ttk.Frame(panes, padding=(0, 0, 6, 0)), ttk.Frame(panes, padding=(6, 0, 0, 0))
        # The preview's side gets the larger share of the tab, across and down.
        panes.add_pane(left, share=3, min_size=240)
        panes.add_pane(right, share=2, min_size=240)

        self._preview = PreviewPane(
            left, project, slots=self._slots, on_select=self._select, on_move=self._refresh, title=preview_title
        )
        self._canvas_bar = CanvasBar(left, project, on_change=self._after_edit)
        self._canvas_bar.pack(side="bottom", fill="x", pady=(10, 0))
        self._preview.pack(fill="both", expand=True)

        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        side = SplitPanes(right, orient="vertical")
        side.grid(row=0, column=0, sticky="nsew")
        inspector_area = ScrollableFrame(side)
        side.add_pane(inspector_area, share=inspector_share)
        self._inspector = Inspector(inspector_area.body, project, on_change=self._after_edit)
        self._inspector.grid(row=0, column=0, sticky="nsew")

        lists = ttk.Frame(side, padding=(0, 6, 0, 0))
        side.add_pane(lists, share=1, min_size=110)
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
                items=lambda: project.videos,
                on_add=self._add_videos,
                on_select=lambda index: self._select(("video", index)),
                on_edit=lambda index: self._after_list_edit("video", index),
                reorder=videos_reorder,
            ),
            "tile": LayerListPanel(
                self._tabs,
                "Tiles",
                "Add Tile",
                items=lambda: project.tiles,
                on_add=self._add_tile,
                on_select=lambda index: self._select(("tile", index)),
                on_edit=lambda index: self._after_list_edit("tile", index),
            ),
            "text": LayerListPanel(
                lists,
                "Text Layers",
                "Add Text",
                items=lambda: project.texts,
                on_add=self._add_text,
                on_select=lambda index: self._select(("text", index)),
                on_edit=lambda index: self._after_list_edit("text", index),
            ),
        }
        self._tabs.add(self._lists["video"], text="Videos")
        self._tabs.add(self._lists["tile"], text="Tiles")
        self._lists["text"].grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self.audio_frame = ttk.LabelFrame(right, text="Audio")
        self.audio_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._audio_choice = ttk.Combobox(self.audio_frame, state="readonly")
        self._audio_choice.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._audio_choice.bind("<<ComboboxSelected>>", self._handle_audio_choice)

        self._render_button = ttk.Button(right, text="Render MP4", command=self._render)
        self._render_button.grid(row=2, column=0, sticky="w", pady=(8, 0))
        export_bar.when_busy_changes(self._enable_render_button)

    def add_lower_pane(self) -> ttk.Frame:
        """A frame across the bottom of the tab, below the page, for a mode to fill.

        It takes the smaller share of the tab's height; the user changes that by dragging the bar above it.
        """
        pane = ttk.Frame(self._stack)
        self._stack.add_pane(pane, share=3, min_size=90)
        return pane

    # --- what a mode fills in ---------------------------------------------------

    def _slots(self) -> list[Slot]:
        """Each tile with the video to draw in it."""
        raise NotImplementedError

    def _video_labels(self) -> list[str]:
        """One row of the Videos list per video of the project."""
        raise NotImplementedError

    def _add_videos(self) -> None:
        """Ask for videos and add them to the project."""
        raise NotImplementedError

    def _render(self) -> None:
        """Export the project."""
        raise NotImplementedError

    def _audio_choices(self) -> list[tuple[str, str | int]]:
        """The entries of the Audio list, each with the value of ``project.audio`` it stands for."""
        tiles = [(f"{tile.name} only", index) for index, tile in enumerate(self._project.tiles)]
        return [("Mix all", AUDIO_MIX), *tiles, ("No audio", AUDIO_NONE)]

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

        labels = {
            "video": self._video_labels(),
            "tile": [tile.name for tile in project.tiles],
            "text": [text.text.strip()[:28] or f"Text {number}" for number, text in enumerate(project.texts, start=1)],
        }
        for kind, panel in self._lists.items():
            selected = self._selection[1] if self._selection is not None and self._selection[0] == kind else None
            panel.show(labels[kind], selected)

        choices = self._audio_choices()
        values = [value for _, value in choices]
        if project.audio not in values:  # The tile it named is gone.
            project.audio = AUDIO_MIX
        self._audio_choice.configure(values=[label for label, _ in choices])
        self._audio_choice.current(values.index(project.audio))

        self._preview.refresh(self._selection)
        self._inspector.show(self._selection)
        self._canvas_bar.refresh()
        self._enable_render_button()

    def _after_edit(self, message: str) -> None:
        """Called by the panels after they changed the project."""
        self._refresh()
        self._export_bar.set_status(message)

    def _after_list_edit(self, kind: str, index: int | None) -> None:
        self._select((kind, index) if index is not None else None)

    def _enable_render_button(self) -> None:
        ready = bool(self._project.videos) and not self._export_bar.busy
        self._render_button.state(["!disabled"] if ready else ["disabled"])

    # --- actions every mode has -------------------------------------------------

    def _add_tile(self) -> None:
        index = self._project.add_tile()
        self._select(("tile", index))
        self._export_bar.set_status(f"Added {self._project.tiles[index].name}.")

    def _add_text(self) -> None:
        self._project.texts.append(TextOverlay(enabled=True, text="Your Text"))
        self._select(("text", len(self._project.texts) - 1))
        self._inspector.focus_text()
        self._export_bar.set_status("Text layer added. Edit it in the Inspector.")

    def _handle_audio_choice(self, _event: object) -> None:
        self._project.audio = self._audio_choices()[self._audio_choice.current()][1]
        self._after_edit("Audio updated.")
