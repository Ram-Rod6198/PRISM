"""Tk building blocks shared by PRISM's modes."""

from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class UiThread:
    """Lets background threads run callables on the Tk thread.

    Tk widgets may only be touched from the thread running the main loop;
    worker threads hand their UI updates to ``call`` instead.
    """

    _POLL_MS = 30

    def __init__(self, widget: tk.Misc) -> None:
        self._widget = widget
        self._pending: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._drain()

    def call(self, function: Callable[..., None], *args: object) -> None:
        """Schedule ``function(*args)`` on the Tk thread. Safe from any thread."""
        self._pending.put(lambda: function(*args))

    def _drain(self) -> None:
        while True:
            try:
                self._pending.get_nowait()()
            except queue.Empty:
                break
        try:
            self._widget.after(self._POLL_MS, self._drain)
        except tk.TclError:
            pass  # The widget is gone; nothing left to update.


class LayerListPanel(ttk.LabelFrame):
    """A titled listbox over a caller-owned list, with Add / Remove / Up / Down.

    The panel removes and reorders entries of the list itself. Creating an entry
    differs per kind of layer, so Add is delegated to ``on_add``.

    ``items`` returns the live list. ``on_select(index)`` fires when the user
    picks a row; ``on_edit(index)`` after the panel changed the list, with the
    row that should now be selected (None when the list became empty).
    """

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        add_label: str,
        items: Callable[[], list],
        on_add: Callable[[], None],
        on_select: Callable[[int], None],
        on_edit: Callable[[int | None], None],
    ) -> None:
        super().__init__(master, text=title)
        self._items = items
        self._on_select = on_select
        self._on_edit = on_edit

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._listbox = tk.Listbox(body, exportselection=False)
        self._listbox.pack(side="left", fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._handle_select)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self._listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._listbox.configure(yscrollcommand=scrollbar.set)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=6, pady=(6, 6))
        ttk.Button(buttons, text=add_label, command=on_add).pack(side="left")
        ttk.Button(buttons, text="Remove", command=self._remove).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Down", command=lambda: self._shift(+1)).pack(side="right")
        ttk.Button(buttons, text="Up", command=lambda: self._shift(-1)).pack(side="right", padx=(0, 6))

    def show(self, labels: list[str], selected: int | None) -> None:
        """Display one row per label and highlight row ``selected`` (None for no highlight)."""
        self._listbox.delete(0, tk.END)
        for label in labels:
            self._listbox.insert(tk.END, label)
        if selected is not None and 0 <= selected < len(labels):
            self._listbox.selection_set(selected)
            self._listbox.activate(selected)
            self._listbox.see(selected)

    def _selected(self) -> int | None:
        chosen = self._listbox.curselection()
        return int(chosen[0]) if chosen else None

    def _handle_select(self, _event: object) -> None:
        index = self._selected()
        if index is not None:
            self._on_select(index)

    def _remove(self) -> None:
        index, items = self._selected(), self._items()
        if index is None or index >= len(items):
            return
        del items[index]
        self._on_edit(min(index, len(items) - 1) if items else None)

    def _shift(self, step: int) -> None:
        index, items = self._selected(), self._items()
        if index is None or not 0 <= index + step < len(items):
            return
        items.insert(index + step, items.pop(index))
        self._on_edit(index + step)


class ScrollableFrame(ttk.Frame):
    """A fixed-height area whose content scrolls vertically. Put children in ``body``."""

    def __init__(self, master: tk.Misc, height: int) -> None:
        super().__init__(master, height=height)
        self.grid_propagate(False)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.body = ttk.Frame(self._canvas)
        self.body.columnconfigure(0, weight=1)
        window = self._canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(window, width=e.width))
        # The wheel event goes to whichever child is under the pointer, so listen app-wide
        # and act only when the pointer is over this frame.
        self.bind_all("<MouseWheel>", self._handle_wheel, add="+")

    def _handle_wheel(self, event: tk.Event) -> None:
        try:
            under_pointer = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        if under_pointer is not None and str(under_pointer).startswith(str(self)) and event.delta:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
