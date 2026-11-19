import os
import tempfile
import unittest
from unittest import mock

from video_combiner.combiner.composer import compose
from video_combiner.combiner.presets import CanvasPresetStore
from video_combiner.combiner.project import AUDIO_NONE, CombinerProject, TextOverlay, Tile, VideoItem
from video_combiner.ffmpeg import MediaInfo


def video(name: str, duration: float, has_audio: bool = True) -> VideoItem:
    return VideoItem(MediaInfo(f"/videos/{name}", duration, 30.0, 1920, 1080, has_video=True, has_audio=has_audio))


class ProjectTest(unittest.TestCase):
    def test_videos_fill_tiles_in_order(self):
        project = CombinerProject()
        project.videos += [video(f"{n}.mp4", 5) for n in range(5)]
        slots = project.slots()
        self.assertEqual(len(slots), 4)
        self.assertEqual([slot.video.media.name for slot in slots], ["0.mp4", "1.mp4", "2.mp4", "3.mp4"])
        self.assertEqual((slots[3].x, slots[3].y), (1920, 1080))

    def test_own_position_overrides_the_tile_corner(self):
        project = CombinerProject()
        project.videos.append(video("a.mp4", 5))
        project.videos[0].position = (100, 50)
        self.assertEqual((project.slots()[0].x, project.slots()[0].y), (100, 50))

    def test_duration_follows_trim_and_start(self):
        project = CombinerProject()
        project.videos += [video("a.mp4", 6), video("b.mp4", 4)]
        project.videos[0].trim_start_sec, project.videos[0].trim_end_sec = 1.0, 4.5
        project.videos[1].start_at_sec = 2.0
        self.assertEqual(project.duration, 6.0)

    def test_resizing_can_scale_the_layout(self):
        project = CombinerProject()
        project.texts.append(TextOverlay(enabled=True, text="hi", x=40, y=40))
        project.resize_canvas(1920, 1080, scale_content=True)
        self.assertEqual(project.tiles[3], Tile(960, 540, 960, 540, "Tile 4"))
        self.assertEqual((project.texts[0].x, project.texts[0].y), (20, 20))


class ComposeTest(unittest.TestCase):
    def test_nothing_to_render(self):
        with self.assertRaises(ValueError):
            compose(CombinerProject())

    def test_graph_overlays_tiles_and_mixes_audio(self):
        project = CombinerProject()
        project.videos += [video("a.mp4", 6), video("b.mp4", 4), video("silent.mp4", 5, has_audio=False)]
        project.videos[1].include_in_mix = False
        args = compose(project)
        self.assertEqual(args[:6], ["-i", "/videos/a.mp4", "-i", "/videos/b.mp4", "-i", "/videos/silent.mp4"])
        graph = args[args.index("-filter_complex") + 1].split(";")
        self.assertEqual(graph[0], "color=c=black:s=3840x2160:r=30:d=6[base]")
        # The empty fourth tile goes down first, then the videos in list order.
        self.assertEqual([part for part in graph if "overlay=" in part][0].split("]")[1], "[v4")
        self.assertTrue(graph[-1].startswith("[0:a]atrim=start=0:duration=6"))
        self.assertTrue(graph[-1].endswith("[aout]"))

    def test_single_tile_audio_and_silence(self):
        project = CombinerProject()
        project.videos += [video("a.mp4", 6), video("b.mp4", 4)]
        project.audio = 1
        self.assertIn("[1:a]atrim", compose(project)[5])
        project.audio = AUDIO_NONE
        self.assertIn("-an", compose(project))

    def test_text_is_escaped_and_timed(self):
        project = CombinerProject()
        project.videos.append(video("a.mp4", 6))
        project.texts.append(TextOverlay(enabled=True, text="50%: it's", start_at_sec=1, duration_sec=2))
        graph = compose(project)[3]
        self.assertIn(r"drawtext=text='50\%\: it\'s'", graph)
        self.assertIn(r"enable='between(t\,1\,3)'", graph)


class PresetStoreTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_saved_presets_survive_a_restart(self):
        store = CanvasPresetStore()
        builtin_count = len(store.presets)
        store.save("Wide", 5120, 1440, [Tile(0, 0, 2560, 1440, "Left"), Tile(2560, 0, 2560, 1440, "Right")])
        store.save("wide", 5120, 1440, [Tile(0, 0, 5120, 1440, "All")])  # Same name: replaces.
        reloaded = CanvasPresetStore()
        self.assertEqual(len(reloaded.presets), builtin_count + 1)
        self.assertEqual(reloaded.presets[-1].tiles, [Tile(0, 0, 5120, 1440, "All")])
        reloaded.delete(reloaded.presets[-1])
        self.assertEqual(len(CanvasPresetStore().presets), builtin_count)

    def test_builtins_are_protected(self):
        store = CanvasPresetStore()
        with self.assertRaises(ValueError):
            store.delete(store.presets[0])
        with self.assertRaises(ValueError):
            store.save(store.presets[0].name.upper(), 100, 100, [Tile(0, 0, 100, 100, "Tile 1")])


if __name__ == "__main__":
    unittest.main()
