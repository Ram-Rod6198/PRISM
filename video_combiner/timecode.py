"""Reading and writing the times users type and see (HH:MM:SS, MM:SS or plain seconds)."""

from __future__ import annotations


def parse_timecode(text: str | None, limit: float | None = None) -> float | None:
    """Seconds for "90", "1:30" or "00:01:30.5"; None when the text is empty or not a time.

    With ``limit`` (typically a clip's length), three all-digit fields that read
    past the limit as HH:MM:SS are read as MM:SS:hundredths when that fits, so
    "00:05:50" on a ten-second clip means 5.5 seconds.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    parts = [part.strip() for part in cleaned.split(":")]
    if len(parts) > 3:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    hours, minutes, seconds = [0.0] * (3 - len(numbers)) + numbers
    total = max(0.0, hours * 3600 + minutes * 60 + seconds)

    if limit is not None and len(parts) == 3 and all(part.isdigit() for part in parts):
        as_hundredths = hours * 60 + minutes + seconds / 100.0
        if total > limit + 0.001 and as_hundredths <= limit + 0.001:
            return as_hundredths
    return total


def format_timecode(seconds: float | None) -> str:
    """HH:MM:SS, with up to three decimals when the time is not whole seconds; "" for None."""
    if seconds is None:
        return ""
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    rest = total - hours * 3600 - minutes * 60
    if abs(rest - round(rest)) < 1e-6:
        return f"{hours:02d}:{minutes:02d}:{int(round(rest)):02d}"
    return f"{hours:02d}:{minutes:02d}:{rest:06.3f}".rstrip("0").rstrip(".")


def format_duration(seconds: float) -> str:
    """A compact length for list rows: "4.20s" or "2:05.00"."""
    if seconds <= 0:
        return "0.00s"
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes}:{rest:05.2f}" if minutes else f"{rest:.2f}s"
