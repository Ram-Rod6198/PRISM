import unittest

from video_combiner.editor.composer import compose, compose_playback
from video_combiner.editor.timeline import AUDIO_TRACK, MIN_CLIP_SEC, Timeline
from video_combiner.ffmpeg import MediaInfo
from video_combiner.project import AUDIO_MIX, TextOverlay, Tile


def media(name: str, duration: float, has_audio: bool = True, size=(1920, 1080)) -> MediaInfo:
    return MediaInfo(f"/videos/{name}", duration, 30.0, size[0], size[1], has_video=True, has_audio=has_audio)


def two_tiles(timeline: Timeline) -> None:
    timeline.set_layout(1280, 360, [Tile(0, 0, 640, 360, "Left"), Tile(640, 0, 640, 360, "Right")])


def placed(timeline: Timeline) -> list[tuple]:
    return [(clip.media.name, clip.tile, clip.start_at_sec) for clip in timeline.videos]


class OneTileTest(unittest.TestCase):
    def setUp(self):
        self.timeline = Timeline()
        self.a = self.timeline.add_video(media("a.mp4", 6))
        self.b = self.timeline.add_video(media("b.mp4", 4))

    def test_new_videos_follow_the_last_one(self):
        self.assertEqual(placed(self.timeline), [("a.mp4", 0, 0), ("b.mp4", 0, 6)])
        self.assertEqual(self.timeline.duration, 10)

    def test_first_video_sets_the_canvas(self):
        timeline = Timeline()
        timeline.add_video(media("phone.mp4", 5, size=(1081, 1921)))
        self.assertEqual((timeline.canvas_w, timeline.canvas_h), (1080, 1920))
        self.assertEqual(timeline.tiles, [Tile(0, 0, 1080, 1920, "Tile 1")])
        two_tiles(timeline)
        timeline.videos.clear()
        timeline.add_video(media("other.mp4", 5, size=(640, 480)))  # A layout the user chose is kept.
        self.assertEqual((timeline.canvas_w, timeline.canvas_h), (1280, 360))

    def test_trimming_the_start_keeps_the_rest_in_place(self):
        self.timeline.trim(self.b, trim_start_sec=1.5)
        self.assertEqual((self.b.start_at_sec, self.b.trim_start_sec, self.b.end_sec), (7.5, 1.5, 10))
        self.assertEqual(self.a.end_sec, 6)  # Nothing else moved: there is a gap now.
        self.timeline.trim(self.b, trim_start_sec=-10)  # Grows back only until it reaches its neighbour.
        self.assertEqual((self.b.start_at_sec, self.b.trim_start_sec), (6, 0))

    def test_trimming_the_end_moves_nothing_and_stops_at_the_neighbour(self):
        self.timeline.trim(self.a, trim_end_sec=2)
        self.assertEqual((self.a.end_sec, self.b.start_at_sec), (2, 6))
        self.timeline.place(self.b, 0, 3)
        self.timeline.trim(self.a, trim_end_sec=99)
        self.assertEqual(self.a.end_sec, 3)

    def test_trim_stays_within_the_file_and_keeps_a_minimum_length(self):
        self.timeline.trim(self.b, trim_start_sec=99)
        self.assertAlmostEqual(self.b.end_sec - self.b.start_at_sec, MIN_CLIP_SEC)
        self.timeline.trim(self.b, trim_end_sec=99)
        self.assertEqual(self.b.trim_end_sec, 4)

    def test_moving_leaves_a_gap_and_close_gaps_removes_it(self):
        self.timeline.place(self.b, 0, 9)
        self.assertEqual((self.b.start_at_sec, self.timeline.duration), (9, 13))
        self.assertIsNone(self.timeline.slots(7.0)[0].video)
        self.timeline.close_gaps()
        self.assertEqual((self.b.start_at_sec, self.timeline.duration), (6, 10))

    def test_dropping_onto_a_clip_goes_in_front_or_behind_and_pushes_later_clips(self):
        c = self.timeline.add_video(media("c.mp4", 2))
        self.timeline.place(c, 0, 1)  # In a's first half: in front of it.
        self.assertEqual(placed(self.timeline), [("a.mp4", 0, 2), ("b.mp4", 0, 8), ("c.mp4", 0, 0)])
        self.timeline.place(c, 0, 6)  # In a's second half: behind it.
        self.assertEqual(placed(self.timeline), [("a.mp4", 0, 2), ("b.mp4", 0, 10), ("c.mp4", 0, 8)])

    def test_split_and_remove(self):
        second_half = self.timeline.split(self.a, 2.5)
        self.assertEqual((self.a.trim_end_sec, second_half.trim_start_sec, second_half.start_at_sec), (2.5, 2.5, 2.5))
        self.assertIsNone(self.timeline.split(self.a, 2.5))  # Now an edge, not inside.
        self.timeline.remove(second_half)
        self.assertEqual(placed(self.timeline), [("a.mp4", 0, 0), ("b.mp4", 0, 6)])  # The gap stays.

    def test_slots_name_the_frame_on_screen(self):
        self.timeline.trim(self.b, trim_start_sec=1)
        slot = self.timeline.slots(8.0)[0]
        self.assertEqual((slot.video, slot.frame_sec), (self.b, 2.0))
        self.assertIs(self.timeline.slots(10.0)[0].video, self.b)  # The very end shows the last frame.
        self.assertIsNone(self.timeline.slots(6.5)[0].video)

    def test_typed_timing_follows_the_same_rules(self):
        self.timeline.set_timing(self.b, 1.0, None, 6.0)
        self.assertEqual((self.b.start_at_sec, self.b.trim_start_sec, self.b.trim_end_sec), (7, 1, 4))
        self.timeline.set_timing(self.b, 1.0, 4.0, 2.0)  # Lands in a's first half: goes in front.
        self.assertEqual((self.b.start_at_sec, self.a.start_at_sec), (0, 3))


