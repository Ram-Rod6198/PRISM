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
    ``reorder=False`` leaves out Up / Down, for lists whose order means nothing.
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
        reorder: bool = True,
    ) -> None:
        super().__init__(master, text=title)
        self._items = items
        self._on_select = on_select
        self._on_edit = on_edit

        # The buttons are packed first, so a short panel shrinks the list rather than hiding them,
        # and kept narrow, so all of them fit in a narrow panel.
        buttons = ttk.Frame(self)
        buttons.pack(side="bottom", fill="x", padx=6, pady=(6, 6))
        ttk.Button(buttons, text=add_label, command=on_add).pack(side="left")
        ttk.Button(buttons, text="Remove", width=7, command=self._remove).pack(side="left", padx=(6, 0))
        if reorder:
            ttk.Button(buttons, text="Down", width=5, command=lambda: self._shift(+1)).pack(side="right")
            ttk.Button(buttons, text="Up", width=3, command=lambda: self._shift(-1)).pack(side="right", padx=(0, 6))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._listbox = tk.Listbox(body, exportselection=False, height=3)
        self._listbox.pack(side="left", fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._handle_select)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self._listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._listbox.configure(yscrollcommand=scrollbar.set)

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


class SplitPanes(tk.PanedWindow):
    """Panes in a row or a stack, with a bar between neighbours that the user drags to resize them.

    Every pane has a share of the room. Resizing the window resizes all panes
    by their shares, so the one given the largest share stays the largest;
    dragging a bar changes the shares of the two panes beside it.

    Create each pane's widget with this as its master, then hand it to ``add_pane``.
    """

    def __init__(self, master: tk.Misc, orient: str) -> None:
        # The classic widget, because it draws its dividers the same on every platform.
        super().__init__(
            master, orient=orient, sashwidth=6, sashrelief="flat", borderwidth=0, background="#aeb4bd"
        )
        self._size_option = "width" if orient == "horizontal" else "height"
        self._panes: list[tk.Widget] = []
        self._shares: list[float] = []
        self._laid_out_for = 0
        self.bind("<Configure>", self._share_out)
        self.bind("<ButtonRelease-1>", self._adopt_dragged_sizes, add="+")

    def add_pane(self, widget: tk.Widget, share: float = 1.0, min_size: int = 60) -> None:
        """Append ``widget`` with ``share`` parts of the room (relative to the other panes' shares)."""
        self._panes.append(widget)
        self._shares.append(share)
        self.add(widget, stretch="always", minsize=min_size)
        self._laid_out_for = 0

    def _room(self) -> int:
        """The pixels the panes have between them along the split."""
        length = self.winfo_width() if self._size_option == "width" else self.winfo_height()
        return length - int(self.cget("sashwidth")) * (len(self._panes) - 1)

    def _share_out(self, _event: object = None) -> None:
        room = self._room()
        if room == self._laid_out_for or room <= 0:
            return
        self._laid_out_for = room
        total = sum(self._shares)
        for pane, share in zip(self._panes, self._shares):
            # An explicit size also stops Tk from resizing the pane whenever its content asks for a new size.
            self.paneconfigure(pane, **{self._size_option: max(1, round(room * share / total))})

    def _adopt_dragged_sizes(self, _event: object) -> None:
        self.update_idletasks()
        sizes = [pane.winfo_width() if self._size_option == "width" else pane.winfo_height() for pane in self._panes]
        if sum(sizes) > 0:
            self._shares = [float(size) for size in sizes]
            for pane, size in zip(self._panes, sizes):
                self.paneconfigure(pane, **{self._size_option: max(1, size)})


class ScrollableFrame(ttk.Frame):
    """An area whose content scrolls vertically; it is as tall as its container makes it. Children go in ``body``."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
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
