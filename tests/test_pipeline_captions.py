import unittest

from pipeline import (
    Segment,
    build_caption_segments,
    format_srt_time,
    map_time_to_output_timeline,
    remap_words_to_output_timeline,
)


class CaptionPipelineTests(unittest.TestCase):
    def test_map_time_to_output_timeline_across_two_keep_segments(self):
        keep = [Segment(0.0, 2.0), Segment(4.0, 6.0)]
        self.assertAlmostEqual(map_time_to_output_timeline(1.5, keep), 1.5)
        self.assertAlmostEqual(map_time_to_output_timeline(4.5, keep), 2.5)
        self.assertIsNone(map_time_to_output_timeline(3.0, keep))

    def test_remap_words_to_output_timeline_filters_cut_words(self):
        keep = [Segment(0.0, 1.0), Segment(2.0, 3.0)]
        words = [
            {"word": "hello", "start": 0.1, "end": 0.4},
            {"word": "cut", "start": 1.2, "end": 1.5},
            {"word": "world", "start": 2.2, "end": 2.5},
        ]
        remapped = remap_words_to_output_timeline(words, keep)
        self.assertEqual([w["word"] for w in remapped], ["hello", "world"])
        self.assertAlmostEqual(remapped[1]["start"], 1.2)

    def test_build_caption_segments_splits_on_gap_and_length(self):
        words = [
            {"word": "This", "start": 0.0, "end": 0.2},
            {"word": "is", "start": 0.21, "end": 0.3},
            {"word": "one.", "start": 0.31, "end": 0.5},
            {"word": "Second", "start": 1.2, "end": 1.4},
            {"word": "segment", "start": 1.41, "end": 1.7},
        ]
        segments = build_caption_segments(words, max_chars=30, gap_threshold=0.35)
        self.assertGreaterEqual(len(segments), 2)
        self.assertEqual(segments[0].text, "This is one.")

    def test_format_srt_time(self):
        self.assertEqual(format_srt_time(0.0), "00:00:00,000")
        self.assertEqual(format_srt_time(62.345), "00:01:02,345")


if __name__ == "__main__":
    unittest.main()
