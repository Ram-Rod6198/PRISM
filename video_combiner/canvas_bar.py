"""Controls for a project's output canvas: layout presets and canvas size."""

from __future__ import annotations

import ast
import operator
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from video_combiner.presets import CanvasPreset, CanvasPresetStore
from video_combiner.project import TileProject


class CanvasBar(ttk.LabelFrame):
    """Applies, saves and deletes canvas presets and resizes the canvas.

    Edits go straight into the project; ``on_change(message)`` follows each one
    with a note for the status line. Width and Height accept whole numbers or
    simple arithmetic such as ``1920*2``. Call ``refresh()`` after the canvas
    was changed from elsewhere.
    """

    def __init__(self, master: tk.Misc, project: TileProject, on_change: Callable[[str], None]) -> None:
        super().__init__(master, text="Canvas Presets / Output Canvas")
        self._project = project
        self._on_change = on_change
        self._store = CanvasPresetStore()
        self._preset_name = tk.StringVar(value="My Preset")
        self._width = tk.StringVar(value=str(project.canvas_w))
        self._height = tk.StringVar(value=str(project.canvas_h))
        self._scale_content = tk.BooleanVar(value=False)

        preset_row = ttk.Frame(self)
        preset_row.pack(fill="x", padx=8, pady=(8, 6))
        ttk.Label(preset_row, text="Preset").pack(side="left")
        self._preset_list = ttk.Combobox(preset_row, state="readonly", width=34)
        self._preset_list.pack(side="left", padx=(4, 8))
        self._preset_list.bind("<<ComboboxSelected>>", lambda _e: self._apply_selected())
        ttk.Button(preset_row, text="Load Preset", command=self._apply_selected).pack(side="left")
        ttk.Button(preset_row, text="Delete", command=self._delete).pack(side="left", padx=(8, 0))

        size_row = ttk.Frame(self)
        size_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(size_row, text="Width").pack(side="left")
        ttk.Entry(size_row, textvariable=self._width, width=8).pack(side="left", padx=(4, 8))
        ttk.Label(size_row, text="Height").pack(side="left")
        ttk.Entry(size_row, textvariable=self._height, width=8).pack(side="left", padx=(4, 8))
        ttk.Checkbutton(size_row, text="Scale layout with canvas", variable=self._scale_content).pack(
            side="left", padx=(4, 8)
        )
        ttk.Button(size_row, text="Apply Canvas", command=self._apply_size).pack(side="left")

        save_row = ttk.Frame(self)
        save_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(save_row, text="Save this canvas and its tiles as").pack(side="left")
        ttk.Entry(save_row, textvariable=self._preset_name, width=24).pack(side="left", padx=(4, 8))
        ttk.Button(save_row, text="Save/Update", command=self._save).pack(side="left")
        self._shown_size = (project.canvas_w, project.canvas_h)
        self._list_presets(select=self._preset_in_use())

    def refresh(self) -> None:
        """Show the project's canvas size, if it is no longer the one on display.

        Otherwise the fields are left alone: they may hold a size the user is
        still typing.
        """
        size = (self._project.canvas_w, self._project.canvas_h)
        if size != self._shown_size:
            self._shown_size = size
            self._width.set(str(size[0]))
            self._height.set(str(size[1]))
            self._list_presets(select=self._preset_in_use())

    def _list_presets(self, select: CanvasPreset | None) -> None:
        presets = self._store.presets
        self._preset_list.configure(values=[preset.label for preset in presets])
        if select is not None:
            self._preset_list.current(presets.index(select))
        else:
            self._preset_list.set("")

    def _preset_in_use(self) -> CanvasPreset | None:
        """The preset the project's canvas and tiles currently match, if any."""
        project = self._project
        in_use = (project.canvas_w, project.canvas_h, project.tiles)
        return next((p for p in self._store.presets if (p.width, p.height, p.tiles) == in_use), None)

    def _selected(self) -> CanvasPreset | None:
        index = self._preset_list.current()
        return self._store.presets[index] if index >= 0 else None

    def _apply_selected(self) -> None:
        preset = self._selected()
        if preset is None:
            return
        self._project.set_layout(preset.width, preset.height, preset.tiles)
        self._preset_name.set(preset.name)
        self._shown_size = (preset.width, preset.height)
        self._width.set(str(preset.width))
        self._height.set(str(preset.height))
        self._on_change(f"Applied canvas preset: {preset.name}")

    def _typed_size(self) -> tuple[int, int] | None:
        """The canvas size in the Width/Height fields; None (after telling the user) if unusable."""
        try:
            width, height = _whole_number(self._width.get()), _whole_number(self._height.get())
        except ValueError:
            messagebox.showerror("Canvas Size", "Width and Height must be whole numbers or simple arithmetic.")
            return None
        if width < 2 or height < 2:
            messagebox.showerror("Canvas Size", "Width and Height must be at least 2.")
            return None
        return width, height

    def _apply_size(self) -> None:
        size = self._typed_size()
        if size is None:
            return
        self._project.resize_canvas(*size, scale_content=self._scale_content.get())
        self._shown_size = size
        self._width.set(str(size[0]))
        self._height.set(str(size[1]))
        scaled = " (layout scaled)" if self._scale_content.get() else ""
        self._on_change(f"Output canvas set to {size[0]}x{size[1]}{scaled}.")

    def _save(self) -> None:
        size = self._typed_size()
        if size is None:
            return
        name = self._preset_name.get().strip() or f"{size[0]}x{size[1]}"
        try:
            preset: CanvasPreset | None = self._store.save(name, *size, self._project.tiles)
        except ValueError as exc:
            messagebox.showinfo("Canvas Preset", str(exc))
            return
        except OSError as exc:
            messagebox.showwarning(
                "Canvas Preset", f"Saved for this session only; the preset file could not be written:\n{exc}"
            )
            preset = None
        self._preset_name.set(name)
        self._list_presets(select=preset)
        self._on_change(f"Saved canvas preset: {name}")

    def _delete(self) -> None:
        preset = self._selected()
        if preset is None:
            return
        try:
            self._store.delete(preset)
        except ValueError as exc:
            messagebox.showinfo("Canvas Preset", str(exc))
            return
        except OSError as exc:
            messagebox.showwarning(
                "Canvas Preset", f"Deleted for this session only; the preset file could not be written:\n{exc}"
            )
        self._list_presets(select=None)
        self._on_change(f"Deleted canvas preset: {preset.name}")


_ARITHMETIC = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def _whole_number(text: str) -> int:
    """The value of ``text`` as a whole number, allowing + - * / // % and parentheses.

    Raises ``ValueError`` for anything else, including results with a fraction.
    """

    def value_of(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = value_of(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC:
            return _ARITHMETIC[type(node.op)](value_of(node.left), value_of(node.right))
        raise ValueError(f"unsupported expression: {text!r}")

    try:
        result = value_of(ast.parse(text.strip(), mode="eval").body)
    except (SyntaxError, ZeroDivisionError) as exc:
        raise ValueError(f"not a number: {text!r}") from exc
    if result != int(result):
        raise ValueError(f"not a whole number: {text!r}")
    return int(result)
