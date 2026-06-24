from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk


class _BaseListPanel(ttk.LabelFrame):
    def __init__(self, master: tk.Misc, title: str, on_select: Callable[[int | None], None]) -> None:
        super().__init__(master, text=title)
        self._on_select = on_select
        self.listbox: tk.Listbox
        self._build_listbox()

    def _build_listbox(self) -> None:
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.listbox = tk.Listbox(body, exportselection=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._handle_select)

        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=scrollbar.set)

    def _handle_select(self, _event: object) -> None:
        self._on_select(self.selected_index())

    def set_rows(self, rows: list[str]) -> None:
        self.listbox.delete(0, tk.END)
        for row in rows:
            self.listbox.insert(tk.END, row)

    def selected_index(self) -> int | None:
        selected = self.listbox.curselection()
        return int(selected[0]) if selected else None

    def select_index(self, index: int | None) -> None:
        self.listbox.selection_clear(0, tk.END)
        if index is None:
            return
        if 0 <= index < self.listbox.size():
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)

    def clear_selection(self) -> None:
        self.select_index(None)


class VideoListPanel(_BaseListPanel):
    def __init__(
        self,
        master: tk.Misc,
        on_add: Callable[[], None],
        on_remove: Callable[[], None],
        on_up: Callable[[], None],
        on_down: Callable[[], None],
        on_select: Callable[[int | None], None],
    ) -> None:
        super().__init__(master, "Videos (Tile Assignment)", on_select)
        self._build_controls(on_add, on_remove, on_up, on_down)

    def _build_controls(
        self,
        on_add: Callable[[], None],
        on_remove: Callable[[], None],
        on_up: Callable[[], None],
        on_down: Callable[[], None],
    ) -> None:
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=6, pady=(6, 6))
        ttk.Button(buttons, text="Add Video", command=on_add).pack(side="left")
        ttk.Button(buttons, text="Remove", command=on_remove).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Down", command=on_down).pack(side="right")
        ttk.Button(buttons, text="Up", command=on_up).pack(side="right", padx=(0, 6))


class TextListPanel(_BaseListPanel):
    def __init__(
        self,
        master: tk.Misc,
        on_add_text: Callable[[], None],
        on_remove: Callable[[], None],
        on_up: Callable[[], None],
        on_down: Callable[[], None],
        on_select: Callable[[int | None], None],
    ) -> None:
        super().__init__(master, "Text Layers", on_select)
        self._build_controls(on_add_text, on_remove, on_up, on_down)

    def _build_controls(
        self,
        on_add_text: Callable[[], None],
        on_remove: Callable[[], None],
        on_up: Callable[[], None],
        on_down: Callable[[], None],
    ) -> None:
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=6, pady=(6, 6))
        ttk.Button(buttons, text="Add Text", command=on_add_text).pack(side="left")
        ttk.Button(buttons, text="Remove", command=on_remove).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Down", command=on_down).pack(side="right")
        ttk.Button(buttons, text="Up", command=on_up).pack(side="right", padx=(0, 6))


class TileListPanel(_BaseListPanel):
    def __init__(
        self,
        master: tk.Misc,
        on_add_tile: Callable[[], None],
        on_remove: Callable[[], None],
        on_up: Callable[[], None],
        on_down: Callable[[], None],
        on_select: Callable[[int | None], None],
    ) -> None:
        super().__init__(master, "Tiles", on_select)
        self._build_controls(on_add_tile, on_remove, on_up, on_down)

    def _build_controls(
        self,
        on_add_tile: Callable[[], None],
        on_remove: Callable[[], None],
        on_up: Callable[[], None],
        on_down: Callable[[], None],
    ) -> None:
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=6, pady=(6, 6))
        ttk.Button(buttons, text="Add Tile", command=on_add_tile).pack(side="left")
        ttk.Button(buttons, text="Remove", command=on_remove).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Down", command=on_down).pack(side="right")
        ttk.Button(buttons, text="Up", command=on_up).pack(side="right", padx=(0, 6))
