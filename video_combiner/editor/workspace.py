"""The Edit mode: the tile page, with a timeline for every tile and playback."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from video_combiner import speaker
from video_combiner.editor.composer import compose
from video_combiner.editor.player import Player
from video_combiner.editor.timeline import AUDIO_TRACK, Clip, Timeline
from video_combiner.editor.timeline_view import TimelineView
from video_combiner.export import ExportBar
from video_combiner.ffmpeg import FFmpegError
from video_combiner.media_picker import pick_media
from video_combiner.project import AUDIO_MIX, Slot
from video_combiner.timecode import format_duration, format_timecode
from video_combiner.workspace import TileWorkspace

# Widgets that need these keys for themselves while they have the keyboard.
_TYPING_WIDGETS = ("TEntry", "Entry", "TCombobox", "Text", "TScale")
_SPACE_WIDGETS = ("TButton", "TCheckbutton")


class EditorWorkspace(TileWorkspace):
    """The Edit tab: the shared page over a Timeline, with the timeline and its controls along the bottom.

    Buttons and keys become edits here; the timeline view handles the mouse.
    Whatever changes, ``_refresh`` brings every panel back in step, and stops
    playback, which shows the timeline as it was when Play was pressed.
    """

    _project: Timeline

    def __init__(self, master: tk.Misc, export_bar: ExportBar) -> None:
        # The timeline takes room at the bottom, so the inspector gives some up (it scrolls).
        super().__init__(
            master, export_bar, Timeline(), preview_title="Preview", videos_reorder=False, inspector_height=250
        )
        self._position = tk.StringVar()
        ttk.Button(self.audio_frame, text="Add Audio", command=self._add_audio).pack(side="right", padx=(0, 8))

        toolbar = ttk.Frame(self.below)
        toolbar.pack(fill="x", pady=(10, 6))
        self._buttons: dict[str, ttk.Button] = {}
        for name, command, side, gap in (
            ("Play", self._toggle_play, "left", 0),
            ("Split", self._split, "left", 18),
            ("Delete", self._delete, "left", 6),
            ("Close Gaps", self._close_gaps, "left", 6),
            ("Undo", self._undo, "left", 18),
            ("Redo", self._redo, "left", 6),
            ("Fit", lambda: self._view.zoom_to_fit(), "right", 0),
            ("Zoom +", lambda: self._view.zoom(1.25), "right", 6),
            ("Zoom -", lambda: self._view.zoom(0.8), "right", 6),
        ):
            # Kept out of the keyboard's way, so Space always means play / pause.
            self._buttons[name] = ttk.Button(toolbar, text=name, command=command, takefocus=False)
            self._buttons[name].pack(side=side, padx=(gap, 0) if side == "left" else (0, gap))
        ttk.Label(toolbar, textvariable=self._position, font=("Consolas", 11)).pack(side="left", padx=(18, 0))
        ttk.Label(
            toolbar, foreground="#555555", text="Space plays. Drag a clip to move it, its ends to trim."
        ).pack(side="left", padx=(18, 0))

        self._view = TimelineView(self.below, self._project, on_select=self._select_clip, on_change=self._refresh)
        self._view.pack(fill="x")
        self._player = Player(
            self, show_picture=self._preview.show_playing, on_progress=self._show_progress, on_stop=self._after_playing
        )

        for key, action in (
            ("<space>", self._toggle_play),
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
            ("<Home>", lambda: self._go_to(0.0)),
            ("<End>", lambda: self._go_to(self._project.duration)),
        ):
            self.bind_all(key, lambda event, action=action: self._handle_key(event, action), add="+")
        # Leaving the tab (or closing the window) must not leave sound playing.
        self.bind("<Unmap>", lambda _e: self._player.stop())
        self.bind("<Destroy>", lambda _e: self._player.stop())
        self._refresh()

    # --- what the shared page asks of this mode --------------------------------

    def _slots(self) -> list[Slot]:
        return self._project.slots(self._view.playhead)

    def _video_labels(self) -> list[str]:
        timeline, labels = self._project, []
        for clip in timeline.videos:
            tile = timeline.tile_of(clip)
            where = "Audio" if clip.tile is None else "not rendered" if tile is None else timeline.tiles[tile].name
            labels.append(f"{clip.media.name} ({format_duration(clip.end_sec - clip.start_at_sec)}) [{where}]")
        return labels

    def _audio_choices(self) -> list[tuple[str, str | int]]:
        *choices, no_audio = super()._audio_choices()
        return [*choices, ("Audio track only", AUDIO_TRACK), no_audio]

    def _refresh(self) -> None:
        if self._player.playing:
            self._player.stop()  # Comes back here through _after_playing.
            return
        super()._refresh()
        timeline, clip = self._project, self._selected_clip()
        self._view.refresh(clip)
        self._show_position()
        enabled = {"Play": timeline.duration > 0, "Split": bool(timeline.videos), "Delete": clip is not None}
        for name, button in self._buttons.items():
            button.state(["!disabled"] if enabled.get(name, True) else ["disabled"])

    def _after_edit(self, message: str) -> None:
        self._project.checkpoint()
        super()._after_edit(message)

    def _after_list_edit(self, kind: str, index: int | None) -> None:
        self._project.checkpoint()
        super()._after_list_edit(kind, index)

    def _selected_clip(self) -> Clip | None:
        if self._selection is None or self._selection[0] != "video":
            return None
        return self._project.videos[self._selection[1]]

    def _select_clip(self, clip: Clip | None) -> None:
        videos = self._project.videos
        self._select(None if clip is None else ("video", next(i for i, c in enumerate(videos) if c is clip)))

    def _show_position(self) -> None:
        shown = (round(self._view.playhead, 2), round(self._project.duration, 2))
        self._position.set(" / ".join(format_timecode(sec) for sec in shown))

    def _handle_key(self, event: tk.Event, action: Callable[[], object]) -> None:
        # Shortcuts belong to this tab, and must not fire while a widget needs the key itself.
        focus_class = getattr(event.widget, "winfo_class", str)()
        taken = focus_class in _TYPING_WIDGETS or (event.keysym == "space" and focus_class in _SPACE_WIDGETS)
        ctrl_with_plain_key = event.keysym in ("s", "S") and event.state & 0x4  # Tk matches <s> for Ctrl+S too.
        if self.winfo_ismapped() and not taken and not ctrl_with_plain_key:
            action()

    # --- playing ----------------------------------------------------------

    def _toggle_play(self) -> None:
        timeline = self._project
        if self._player.playing:
            self._player.stop()
            return
        if timeline.duration <= 0:
            self._export_bar.set_status("Add a video to a tile first.")
            return
        # Play pressed at the end starts over, as in any player.
        start = self._view.playhead if self._view.playhead < timeline.duration - 0.05 else 0.0
        self._view.set_playhead(start)
        self._buttons["Play"].configure(text="Pause")
        silent = "" if speaker.available() else " (no sound: this system has no audio player)"
        self._export_bar.set_status(f"Playing{silent}. Space or Pause stops.")
        self._player.play(timeline, start, self._preview.picture_size())

    def _show_progress(self, sec: float) -> None:
        self._view.set_playhead(sec)
        self._show_position()

    def _after_playing(self, error: FFmpegError | None) -> None:
        self._buttons["Play"].configure(text="Play")
        self._refresh()
        self._export_bar.set_status(f"Could not play: {error}" if error else "Paused.")

    # --- actions ----------------------------------------------------------

    def _add_videos(self) -> None:
        added = pick_media(self, "Add videos to the timeline")
        if not added:
            return
        timeline, selection = self._project, self._selection
        tile = None
        if selection is not None and selection[0] == "tile":
            tile = selection[1]  # A selected tile is where the user wants them.
        elif all(timeline.track(index) for index in range(len(timeline.tiles))):
            selected = self._selected_clip()
            tile = timeline.tile_of(selected) if selected is not None else None
        was_empty = not timeline.videos
        clips = [timeline.add_video(media, tile) for media in added]
        self._selection = ("video", len(timeline.videos) - 1)
        self._after_edit(f"Added {len(clips)} video(s). Drag them on the timeline to move or trim them.")
        if was_empty:
            self._view.zoom_to_fit()

    def _add_audio(self) -> None:
        added = pick_media(self, "Add audio (a video's sound or an audio file)", need="audio")
        if not added:
            return
        timeline = self._project
        note = ""
        if timeline.audio == AUDIO_MIX and not timeline.track(None) and timeline.heard():
            # The usual reason to add audio is to replace the videos' own sound.
            timeline.audio = AUDIO_TRACK
            note = ' Audio is now "Audio track only"; choose "Mix all" to hear the videos too.'
        start = self._view.playhead
        for media in added:
            start = timeline.add_sound(media, start).end_sec
        self._selection = ("video", len(timeline.videos) - 1)
        self._after_edit(f"Audio added at {format_timecode(round(self._view.playhead, 2))}.{note}")

    def _split(self) -> None:
        timeline, playhead = self._project, self._view.playhead
        # Prefer the selected clip when the playhead is inside it; otherwise cut whatever is under the playhead.
        under_playhead = [clip for clip in timeline.videos if clip.start_at_sec < playhead < clip.end_sec]
        selected = self._selected_clip()
        target = next((clip for clip in under_playhead if clip is selected), None) or next(iter(under_playhead), None)
        second_half = timeline.split(target, playhead) if target is not None else None
        if second_half is None:
            self._export_bar.set_status("To split, put the playhead inside a clip (not at its very edge).")
            return
        self._select_clip(second_half)
        self._after_edit(f"Split {target.media.name} at {format_timecode(round(playhead, 2))}.")

    def _delete(self) -> None:
        clip = self._selected_clip()
        if clip is None:
            return
        self._project.remove(clip)
        self._selection = None
        self._after_edit(f"Removed {clip.media.name}.")

    def _close_gaps(self) -> None:
        self._project.close_gaps()
        self._after_edit("Gaps closed: the clips in each tile now play back to back.")

    def _undo(self) -> None:
        undone = self._project.undo()
        self._refresh()
        self._export_bar.set_status("Undone." if undone else "Nothing to undo.")

    def _redo(self) -> None:
        redone = self._project.redo()
        self._refresh()
        self._export_bar.set_status("Redone." if redone else "Nothing to redo.")

    def _step(self, direction: int, unit: str) -> None:
        self._go_to(self._view.playhead + direction * (1.0 if unit == "second" else 1.0 / self._project.fps))

    def _go_to(self, sec: float) -> None:
        self._player.stop()
        self._view.set_playhead(sec)
        self._refresh()

    def _render(self) -> None:
        timeline = self._project
        try:
            args = compose(timeline)
        except ValueError as exc:
            messagebox.showerror("Render", str(exc))
            return
        first = Path(timeline.videos[0].media.path)
        self._export_bar.export(args, timeline.duration, first.with_name(f"{first.stem}_edit.mp4"))
