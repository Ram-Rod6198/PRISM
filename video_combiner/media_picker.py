"""Asking the user for media files."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox

from video_combiner.ffmpeg import FFmpegError, FFmpegNotFound, MediaInfo, load_media

_VIDEO_PATTERNS = "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"
_AUDIO_PATTERNS = "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus"


def pick_media(parent: tk.Misc, title: str, need: str = "video") -> list[MediaInfo]:
    """Let the user choose files and return the usable ones, in the order chosen.

    ``need`` is "video" (files must have a picture) or "audio" (files must have
    sound; videos with sound qualify). Files that cannot be used are explained
    to the user here, so the caller only ever sees good media; the list is
    empty if the dialog was cancelled or nothing qualified.
    """
    if need == "audio":
        file_types = [("Video or audio files", f"{_VIDEO_PATTERNS} {_AUDIO_PATTERNS}"), ("All files", "*.*")]
    else:
        file_types = [("Video files", _VIDEO_PATTERNS), ("All files", "*.*")]
    paths = filedialog.askopenfilenames(parent=parent, title=title, filetypes=file_types)

    usable: list[MediaInfo] = []
    problems: list[str] = []
    for path in paths:
        try:
            media = load_media(path)
        except FFmpegNotFound as exc:
            messagebox.showerror("FFmpeg Not Found", str(exc), parent=parent)
            break
        except FFmpegError as exc:
            problems.append(f"{path}: {exc}")
            continue
        if need == "audio" and not media.has_audio:
            problems.append(f"{media.name}: has no audio")
        elif need == "video" and not media.has_video:
            problems.append(f"{media.name}: has no video")
        elif media.duration <= 0:
            problems.append(f"{media.name}: has no playable length")
        else:
            usable.append(media)
    if problems:
        messagebox.showwarning("Some files were skipped", "\n".join(problems[:20]), parent=parent)
    return usable