class TilesAndAudioTest(unittest.TestCase):
    def setUp(self):
        self.timeline = Timeline()
        two_tiles(self.timeline)
        self.a = self.timeline.add_video(media("a.mp4", 6))
        self.b = self.timeline.add_video(media("b.mp4", 4))
        self.c = self.timeline.add_video(media("c.mp4", 3))

    def test_videos_fill_empty_tiles_first(self):
        self.assertEqual(placed(self.timeline), [("a.mp4", 0, 0), ("b.mp4", 1, 0), ("c.mp4", 0, 6)])
        self.assertEqual(self.timeline.add_video(media("d.mp4", 1), tile=1).start_at_sec, 4)

    def test_moving_to_another_tile_or_to_the_audio_track(self):
        self.timeline.place(self.c, 1, 2)  # Onto b's second half.
        self.assertEqual((self.c.tile, self.c.start_at_sec), (1, 4))
        self.timeline.place(self.c, None, 1)
        self.assertEqual(self.timeline.track(None), [self.c])
        self.assertIsNone(self.timeline.tile_of(self.c))
        self.assertEqual((self.timeline.duration, self.timeline.extent), (6, 6))

    def test_what_is_heard(self):
        music = self.timeline.add_sound(media("music.mp3", 20), start_sec=2)
        self.assertEqual(self.timeline.heard(), [self.a, self.b, self.c, music])
        self.b.include_in_mix = False
        self.assertEqual(self.timeline.heard(), [self.a, self.c, music])
        self.timeline.audio = AUDIO_TRACK
        self.assertEqual(self.timeline.heard(), [music])
        self.timeline.audio = 1
        self.assertEqual(self.timeline.heard(), [self.b])
        self.assertEqual((self.timeline.duration, self.timeline.extent), (9, 22))

    def test_a_clip_whose_tile_is_gone_is_not_rendered(self):
        del self.timeline.tiles[1]
        self.assertIsNone(self.timeline.tile_of(self.b))
        self.assertNotIn(self.b, self.timeline.heard())
        self.assertEqual(self.timeline.duration, 9)


