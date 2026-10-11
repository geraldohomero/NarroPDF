import unittest
from unittest.mock import MagicMock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from src.tts_segmenter import TtsSentence, TtsWord

class TestTtsVisual(unittest.TestCase):
    def test_highlight_rendering_calls_cairo(self):
        from src.window.annotations import WindowAnnotationsMixin
        mixin = WindowAnnotationsMixin()
        mixin.renderer = MagicMock()
        mixin.renderer.zoom = 1.5
        mixin.active_tts_sentence = TtsSentence(
            page_index=0,
            paragraph_index=0,
            sentence_index=0,
            text="Exemplo de teste",
            words=[
                TtsWord("Exemplo", fitz.Rect(10, 10, 50, 20), 0, 0, 7),
                TtsWord("de", fitz.Rect(55, 10, 70, 20), 1, 8, 10),
                TtsWord("teste", fitz.Rect(75, 10, 110, 20), 2, 11, 16),
            ],
            line_rects=[fitz.Rect(10, 10, 110, 20)]
        )
        mixin.active_tts_word_index = 1
        cr = MagicMock()
        mixin._render_tts_highlights_on_cr(cr, 0)

        # Verify sentence and word rectangles were drawn
        self.assertTrue(cr.rectangle.called)
        self.assertTrue(cr.fill.called)
        # Sentence line_rect scaled by 1.5: (15, 15, 150, 15)
        cr.rectangle.assert_any_call(15.0, 15.0, 150.0, 15.0)
        # Word rect scaled by 1.5: (82.5, 15.0, 22.5, 15.0)
        cr.rectangle.assert_any_call(82.5, 15.0, 22.5, 15.0)

    def test_highlight_rendering_different_page_does_nothing(self):
        from src.window.annotations import WindowAnnotationsMixin
        mixin = WindowAnnotationsMixin()
        mixin.renderer = MagicMock()
        mixin.renderer.zoom = 1.0
        mixin.active_tts_sentence = TtsSentence(
            page_index=0,
            paragraph_index=0,
            sentence_index=0,
            text="Exemplo",
            words=[TtsWord("Exemplo", fitz.Rect(10, 10, 50, 20), 0, 0, 7)],
            line_rects=[fitz.Rect(10, 10, 50, 20)]
        )
        mixin.active_tts_word_index = 0
        cr = MagicMock()
        mixin._render_tts_highlights_on_cr(cr, 1) # Different page
        self.assertFalse(cr.rectangle.called)

if __name__ == "__main__":
    unittest.main()
