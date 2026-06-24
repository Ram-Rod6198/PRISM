from __future__ import annotations

import subprocess
from collections.abc import Callable

from video_combiner.src.ffmpeg_bin import resolve_tool


class FFmpegRenderer:
    def resolve_runtime_command(self, command: list[str]) -> list[str]:
        if not command:
            return command
        return [resolve_tool("ffmpeg"), *command[1:]]

    def run(self, command: list[str], on_stderr_line: Callable[[str], None] | None = None) -> int:
        command = self.resolve_runtime_command(command)
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError("ffmpeg not found (bundled binary missing and not on PATH)") from exc

        assert proc.stderr is not None
        for line in proc.stderr:
            if on_stderr_line:
                on_stderr_line(line.rstrip())
        return proc.wait()
