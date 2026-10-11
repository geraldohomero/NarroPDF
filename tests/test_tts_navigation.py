import unittest
from unittest.mock import MagicMock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from src.tts_segmenter import TtsSentence, TtsWord
from src.constants import ViewMode

class TestTtsNavigation(unittest.TestCase):
    def test_scroll_target_calculation(self):
        from src.window.navigation import WindowNavigationMixin
        nav = WindowNavigationMixin()
        nav.renderer = MagicMock()
        nav.renderer.zoom = 1.0
        nav.renderer.page_h = 800
        nav.view_mode = ViewMode.CONTINUOUS
        nav.scroller = MagicMock()
        vadj = MagicMock()
        vadj.get_value.return_value = 0.0
        vadj.get_page_size.return_value = 600.0
        vadj.get_upper.return_value = 2000.0
        nav.scroller.get_vadjustment.return_value = vadj

        sent = TtsSentence(0, 0, 0, "Texto", [], [fitz.Rect(10, 550, 100, 570)])
        nav._scroll_to_tts_sentence(sent)
        self.assertTrue(vadj.set_value.called)

    def test_double_click_handler(self):
        from src.window.tts import WindowTtsMixin
        win = WindowTtsMixin()
        win.tts = MagicMock()
        win.renderer = MagicMock()
        win.renderer.zoom = 1.0
        win.current_page = 0
        win.voice_row = MagicMock()
        win.voice_row.get_selected.return_value = 0
        win.voice_model = MagicMock()
        win.voice_model.get_string.return_value = "pt-BR-AntonioNeural"
        win.current_language = "pt-BR"
        win.current_engine = "edge"
        win.speed_scale = MagicMock()
        win.speed_scale.get_value.return_value = 0.0

        sent = TtsSentence(0, 0, 2, "Alvo do clique", [TtsWord("Alvo", fitz.Rect(50, 50, 90, 70), 0, 0, 4)], [fitz.Rect(50, 50, 90, 70)])
        win.tts.get_sentences_for_page.return_value = [sent]

        # Call double click at (60, 60)
        win._on_pdf_double_clicked(0, 60.0, 60.0)
        win.tts.start_playback.assert_called_once()
        args, kwargs = win.tts.start_playback.call_args
        self.assertEqual(args[0], 0)  # page_idx
        self.assertEqual(args[1], 2)  # sentence_idx in page

if __name__ == "__main__":
    unittest.main()
