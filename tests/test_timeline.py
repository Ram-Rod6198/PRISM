import unittest

from video_combiner.editor.composer import compose
from video_combiner.editor.timeline import MIN_CLIP_SEC, Timeline
from video_combiner.ffmpeg import MediaInfo


def media(name: str, duration: float, has_audio: bool = True, size=(1920, 1080)) -> MediaInfo:
    return MediaInfo(f"/videos/{name}", duration, 30.0, size[0], size[1], has_video=True, has_audio=has_audio)


class VideoTrackTest(unittest.TestCase):
    def setUp(self):
        self.timeline = Timeline()
        self.a = self.timeline.add_video(media("a.mp4", 6))
        self.b = self.timeline.add_video(media("b.mp4", 4))

    def test_clips_play_back_to_back(self):
        self.assertEqual((self.a.start_sec, self.b.start_sec, self.timeline.duration), (0, 6, 10))

    def test_trimming_closes_the_gap(self):
        self.timeline.trim(self.a, in_sec=1, out_sec=3)
        self.assertEqual((self.a.duration, self.b.start_sec, self.timeline.duration), (2, 2, 6))

    def test_trim_stays_within_the_file_and_keeps_a_minimum_length(self):
        self.timeline.trim(self.a, in_sec=-5, out_sec=99)
        self.assertEqual((self.a.in_sec, self.a.out_sec), (0, 6))
        self.timeline.trim(self.a, in_sec=99)
        self.assertAlmostEqual(self.a.duration, MIN_CLIP_SEC)

    def test_reorder(self):
        self.timeline.reorder(self.b, 0)
        self.assertEqual(self.timeline.video, [self.b, self.a])
        self.assertEqual((self.b.start_sec, self.a.start_sec), (0, 4))

    def test_split_and_remove(self):
        second_half = self.timeline.split(self.a, 2.5)
        self.assertEqual((self.a.out_sec, second_half.in_sec, second_half.start_sec), (2.5, 2.5, 2.5))
        self.assertEqual(self.timeline.duration, 10)
        self.assertIsNone(self.timeline.split(self.a, 2.5))  # Now an edge, not inside.
        self.timeline.remove(second_half)
        self.assertEqual((self.b.start_sec, self.timeline.duration), (2.5, 6.5))

    def test_frame_at(self):
        self.timeline.trim(self.b, in_sec=1)
        self.assertEqual(self.timeline.frame_at(7.0), (self.b.media, 2.0))
        self.assertEqual(self.timeline.frame_at(9.0)[0], self.b.media)  # The very end shows the last frame.
        self.assertIsNone(self.timeline.frame_at(20.0))


class AudioTrackTest(unittest.TestCase):
    def setUp(self):
        self.timeline = Timeline()
        self.timeline.add_video(media("a.mp4", 6))
        self.music = self.timeline.add_audio(media("music.mp4", 20), start_sec=2)

    def test_trimming_the_start_keeps_the_rest_in_place(self):
        self.timeline.trim(self.music, in_sec=3)
        self.assertEqual((self.music.start_sec, self.music.in_sec, self.music.end_sec), (5, 3, 22))
        self.timeline.trim(self.music, in_sec=-10)  # Can grow back only until it reaches the timeline's start.
        self.assertEqual((self.music.start_sec, self.music.in_sec), (2, 0))

    def test_slide_and_extent(self):
        self.timeline.slide(self.music, -4)
        self.assertEqual(self.music.start_sec, 0)
        self.assertEqual((self.timeline.duration, self.timeline.extent), (6, 20))


class UndoTest(unittest.TestCase):
    def test_undo_and_redo_a_step(self):
        timeline = Timeline()
        clip = timeline.add_video(media("a.mp4", 6))
        timeline.checkpoint()
        timeline.trim(clip, out_sec=2)
        self.assertTrue(timeline.undo())
        self.assertEqual(timeline.duration, 6)
        self.assertTrue(timeline.redo())
        self.assertEqual(timeline.duration, 2)
        self.assertFalse(timeline.redo())

    def test_checkpoint_without_change_is_not_a_step(self):
        timeline = Timeline()
        timeline.checkpoint()
        timeline.add_video(media("a.mp4", 6))
        timeline.checkpoint()
        timeline.checkpoint()
        self.assertTrue(timeline.undo())
        self.assertEqual(timeline.video, [])
        self.assertFalse(timeline.undo())

    def test_editing_after_undo_discards_redo(self):
        timeline = Timeline()
        timeline.checkpoint()
        clip = timeline.add_video(media("a.mp4", 6))
        timeline.undo()
        timeline.checkpoint()  # Harmless on its own...
        self.assertTrue(timeline.redo())
        timeline.undo()
        timeline.add_video(media("b.mp4", 4))  # ...but a real edit ends the redo history.
        self.assertFalse(timeline.redo())
        self.assertEqual([c.media.name for c in timeline.video], ["b.mp4"])
        self.assertIsNot(timeline.video[0], clip)


class ComposeTest(unittest.TestCase):
    def test_refuses_an_empty_timeline(self):
        with self.assertRaises(ValueError):
            compose(Timeline())

    def test_inputs_are_trimmed_and_audio_is_placed(self):
        timeline = Timeline()
        clip = timeline.add_video(media("a.mp4", 6))
        timeline.add_video(media("silent.mp4", 4, has_audio=False))
        timeline.trim(clip, in_sec=1, out_sec=3)
        timeline.add_audio(media("music.mp4", 20), start_sec=1.5)
        args = compose(timeline)
        self.assertEqual(args[:6], ["-ss", "1", "-t", "2", "-i", "/videos/a.mp4"])
        self.assertEqual(args[12:19], ["-ss", "0", "-t", "20", "-vn", "-i", "/videos/music.mp4"])
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("[v0][v1]concat=n=2:v=1:a=0[vout]", graph)
        self.assertIn("[2:a]", graph)
        self.assertIn("adelay=1500:all=1", graph)
        self.assertIn("amix=inputs=2", graph)
        self.assertEqual(args[args.index("-t", 19) + 1], "6")

    def test_muting_and_frame_size(self):
        timeline = Timeline()
        timeline.add_video(media("a.mp4", 6, size=(1921, 1081)))
        timeline.video_muted = True
        args = compose(timeline)
        self.assertIn("-an", args)
        self.assertIn("scale=1920:1080:", args[args.index("-filter_complex") + 1])
        draft = compose(timeline, draft=True)
        self.assertIn("scale=640:360:", draft[draft.index("-filter_complex") + 1])


if __name__ == "__main__":
    unittest.main()
