"""End-to-end checks that really run FFmpeg; skipped when it is not installed."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_combiner.combiner import composer as combiner_composer
from video_combiner.combiner.project import CombinerProject, TextOverlay, VideoItem
from video_combiner.editor import composer as editor_composer
from video_combiner.editor.timeline import Timeline
from video_combiner.ffmpeg import Encode, FFmpegError, load_media, still_frame


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is not on PATH")
class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.bars = cls._make("bars.mp4", "smptebars=s=640x360:r=30:d=3", "sine=f=440:d=3")
        cls.silent = cls._make("silent.mp4", "color=c=red:s=320x240:r=25:d=2", None)
        cls.music = cls._make("music.mp4", "color=c=blue:s=160x120:r=10:d=6", "sine=f=880:d=6")

    @classmethod
    def _make(cls, name, picture, sound):
        path = str(Path(cls.folder.name) / name)
        command = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", picture]
        if sound:
            command += ["-f", "lavfi", "-i", sound, "-c:a", "aac", "-shortest"]
        subprocess.run([*command, "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)
        return load_media(path)

    def _out(self, name):
        return str(Path(self.folder.name) / name)

    def test_load_media_reports_streams_and_makes_a_thumbnail(self):
        self.assertEqual((self.bars.width, self.bars.height, self.bars.has_audio), (640, 360, True))
        self.assertAlmostEqual(self.bars.duration, 3.0, delta=0.1)
        self.assertFalse(self.silent.has_audio)
        self.assertTrue(Path(self.bars.thumb_path).exists())
        with self.assertRaises(FFmpegError):
            load_media(self._out("missing.mp4"))

    def test_still_frame_even_at_the_very_end(self):
        self.assertTrue(still_frame(self.bars.path, 1.0).startswith(b"\xff\xd8"))
        self.assertTrue(still_frame(self.bars.path, self.bars.duration).startswith(b"\xff\xd8"))

    def test_editor_export(self):
        timeline = Timeline()
        clip = timeline.add_video(self.bars)
        timeline.add_video(self.silent)
        timeline.trim(clip, in_sec=1.0)
        timeline.video_muted = True
        timeline.add_audio(self.music, start_sec=0.5)
        progress = []
        Encode(editor_composer.compose(timeline), self._out("edit.mp4")).run(on_progress=progress.append)
        result = load_media(self._out("edit.mp4"))
        self.assertEqual((result.width, result.height, result.has_audio), (640, 360, True))
        self.assertAlmostEqual(result.duration, 4.0, delta=0.15)
        self.assertTrue(progress)

    def test_combiner_render(self):
        project = CombinerProject()
        project.resize_canvas(640, 360, scale_content=True)
        project.videos += [VideoItem(self.bars), VideoItem(self.silent)]
        project.texts.append(TextOverlay(enabled=True, text="Hi: 100%", size=24))
        Encode(combiner_composer.compose(project), self._out("combined.mp4")).run()
        result = load_media(self._out("combined.mp4"))
        self.assertEqual((result.width, result.height, result.has_audio), (640, 360, True))
        self.assertAlmostEqual(result.duration, 3.0, delta=0.15)

    def test_failed_encode_raises_and_cancel_removes_the_file(self):
        with self.assertRaises(FFmpegError):
            Encode(["-i", self._out("missing.mp4")], self._out("never.mp4")).run()
        encode = Encode(["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=600"], self._out("cancelled.mp4"))
        encode.run(on_progress=lambda _seconds: encode.cancel())
        self.assertTrue(encode.cancelled)
        self.assertFalse(Path(encode.output_path).exists())


if __name__ == "__main__":
    unittest.main()
