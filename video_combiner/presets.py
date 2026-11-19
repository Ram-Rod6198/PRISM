"""Canvas presets: named canvas sizes with a tile layout, built in or saved by the user."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from video_combiner.project import Tile, grid_tiles

_FILE_NAME = "canvas_presets.user.json"
# Presets shipped with the source tree, merged in as if the user had saved them.
_SEED_FILE = Path(__file__).resolve().parent / "assets" / _FILE_NAME


@dataclass
class CanvasPreset:
    name: str
    width: int
    height: int
    tiles: list[Tile]
    builtin: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} ({self.width}x{self.height})"


class CanvasPresetStore:
    """The presets offered to the user: the built-in ones, then those saved on this machine.

    ``presets`` is the list to display. Names are unique, ignoring case.
    Saving and deleting update the list first and then the user's preset file,
    so an ``OSError`` from either means "changed for this session only".
    """

    def __init__(self) -> None:
        self.presets: list[CanvasPreset] = _builtin_presets()
        for path in (_SEED_FILE, _user_file()):
            for preset in _read_presets(path):
                if self._find(preset.name) is None:
                    self.presets.append(preset)

    def save(self, name: str, width: int, height: int, tiles: list[Tile]) -> CanvasPreset:
        """Add a preset, or replace the saved one of the same name. Built-ins cannot be replaced (ValueError)."""
        existing = self._find(name)
        if existing is not None and existing.builtin:
            raise ValueError(f'"{existing.name}" is a built-in preset. Save under a different name.')
        preset = CanvasPreset(name, width, height, [Tile(t.x, t.y, t.w, t.h, t.name) for t in tiles])
        if existing is None:
            self.presets.append(preset)
        else:
            self.presets[self.presets.index(existing)] = preset
        self._write()
        return preset

    def delete(self, preset: CanvasPreset) -> None:
        """Remove a saved preset. Built-ins cannot be deleted (ValueError)."""
        if preset.builtin:
            raise ValueError("Built-in presets cannot be deleted.")
        self.presets.remove(preset)
        self._write()

    def _find(self, name: str) -> CanvasPreset | None:
        key = name.strip().lower()
        return next((preset for preset in self.presets if preset.name.lower() == key), None)

    def _write(self) -> None:
        saved = [
            {
                "name": preset.name,
                "w": preset.width,
                "h": preset.height,
                "tiles": [
                    # "z" is written for older PRISM builds, which stored the stacking order explicitly.
                    {"x": t.x, "y": t.y, "w": t.w, "h": t.h, "z": z, "label": t.name}
                    for z, t in enumerate(preset.tiles, start=1)
                ],
            }
            for preset in self.presets
            if not preset.builtin
        ]
        path = _user_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved, indent=2), encoding="utf-8")


def _builtin_presets() -> list[CanvasPreset]:
    three_over_two = [
        # Three 1080p tiles on top, two centred below (960 px margins either side).
        Tile(0, 0, 1920, 1080, "Tile 1"),
        Tile(1920, 0, 1920, 1080, "Tile 2"),
        Tile(3840, 0, 1920, 1080, "Tile 3"),
        Tile(960, 1080, 1920, 1080, "Tile 4"),
        Tile(2880, 1080, 1920, 1080, "Tile 5"),
    ]
    return [
        CanvasPreset("2x2 for 4K", 3840, 2160, grid_tiles(3840, 2160), builtin=True),
        CanvasPreset("2x2 1080p", 1920, 1080, grid_tiles(1920, 1080), builtin=True),
        CanvasPreset("2x2 720p", 1280, 720, grid_tiles(1280, 720), builtin=True),
        CanvasPreset("3 Top + 2 Centered (1080p tiles)", 5760, 2160, three_over_two, builtin=True),
        CanvasPreset("Single tile 1080p", 1920, 1080, [Tile(0, 0, 1920, 1080, "Tile 1")], builtin=True),
    ]


def _user_file() -> Path:
    if getattr(sys, "frozen", False):
        # The portable build keeps its data next to the executable.
        return Path(sys.executable).resolve().parent / "data" / _FILE_NAME
    app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / "VideoCombiner" / _FILE_NAME
    return Path.home() / ".video_combiner" / _FILE_NAME


def _read_presets(path: Path) -> list[CanvasPreset]:
    """The valid presets in a preset file; a missing or damaged file (or entry) contributes nothing."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    presets = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            tiles = [
                Tile(
                    int(tile.get("x", 0)),
                    int(tile.get("y", 0)),
                    max(1, int(tile.get("w", 1))),
                    max(1, int(tile.get("h", 1))),
                    str(tile.get("label", "")).strip() or f"Tile {number}",
                )
                for number, tile in enumerate(entry["tiles"], start=1)
            ]
            preset = CanvasPreset(str(entry["name"]).strip(), max(2, int(entry["w"])), max(2, int(entry["h"])), tiles)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if preset.name and preset.tiles:
            presets.append(preset)
    return presets
