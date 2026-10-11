import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from src.tts_segmenter import TtsWord, TtsSentence, TtsParagraph
from src.tts_coordinator import (
    WordBoundaryInfo,
    align_word_boundaries,
    interpolate_word_boundaries,
    find_boundary_index_at_time,
)

class TestTtsCoordinator(unittest.TestCase):
    def test_align_word_boundaries_exact(self):
        words = [
            TtsWord("Olá", fitz.Rect(0, 0, 10, 10), 0, 0, 3),
            TtsWord("mundo", fitz.Rect(12, 0, 25, 10), 1, 4, 9),
        ]
        raw_boundaries = [
            {"offset": 1000000, "duration": 2000000, "text": "Olá"},
            {"offset": 3000000, "duration": 3000000, "text": "mundo"},
        ]
        aligned = align_word_boundaries(words, raw_boundaries)
        self.assertEqual(len(aligned), 2)
        self.assertEqual(aligned[0].word_index, 0)
        self.assertAlmostEqual(aligned[0].time, 0.1, places=4)
        self.assertEqual(aligned[1].word_index, 1)
        self.assertAlmostEqual(aligned[1].time, 0.3, places=4)

    def test_interpolate_word_boundaries(self):
        words = [
            TtsWord("Um", fitz.Rect(0, 0, 10, 10), 0, 0, 2),
            TtsWord("dois", fitz.Rect(12, 0, 25, 10), 1, 3, 7),
            TtsWord("três", fitz.Rect(27, 0, 40, 10), 2, 8, 12),
        ]
        total_duration = 3.0  # seconds
        interpolated = interpolate_word_boundaries(words, total_duration)
        self.assertEqual(len(interpolated), 3)
        self.assertEqual(interpolated[0].word_index, 0)
        self.assertEqual(interpolated[0].time, 0.0)
        self.assertTrue(interpolated[1].time > 0.0)
        self.assertTrue(interpolated[2].time > interpolated[1].time)
        self.assertAlmostEqual(
            interpolated[-1].time + interpolated[-1].duration, total_duration, places=2
        )

    def test_find_boundary_index_at_time(self):
        boundaries = [
            WordBoundaryInfo(time=0.0, duration=0.5, text="A", word_index=0),
            WordBoundaryInfo(time=0.5, duration=0.8, text="B", word_index=1),
            WordBoundaryInfo(time=1.3, duration=0.7, text="C", word_index=2),
        ]
        # At t=0.2s -> A (idx 0)
        self.assertEqual(find_boundary_index_at_time(boundaries, 0.2), 0)
        # At t=0.7s -> B (idx 1)
        self.assertEqual(find_boundary_index_at_time(boundaries, 0.7), 1)
        # At t=1.5s -> C (idx 2)
        self.assertEqual(find_boundary_index_at_time(boundaries, 1.5), 2)
        # Before first -> 0
        self.assertEqual(find_boundary_index_at_time(boundaries, -0.1), 0)
        # After last -> 2
        self.assertEqual(find_boundary_index_at_time(boundaries, 5.0), 2)

if __name__ == "__main__":
    unittest.main()
