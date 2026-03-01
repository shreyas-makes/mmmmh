import unittest

from pipeline import Segment, build_cut_segments


class SilenceCuttingTests(unittest.TestCase):
    def test_pause_floor_keeps_short_silence_intact(self):
        cuts = build_cut_segments(
            filler_segments=[],
            silence_segments=[Segment(1.0, 1.15)],
            handle_ms=0,
            breath_ms=0,
            pause_floor_ms=180,
            duration=5.0,
        )
        self.assertEqual(cuts, [])

    def test_pause_floor_cuts_only_excess_centered(self):
        cuts = build_cut_segments(
            filler_segments=[],
            silence_segments=[Segment(1.0, 1.5)],
            handle_ms=0,
            breath_ms=0,
            pause_floor_ms=200,
            duration=5.0,
        )
        self.assertEqual(len(cuts), 2)
        self.assertAlmostEqual(cuts[0].start, 1.0, places=3)
        self.assertAlmostEqual(cuts[0].end, 1.15, places=3)
        self.assertAlmostEqual(cuts[1].start, 1.35, places=3)
        self.assertAlmostEqual(cuts[1].end, 1.5, places=3)

    def test_pause_floor_falls_back_to_breath_when_missing(self):
        cuts = build_cut_segments(
            filler_segments=[],
            silence_segments=[Segment(2.0, 2.4)],
            handle_ms=0,
            breath_ms=250,
            pause_floor_ms=None,
            duration=5.0,
        )
        self.assertEqual(len(cuts), 2)
        # 400ms silence with 250ms floor means 150ms removed in the middle.
        self.assertAlmostEqual(cuts[0].end - cuts[0].start, 0.075, places=3)
        self.assertAlmostEqual(cuts[1].end - cuts[1].start, 0.075, places=3)


if __name__ == "__main__":
    unittest.main()
