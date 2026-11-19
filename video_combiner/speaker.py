"""Plays sound files through the computer's speakers, with whatever this system offers for it."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

try:
    import winsound
except ImportError:  # Not Windows.
    winsound = None  # type: ignore[assignment]

# Command-line players found on other systems, tried in this order.
_PLAYERS = (
    ["afplay"],
    ["paplay"],
    ["aplay", "-q"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
)


def available() -> bool:
    """Whether this system has a way to play sound at all."""
    return winsound is not None or _player() is not None


def play(wav_path: str) -> Callable[[], None]:
    """Start playing a WAV file and return at once; call the returned function to silence it.

    Where no sound can be played this does nothing, and so does the function
    returned. The file must stay in place until playing has stopped.
    """
    if winsound is not None:
        try:
            winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except RuntimeError:
            return lambda: None
        return lambda: winsound.PlaySound(None, winsound.SND_PURGE)
    player = _player()
    if player is None:
        return lambda: None
    try:
        process = subprocess.Popen(
            [*player, wav_path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError:
        return lambda: None

    def silence() -> None:
        if process.poll() is None:
            process.terminate()

    return silence


def _player() -> list[str] | None:
    return next((player for player in _PLAYERS if shutil.which(player[0])), None)
