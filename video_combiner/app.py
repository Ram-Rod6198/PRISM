"""PRISM's window: one tab per mode, above a shared status and export bar."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from video_combiner.combiner.workspace import CombinerWorkspace
from video_combiner.export import ExportBar


def create_window() -> tk.Tk:
    """Build the PRISM window, ready for ``mainloop()``."""
    root = tk.Tk()
    root.title("PRISM")
    root.geometry("1520x860")
    root.minsize(1320, 780)

    export_bar = ExportBar(root)
    export_bar.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
    modes = ttk.Notebook(root)
    modes.pack(fill="both", expand=True)
    modes.add(CombinerWorkspace(modes, export_bar), text="  Combine (tiles)  ")
    export_bar.set_status("Add videos to begin.")

    menu_bar = tk.Menu(root)
    options = tk.Menu(menu_bar, tearoff=False)
    options.add_checkbutton(label="Show FFmpeg log while encoding", variable=export_bar.show_log_while_encoding)
    menu_bar.add_cascade(label="Options", menu=options)
    root.configure(menu=menu_bar)
    return root


def main() -> None:
    """Run PRISM until its window is closed."""
    create_window().mainloop()


if __name__ == "__main__":
    main()
