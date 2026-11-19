"""Plays a timeline in the window, in real time."""

from __future__ import annotations

import atexit
import itertools
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from video_combiner import speaker
from video_combiner.editor.composer import Playback, compose_playback
from video_combiner.editor.timeline import Timeline
from video_combiner.ffmpeg import Encode, FFmpegError, FrameStream
from video_combiner.widgets import UiThread

_TICK_MS = 15
_FRAMES_AHEAD = 12  # Decoded pictures kept ready; more would only use memory.


class Player:
    """Shows a timeline's pictures at their proper pace and plays its sound along.

    ``show_picture(image)`` receives each frame, ``on_progress(sec)`` the
    timeline time being shown, and ``on_stop(error)`` is called once whenever
    playing ends: at the end of the timeline, on ``stop()``, or with an
    ``FFmpegError`` if playing could not go on. All three run on the Tk thread.

    When pictures cannot be decoded fast enough, frames are skipped rather than
    letting picture and sound drift apart.
    """

    def __init__(
        self,
        widget: tk.Misc,
        show_picture: Callable[[Image.Image], None],
        on_progress: Callable[[float], None],
        on_stop: Callable[[FFmpegError | None], None],
    ) -> None:
        self._widget = widget
        self._show_picture = show_picture
        self._on_progress = on_progress
        self._on_stop = on_stop
        self._ui = UiThread(widget)
        self._run: _Run | None = None

    @property
    def playing(self) -> bool:
        return self._run is not None

    def play(self, timeline: Timeline, from_sec: float, fit_within: tuple[int, int]) -> None:
        """Start playing ``timeline`` from ``from_sec``, in pictures no larger than ``fit_within``.

        Playing begins a moment later, once the sound is ready. Later changes
        to the timeline do not affect what is being played.
        """
        self.stop()
        if from_sec >= timeline.duration:
            self._on_stop(None)
            return
        run = self._run = _Run(compose_playback(timeline, from_sec, fit_within), from_sec)
        threading.Thread(target=self._decode, args=(run,), daemon=True).start()

    def stop(self) -> None:
        """Stop playing, if anything is. The position last reported stands."""
        self._end(self._run, None)

    # --- one run, start to finish --------------------------------------------

    def _decode(self, run: _Run) -> None:
        """Worker thread: prepare the sound, then keep the queue of decoded frames topped up."""
        try:
            run.prepare()
            if run.ready:
                self._ui.call(self._begin, run)
                run.feed_frames()
        except FFmpegError as exc:
            self._ui.call(self._end, run, exc)

    def _begin(self, run: _Run) -> None:
        if run is self._run:
            run.start_clock()
            self._tick(run)

    def _tick(self, run: _Run) -> None:
        if run is not self._run:
            return
        elapsed = time.perf_counter() - run.started
        frame, finished = run.frame_due(elapsed)
        if frame is not None:
            plan = run.plan
            self._show_picture(Image.frombuffer("RGB", (plan.width, plan.height), frame, "raw", "RGB", 0, 1))
        if finished or elapsed >= run.plan.duration:
            self._on_progress(run.from_sec + run.plan.duration)
            self._end(run, None)
            return
        self._on_progress(run.from_sec + elapsed)
        self._widget.after(_TICK_MS, self._tick, run)

    def _end(self, run: _Run | None, error: FFmpegError | None) -> None:
        if run is None or run is not self._run:
            return
        self._run = None
        run.close()
        self._on_stop(error)


class _Run:
    """One playback from start to stop: the decoder, the sound, and the clock that paces them."""

    def __init__(self, plan: Playback, from_sec: float) -> None:
        self.plan = plan
        self.from_sec = from_sec
        self.started = 0.0
        self._closed = False
        self._frames: queue.Queue[bytes | None] = queue.Queue(maxsize=_FRAMES_AHEAD)
        self._frames_taken = 0
        self._stream: FrameStream | None = None
        self._sound_render: Encode | None = None
        self._sound_file: str | None = None
        self._silence: Callable[[], None] = lambda: None

    def prepare(self) -> None:
        """Render the sound to a file and decode the first frame, so both can start together."""
        if self.plan.sound is not None and speaker.available():
            self._sound_render = Encode(self.plan.sound, _new_sound_path())
            if self._closed:
                return
            self._sound_render.run()
            self._sound_file = self._sound_render.output_path
        self._stream = FrameStream(self.plan.picture, self.plan.width, self.plan.height)
        if self._closed:
            self._stream.close()
        self._frames.put(self._stream.read())

    @property
    def ready(self) -> bool:
        return self._stream is not None

    def start_clock(self) -> None:
        if self._sound_file is not None:
            self._silence = speaker.play(self._sound_file)
        self.started = time.perf_counter()

    def feed_frames(self) -> None:
        """Decode until the end, waiting whenever enough frames are ready. Returns early once closed."""
        assert self._stream is not None
        frame = self._stream.read()
        while not self._closed:
            try:
                self._frames.put(frame, timeout=0.1)
            except queue.Full:
                continue
            if frame is None:
                return
            frame = self._stream.read()

    def frame_due(self, elapsed: float) -> tuple[bytes | None, bool]:
        """The newest decoded frame that should be on screen ``elapsed`` seconds in, and whether that was the last.

        None when there is nothing newer than what was returned before.
        """
        due = int(elapsed * self.plan.fps) + 1
        newest = None
        while self._frames_taken < due:
            try:
                frame = self._frames.get_nowait()
            except queue.Empty:
                break
            if frame is None:
                return newest, True
            newest = frame
            self._frames_taken += 1
        return newest, False

    def close(self) -> None:
        self._closed = True
        self._silence()
        if self._sound_render is not None:
            self._sound_render.cancel()
        if self._stream is not None:
            self._stream.close()
        if self._sound_file is not None:
            try:
                Path(self._sound_file).unlink(missing_ok=True)
            except OSError:
                pass  # Still held by the sound system; the folder is removed when PRISM exits.


_sound_numbers = itertools.count(1)
_sound_dir: str | None = None


def _new_sound_path() -> str:
    global _sound_dir
    if _sound_dir is None:
        _sound_dir = tempfile.mkdtemp(prefix="prism_playback_")
        atexit.register(shutil.rmtree, _sound_dir, ignore_errors=True)
    return str(Path(_sound_dir) / f"sound_{next(_sound_numbers)}.wav")
