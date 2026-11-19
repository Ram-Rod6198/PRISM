"""The Combine mode: several videos tiled on one canvas, all playing at once."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from video_combiner.combiner.composer import compose
from video_combiner.combiner.project import CombinerProject
from video_combiner.export import ExportBar
from video_combiner.media_picker import pick_media
from video_combiner.project import Slot, VideoItem
from video_combiner.timecode import format_duration
from video_combiner.workspace import TileWorkspace

_RENDERS_DIR = Path(__file__).resolve().parents[1] / "tmp" / "renders"


class CombinerWorkspace(TileWorkspace):
    """The Combine tab: the shared page, over a project where the n-th video plays in the n-th tile."""

    _project: CombinerProject

    def __init__(self, master: tk.Misc, export_bar: ExportBar) -> None:
        super().__init__(master, export_bar, CombinerProject())
        self._refresh()

    def _slots(self) -> list[Slot]:
        return self._project.slots()

    def _video_labels(self) -> list[str]:
        rendered = len(self._project.tiles)
        return [
            f"{video.media.name} ({format_duration(video.end_sec)})" + ("" if index < rendered else " [not rendered]")
            for index, video in enumerate(self._project.videos)
        ]

    def _add_videos(self) -> None:
        added = pick_media(self, "Select one or more videos")
        if added:
            self._project.videos.extend(VideoItem(media) for media in added)
            self._select(("video", len(self._project.videos) - 1))
            self._export_bar.set_status(f"Added {len(added)} video(s). Videos fill the tiles in list order.")

    def _render(self) -> None:
        try:
            args = compose(self._project)
        except ValueError as exc:
            messagebox.showerror("Render", str(exc))
            return
        _RENDERS_DIR.mkdir(parents=True, exist_ok=True)
        self._export_bar.export(args, self._project.duration, _RENDERS_DIR / "combined.mp4")
