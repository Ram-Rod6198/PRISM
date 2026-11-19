"""The window's status line, and the one place FFmpeg encodes are run from the UI."""

from __future__ import annotations

import atexit
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from video_combiner.ffmpeg import Encode, FFmpegError
from video_combiner.widgets import UiThread

_MAX_LOG_LINES = 5000


class ExportBar(ttk.Frame):
    """Status text, progress and Cancel for the whole window.

    A mode hands over finished FFmpeg arguments; the bar asks where to save,
    encodes in the background, shows progress, lets the user cancel and reports
    the outcome. One encode runs at a time; requests made meanwhile are ignored.
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.show_log_while_encoding = tk.BooleanVar(value=False)
        self._status = tk.StringVar(value="")
        self._progress = tk.DoubleVar(value=0.0)
        self._encode: Encode | None = None
        self._busy_listeners: list[Callable[[], None]] = []
        self._log: list[str] = []
        self._log_window: _LogWindow | None = None
        self._ui = UiThread(self)

        ttk.Label(self, textvariable=self._status, anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="FFmpeg Log", command=self.show_log).pack(side="right")
        self._cancel_button = ttk.Button(self, text="Cancel", command=self._cancel)
        self._progress_bar = ttk.Progressbar(self, variable=self._progress, maximum=1.0, length=220)

    @property
    def busy(self) -> bool:
        return self._encode is not None

    def when_busy_changes(self, listener: Callable[[], None]) -> None:
        """Call ``listener()`` whenever an encode starts or ends (e.g. to enable buttons)."""
        self._busy_listeners.append(listener)

    def set_status(self, text: str) -> None:
        self._status.set(text)

    def export(self, args: list[str], duration: float, suggested_path: Path) -> None:
        """Ask where to save (defaulting to ``suggested_path``), encode, then offer to open the file.

        ``args`` are FFmpeg arguments without program or output file; ``duration``
        is the length of the result in seconds, used to show progress.
        """
        if self.busy:
            return
        output_path = filedialog.asksaveasfilename(
            title="Save output MP4",
            initialdir=str(suggested_path.parent),
            initialfile=suggested_path.name,
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
        )
        if output_path:
            self._start(args, duration, output_path, self._offer_to_open)

    def preview(self, args: list[str], duration: float) -> None:
        """Encode to a throwaway file and open it in the system's video player."""
        if self.busy:
            return
        self._start(args, duration, _new_preview_path(), _open_in_default_app)

    def show_log(self) -> None:
        """Open (or raise) the window with the last encode's exact command and FFmpeg output."""
        if self._log_window is None or not self._log_window.winfo_exists():
            self._log_window = _LogWindow(self)
        self._log_window.show(self._log or ["Nothing has been encoded yet."])

    # --- one encode, start to finish ---------------------------------------

    def _start(self, args: list[str], duration: float, output_path: str, on_success: Callable[[str], None]) -> None:
        encode = Encode(args, output_path)
        self._encode = encode
        self._log = [encode.command_line, ""]
        self._show_progress(0.0, duration)
        self._cancel_button.pack(side="right", padx=(0, 8))
        self._progress_bar.pack(side="right", padx=(8, 8))
        self._notify_busy_changed()
        if self.show_log_while_encoding.get() or (self._log_window is not None and self._log_window.winfo_exists()):
            self.show_log()

        def work() -> None:
            error: FFmpegError | None = None
            try:
                encode.run(
                    on_line=lambda line: self._ui.call(self._append_log, line),
                    on_progress=lambda seconds: self._ui.call(self._show_progress, seconds, duration),
                )
            except FFmpegError as exc:
                error = exc
            self._ui.call(self._finish, encode, error, on_success)

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, encode: Encode, error: FFmpegError | None, on_success: Callable[[str], None]) -> None:
        self._encode = None
        self._progress_bar.pack_forget()
        self._cancel_button.pack_forget()
        self._notify_busy_changed()
        if encode.cancelled:
            self.set_status("Cancelled.")
        elif error is not None:
            self.set_status("Failed.")
            messagebox.showerror("Export Failed", f"{error}\n\nOpen FFmpeg Log for the full output.")
        else:
            self.set_status(f"Done: {encode.output_path}")
            on_success(encode.output_path)

    def _cancel(self) -> None:
        if self._encode is not None:
            self._encode.cancel()

    def _show_progress(self, seconds_done: float, duration: float) -> None:
        fraction = min(1.0, seconds_done / duration) if duration > 0 else 0.0
        self._progress.set(fraction)
        self.set_status(f"Encoding… {fraction:.0%}")

    def _append_log(self, line: str) -> None:
        if len(self._log) < _MAX_LOG_LINES:
            self._log.append(line)
            if self._log_window is not None and self._log_window.winfo_exists():
                self._log_window.append(line)

    def _notify_busy_changed(self) -> None:
        for listener in self._busy_listeners:
            listener()

    @staticmethod
    def _offer_to_open(output_path: str) -> None:
        if messagebox.askyesno("Done", f"Export complete:\n{output_path}\n\nOpen the video now?"):
            _open_in_default_app(output_path)


class _LogWindow(tk.Toplevel):
    """Shows the exact FFmpeg command (first line) followed by FFmpeg's output."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.title("FFmpeg Log")
        self.geometry("980x420")
        container = ttk.Frame(self, padding=8)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text="First line: the exact command PRISM ran (paste into a terminal to reproduce). Then FFmpeg's output.",
        ).pack(anchor="w", pady=(0, 6))

        button_row = ttk.Frame(container)
        button_row.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(button_row, text="Copy Command", command=self._copy_command).pack(side="left")
        ttk.Button(button_row, text="Close", command=self.destroy).pack(side="right")
        x_scroll = ttk.Scrollbar(container, orient="horizontal")
        x_scroll.pack(side="bottom", fill="x")
        y_scroll = ttk.Scrollbar(container, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        self._text = tk.Text(container, wrap="none", state="disabled")
        self._text.pack(side="left", fill="both", expand=True)
        self._text.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        x_scroll.configure(command=self._text.xview)
        y_scroll.configure(command=self._text.yview)
        self._command = ""

    def show(self, lines: list[str]) -> None:
        self._command = lines[0]
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", "\n".join(lines) + "\n")
        self._text.configure(state="disabled")
        self._text.see("end")
        self.lift()
        self.focus_force()

    def append(self, line: str) -> None:
        self._text.configure(state="normal")
        self._text.insert("end", line + "\n")
        self._text.configure(state="disabled")
        self._text.see("end")

    def _copy_command(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._command)


_preview_numbers = itertools.count(1)
_preview_dir: str | None = None


def _new_preview_path() -> str:
    """A fresh file name per preview: a player may still hold the previous preview open."""
    global _preview_dir
    if _preview_dir is None:
        _preview_dir = tempfile.mkdtemp(prefix="prism_preview_")
        atexit.register(shutil.rmtree, _preview_dir, ignore_errors=True)
    return str(Path(_preview_dir) / f"preview_{next(_preview_numbers)}.mp4")


def _open_in_default_app(path: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
    except OSError as exc:
        messagebox.showwarning("Open Failed", f"Could not open the video:\n{exc}")
