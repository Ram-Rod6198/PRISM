"""A canvas that shows single video frames, fetched in the background."""

from __future__ import annotations

import io
import threading
import tkinter as tk

from PIL import Image, ImageOps, ImageTk

from video_combiner.ffmpeg import FFmpegError, MediaInfo, still_frame
from video_combiner.widgets import UiThread

_FRAME_HEIGHT = 540
_REMEMBERED_FRAMES = 60


class FramePreview(tk.Canvas):
    """Displays the frame it was last asked for, without ever blocking the UI.

    Frames are decoded on a worker thread. When requests arrive faster than
    frames can be fetched (scrubbing), intermediate requests are dropped and
    only the newest is fetched next. Recently shown frames are remembered, so
    going back over the same spot is instant.
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, bg="#101010", highlightthickness=1, highlightbackground="#303030")
        self._ui = UiThread(self)
        self._wanted: tuple[str, float] | None = None
        self._fetching = False
        self._frames: dict[tuple[str, float], Image.Image | None] = {}
        self._image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self.bind("<Configure>", lambda _e: self._draw())

    def show(self, frame: tuple[MediaInfo, float] | None) -> None:
        """Show the frame of a media file at a time within it; None blanks the preview."""
        self._wanted = None if frame is None else (frame[0].path, round(frame[1], 3))
        self._update()

    def _update(self) -> None:
        """Display the wanted frame if it is at hand; otherwise fetch it, unless a fetch is already running."""
        if self._wanted is None or self._wanted in self._frames:
            self._image = self._frames.get(self._wanted) if self._wanted else None
            self._draw()
        elif not self._fetching:
            self._fetch(self._wanted)

    def _fetch(self, key: tuple[str, float]) -> None:
        self._fetching = True

        def work() -> None:
            try:
                image: Image.Image | None = Image.open(io.BytesIO(still_frame(*key, max_height=_FRAME_HEIGHT)))
                image.load()
            except (FFmpegError, OSError):
                image = None  # Shown as a blank frame; the next request may well succeed.
            self._ui.call(self._fetched, key, image)

        threading.Thread(target=work, daemon=True).start()

    def _fetched(self, key: tuple[str, float], image: Image.Image | None) -> None:
        self._fetching = False
        self._frames[key] = image
        while len(self._frames) > _REMEMBERED_FRAMES:
            del self._frames[next(iter(self._frames))]
        if self._wanted is not None and self._wanted != key:
            # Outdated already, but while scrubbing a recent frame beats a frozen picture.
            self._image = image
            self._draw()
        self._update()

    def _draw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if self._image is None or width < 8 or height < 8:
            return
        fitted = ImageOps.contain(self._image, (width, height))
        self._photo = ImageTk.PhotoImage(fitted)
        self.create_image(width // 2, height // 2, image=self._photo, anchor="center")
