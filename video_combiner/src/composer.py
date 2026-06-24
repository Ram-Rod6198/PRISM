from __future__ import annotations

from video_combiner.src.model import TextOverlaySettings, VideoItem, VideoListModel
from video_combiner.src.utils import ff_time


class FFmpegComposer:
    def build_command(
        self,
        items_by_slots: list[VideoItem | None],
        output_path: str,
        audio_mode: str,
        fps: float,
        max_duration: float,
        tile_positions: list[tuple[int, int]] | None = None,
        tile_rects: list[tuple[int, int, int, int]] | None = None,
        video_z_levels: list[int] | None = None,
        text_overlays: list[TextOverlaySettings] | None = None,
        canvas_size: tuple[int, int] = (3840, 2160),
    ) -> list[str]:
        if len(items_by_slots) < 1:
            raise ValueError("Expected at least 1 tile slot")
        if max_duration <= 0:
            raise ValueError("No videos selected")

        fps = fps if fps and fps > 0 else 30.0
        fps_s = ff_time(fps)
        max_d = ff_time(max_duration)
        canvas_w = max(2, int(canvas_size[0]))
        canvas_h = max(2, int(canvas_size[1]))
        default_tile_w = max(1, canvas_w // 2)
        default_tile_h = max(1, canvas_h // 2)
        if tile_rects is not None and len(tile_rects) >= len(items_by_slots):
            rects = [
                (int(r[0]), int(r[1]), max(1, int(r[2])), max(1, int(r[3])))
                for r in tile_rects[: len(items_by_slots)]
            ]
        else:
            positions = (
                tile_positions
                if tile_positions is not None and len(tile_positions) >= len(items_by_slots)
                else [(0, 0), (default_tile_w, 0), (0, default_tile_h), (default_tile_w, default_tile_h)]
            )
            rects = [(int(x), int(y), default_tile_w, default_tile_h) for (x, y) in positions[: len(items_by_slots)]]

        tile_input_idx: dict[int, int] = {}
        input_args: list[str] = []
        next_input = 0
        for tile_idx, item in enumerate(items_by_slots, start=1):
            if item is None:
                continue
            tile_input_idx[tile_idx] = next_input
            input_args.extend(["-i", item.path])
            next_input += 1

        filter_parts: list[str] = [f"color=c=black:s={canvas_w}x{canvas_h}:r={fps_s}:d={max_d}[base]"]
        for tile_idx, item in enumerate(items_by_slots, start=1):
            out_label = f"v{tile_idx}"
            _x, _y, tile_w, tile_h = rects[tile_idx - 1]
            if item is None:
                filter_parts.append(
                    f"color=c=black:s={tile_w}x{tile_h}:r={fps_s}:d={max_d}[{out_label}]"
                )
                continue

            in_idx = tile_input_idx[tile_idx]
            scaled = f"v{tile_idx}_scaled"
            filter_parts.append(
                f"[{in_idx}:v]"
                f"scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,"
                f"crop={tile_w}:{tile_h},setsar=1"
                f"[{scaled}]"
            )

            trim_start, trim_end, delay_start, visible_dur, post_pad = self._video_timing_parts(
                item, max_duration
            )
            if visible_dur <= 0:
                filter_parts.append(
                    f"color=c=black:s={tile_w}x{tile_h}:r={fps_s}:d={max_d}[{out_label}]"
                )
                continue

            filter_parts.append(
                f"[{scaled}]trim=start={ff_time(trim_start)}:duration={ff_time(visible_dur)},"
                f"setpts=PTS-STARTPTS,"
                f"tpad=start_duration={ff_time(delay_start)}:stop_duration={ff_time(post_pad)}:stop_mode=add,"
                f"trim=duration={max_d},setpts=PTS-STARTPTS[{out_label}]"
            )

        current_canvas = "base"
        slot_count = len(items_by_slots)
        overlay_order = sorted(
            range(1, slot_count + 1),
            key=lambda t: (
                0 if items_by_slots[t - 1] is None else 1,
                (
                    (video_z_levels[t - 1] if video_z_levels and len(video_z_levels) >= slot_count else t)
                    if items_by_slots[t - 1] is not None
                    else -10_000
                ),
                t,
            ),
        )
        for order_idx, tile_idx in enumerate(overlay_order, start=1):
            vx, vy, _vw, _vh = rects[tile_idx - 1]
            next_canvas = "vstacked" if order_idx == len(overlay_order) else f"canvas{order_idx}"
            filter_parts.append(
                f"[{current_canvas}][v{tile_idx}]overlay=x={int(vx)}:y={int(vy)}:eof_action=pass[{next_canvas}]"
            )
            current_canvas = next_canvas

        video_out_label = "vstacked"
        active_texts = [t for t in (text_overlays or []) if t.enabled and t.text.strip()]
        if active_texts:
            current_label = video_out_label
            for idx, overlay in enumerate(active_texts):
                out_label = "vout" if idx == len(active_texts) - 1 else f"vtxt{idx + 1}"
                escaped = self._escape_drawtext(overlay.text)
                tx = int(overlay.x)
                ty = int(overlay.y)
                size = max(1, int(overlay.size))
                color = (overlay.color or "white").replace(":", "\\:")
                enable_expr = self._drawtext_enable_expr(overlay)
                enable_part = f":enable='{enable_expr}'" if enable_expr else ""
                filter_parts.append(
                    f"[{current_label}]drawtext=text='{escaped}':x={tx}:y={ty}:"
                    f"fontsize={size}:fontcolor={color}{enable_part}[{out_label}]"
                )
                current_label = out_label
        else:
            filter_parts.append(f"[{video_out_label}]format=yuv420p[vout]")

        audio_label = self._append_audio_filter(
            filter_parts=filter_parts,
            items_by_slots=items_by_slots,
            tile_input_idx=tile_input_idx,
            audio_mode=audio_mode,
            max_duration=max_duration,
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            *input_args,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
        ]

        if audio_label:
            cmd.extend(["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.append("-an")

        cmd.extend(
            [
                "-r",
                fps_s,
                "-t",
                max_d,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                "-preset",
                "veryfast",
                "-movflags",
                "+faststart",
                output_path,
            ]
        )
        return cmd

    def _append_audio_filter(
        self,
        filter_parts: list[str],
        items_by_slots: list[VideoItem | None],
        tile_input_idx: dict[int, int],
        audio_mode: str,
        max_duration: float,
    ) -> str | None:
        max_d = ff_time(max_duration)

        def build_padded(tile_idx: int, out_label: str) -> str | None:
            if tile_idx - 1 < 0 or tile_idx - 1 >= len(items_by_slots):
                return None
            item = items_by_slots[tile_idx - 1]
            if item is None or not item.has_audio:
                return None
            if audio_mode == "mix_all" and not item.include_in_mix:
                return None
            in_idx = tile_input_idx.get(tile_idx)
            if in_idx is None:
                return None
            trim_start, _trim_end, delay_start, visible_dur, _post_pad = self._video_timing_parts(
                item, max_duration
            )
            if visible_dur <= 0:
                return None
            delay_ms = int(round(delay_start * 1000))
            filter_parts.append(
                f"[{in_idx}:a]"
                f"atrim=start={ff_time(trim_start)}:duration={ff_time(visible_dur)},"
                f"asetpts=PTS-STARTPTS,"
                f"adelay={delay_ms}:all=1,"
                f"apad,atrim=duration={max_d},asetpts=N/SR/TB[{out_label}]"
            )
            return out_label

        if audio_mode == "none":
            return None

        if audio_mode.startswith("tile_"):
            try:
                tile_idx = int(audio_mode.split("_", 1)[1])
            except (IndexError, ValueError):
                return None
            return build_padded(tile_idx, "aout")

        padded_labels: list[str] = []
        for tile_idx in range(1, len(items_by_slots) + 1):
            label = build_padded(tile_idx, f"a{tile_idx}")
            if label:
                padded_labels.append(label)

        if not padded_labels:
            return None
        if len(padded_labels) == 1:
            filter_parts.append(f"[{padded_labels[0]}]anull[aout]")
            return "aout"

        joined = "".join(f"[{label}]" for label in padded_labels)
        filter_parts.append(f"{joined}amix=inputs={len(padded_labels)}:normalize=0[aout]")
        return "aout"

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        return (
            text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", r"\'")
            .replace("[", r"\[")
            .replace("]", r"\]")
            .replace("%", r"\%")
            .replace(",", r"\,")
        )

    @staticmethod
    def _video_timing_parts(item: VideoItem, max_duration: float) -> tuple[float, float, float, float, float]:
        trim_start, trim_end = VideoListModel.video_trim_bounds(item)
        clip_len = max(0.0, trim_end - trim_start)
        delay_start = max(0.0, float(item.start_at_sec or 0.0))
        available = max(0.0, max_duration - delay_start)
        visible_dur = min(clip_len, available)
        post_pad = max(0.0, max_duration - delay_start - visible_dur)
        return trim_start, trim_end, delay_start, visible_dur, post_pad

    @staticmethod
    def _drawtext_enable_expr(overlay: TextOverlaySettings) -> str | None:
        start = max(0.0, float(overlay.start_at_sec or 0.0))
        duration = overlay.duration_sec
        if duration is not None and duration <= 0:
            return "0"
        if duration is not None:
            end = start + float(duration)
            return f"between(t\\,{ff_time(start)}\\,{ff_time(end)})"
        if start > 0:
            return f"gte(t\\,{ff_time(start)})"
        return None