class UndoTest(unittest.TestCase):
    def test_each_checkpoint_is_a_step(self):
        timeline = Timeline()
        clip = timeline.add_video(media("a.mp4", 6))
        timeline.checkpoint()
        timeline.trim(clip, trim_end_sec=2)
        timeline.audio = AUDIO_TRACK
        timeline.checkpoint()
        self.assertTrue(timeline.undo())
        self.assertEqual((timeline.duration, timeline.audio), (6, AUDIO_MIX))
        self.assertTrue(timeline.redo())
        self.assertEqual((timeline.duration, timeline.audio), (2, AUDIO_TRACK))
        self.assertFalse(timeline.redo())
        self.assertTrue(timeline.undo())
        self.assertTrue(timeline.undo())
        self.assertEqual(timeline.videos, [])
        self.assertFalse(timeline.undo())

    def test_checkpoint_without_change_is_not_a_step(self):
        timeline = Timeline()
        timeline.add_video(media("a.mp4", 6))
        timeline.checkpoint()
        timeline.checkpoint()
        self.assertTrue(timeline.undo())
        self.assertEqual(timeline.videos, [])
        self.assertFalse(timeline.undo())

    def test_a_step_made_after_undo_and_redo_is_undone_alone(self):
        timeline = Timeline()
        timeline.add_video(media("a.mp4", 6))
        timeline.checkpoint()
        timeline.undo()
        timeline.redo()
        timeline.add_video(media("b.mp4", 4))
        timeline.checkpoint()
        self.assertTrue(timeline.undo())
        self.assertEqual([clip.media.name for clip in timeline.videos], ["a.mp4"])

    def test_editing_after_undo_discards_redo(self):
        timeline = Timeline()
        timeline.add_video(media("a.mp4", 6))
        timeline.checkpoint()
        timeline.undo()
        timeline.checkpoint()  # Harmless on its own...
        self.assertTrue(timeline.redo())
        timeline.undo()
        timeline.add_video(media("b.mp4", 4))  # ...but a real edit ends the redo history.
        timeline.checkpoint()
        self.assertFalse(timeline.redo())
        self.assertEqual([clip.media.name for clip in timeline.videos], ["b.mp4"])


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.timeline = Timeline()
        two_tiles(self.timeline)
        self.a = self.timeline.add_video(media("a.mp4", 6))
        self.b = self.timeline.add_video(media("silent.mp4", 4, has_audio=False))
        self.timeline.trim(self.a, trim_start_sec=1, trim_end_sec=3)
        self.music = self.timeline.add_sound(media("music.mp4", 20), start_sec=1.5)

    def test_refuses_an_empty_timeline(self):
        with self.assertRaises(ValueError):
            compose(Timeline())

    def test_clips_are_trimmed_placed_and_mixed(self):
        args = compose(self.timeline)
        self.assertEqual(args[:6], ["-ss", "1", "-t", "2", "-i", "/videos/a.mp4"])
        self.assertEqual(args[6:13], ["-ss", "0", "-t", "4", "-an", "-i", "/videos/silent.mp4"])
        # The music is cut where the picture ends (4 s in), 1.5 s after it starts.
        self.assertEqual(args[13:20], ["-ss", "0", "-t", "2.5", "-vn", "-i", "/videos/music.mp4"])
        graph = args[args.index("-filter_complex") + 1].split(";")
        self.assertEqual(graph[0], "color=c=black:s=1280x360:r=30:d=4[base]")
        self.assertIn("setpts=PTS-STARTPTS+1/TB[c0]", graph[1])
        self.assertEqual(graph[2], "[base][c0]overlay=x=0:y=0:eof_action=pass[k0]")
        self.assertIn("[k0][c1]overlay=x=640:y=0", ";".join(graph))
        self.assertIn("[0:a]", ";".join(graph))
        self.assertIn("adelay=1500:all=1[a2]", ";".join(graph))
        self.assertIn("[a0][a2]amix=inputs=2", graph[-1])
        self.assertEqual(args[args.index("-t", 20) + 1], "4")

    def test_audio_choice_and_text(self):
        self.timeline.audio = AUDIO_TRACK
        self.timeline.texts.append(TextOverlay(enabled=True, text="Hi", start_at_sec=1, duration_sec=2))
        args = compose(self.timeline)
        self.assertEqual(args[:7], ["-ss", "1", "-t", "2", "-an", "-i", "/videos/a.mp4"])
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("drawtext=text='Hi'", graph)
        self.assertNotIn("amix", graph)

    def test_playback_starts_part_way_at_a_smaller_size(self):
        self.timeline.texts.append(TextOverlay(enabled=True, text="Hi", x=100, size=64, start_at_sec=1, duration_sec=2))
        plan = compose_playback(self.timeline, 2.0, fit_within=(640, 640))
        self.assertEqual((plan.width, plan.height, plan.duration), (640, 180, 2.0))
        # a played from 1 s to 3 s: one second of it is left, and it starts at once.
        self.assertEqual(plan.picture[:7], ["-ss", "2", "-t", "1", "-an", "-i", "/videos/a.mp4"])
        graph = plan.picture[plan.picture.index("-filter_complex") + 1]
        self.assertIn("scale=320:180:", graph)
        self.assertIn("overlay=x=320:y=0", graph)
        self.assertIn("x=50:y=20:fontsize=32", graph)
        self.assertIn("between(t\\,0\\,1)", graph)
        self.assertNotIn("[aout]", graph)
        self.assertEqual(plan.sound[:7], ["-ss", "2", "-t", "1", "-vn", "-i", "/videos/a.mp4"])
        self.assertIn("-vn", plan.sound[7:14])
        self.assertIn("adelay=0:all=1", plan.sound[plan.sound.index("-filter_complex") + 1])
        self.timeline.audio = 1  # Only the silent video's tile: nothing to hear.
        self.assertIsNone(compose_playback(self.timeline, 0.0, (640, 640)).sound)


if __name__ == "__main__":
    unittest.main()
