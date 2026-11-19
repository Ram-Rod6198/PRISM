import unittest

from video_combiner.timecode import format_duration, format_timecode, parse_timecode


class ParseTimecodeTest(unittest.TestCase):
    def test_accepts_seconds_minutes_and_hours(self):
        self.assertEqual(parse_timecode("90"), 90.0)
        self.assertEqual(parse_timecode("1:30"), 90.0)
        self.assertEqual(parse_timecode("00:01:30.5"), 90.5)

    def test_rejects_what_is_not_a_time(self):
        for text in ("", None, "abc", "1:", "1:2:3:4"):
            self.assertIsNone(parse_timecode(text))

    def test_reads_hundredths_when_plain_reading_exceeds_limit(self):
        self.assertEqual(parse_timecode("00:05:50", limit=10.0), 5.5)
        self.assertEqual(parse_timecode("00:05:50", limit=3600.0), 350.0)
        self.assertEqual(parse_timecode("00:05:50"), 350.0)


class FormatTest(unittest.TestCase):
    def test_timecode_round_trips(self):
        self.assertEqual(format_timecode(90), "00:01:30")
        self.assertEqual(format_timecode(3.25), "00:00:03.25")
        self.assertEqual(format_timecode(None), "")
        self.assertEqual(parse_timecode(format_timecode(3725.125)), 3725.125)

    def test_duration(self):
        self.assertEqual(format_duration(4.2), "4.20s")
        self.assertEqual(format_duration(125), "2:05.00")
        self.assertEqual(format_duration(0), "0.00s")


if __name__ == "__main__":
    unittest.main()
