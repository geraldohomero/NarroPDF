import unittest
import fitz
from src.text_selection import TextSelectionHandler

class TestTextSelectionHandles(unittest.TestCase):
    def setUp(self):
        self.handler = TextSelectionHandler()
        self.handler.set_words([
            {"rect": fitz.Rect(10, 10, 50, 20), "text": "Hello", "block": 0, "line": 0, "word": 0},
            {"rect": fitz.Rect(55, 10, 100, 20), "text": "World", "block": 0, "line": 0, "word": 1},
            {"rect": fitz.Rect(10, 30, 80, 40), "text": "Second", "block": 0, "line": 1, "word": 0},
        ])

    def test_find_word_range_for_vertices(self):
        # Quad covering Hello and World
        vertices = [(10, 10), (100, 10), (10, 20), (100, 20)]
        bounds = self.handler.find_word_range_for_vertices(vertices)
        self.assertEqual(bounds, (0, 1))

    def test_set_selection_bounds_and_handle_positions(self):
        self.handler.set_selection_bounds(0, 1)
        self.assertEqual(self.handler.get_selected_bounds(), (0, 1))
        handles = self.handler.get_handle_positions(zoom=2.0)
        self.assertIsNotNone(handles)
        start_pt, end_pt = handles
        # Start handle at top-left of word 0 (10*2, 10*2) = (20, 20)
        self.assertEqual(start_pt, (20.0, 20.0))
        # End handle at bottom-right of word 1 (100*2, 20*2) = (200, 40)
        self.assertEqual(end_pt, (200.0, 40.0))

if __name__ == "__main__":
    unittest.main()

