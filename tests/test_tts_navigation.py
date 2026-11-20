import unittest
from unittest.mock import MagicMock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import gi
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

from src.tts_segmenter import TtsSentence, TtsWord
from src.constants import PAGE_SHADOW_VERTICAL_CHROME, PAGE_SPACING, ViewMode
from src.pdf_renderer import PdfRenderer


class _DummyNavWindow:
    """Minimal harness combining navigation, TTS, and MainWindow follow helpers."""

    def __init__(self, view_mode=ViewMode.CONTINUOUS):
        from src.window.navigation import WindowNavigationMixin
        from src.window.tts import WindowTtsMixin
        from src.window.window import MainWindow

        self.renderer = MagicMock()
        self.renderer.zoom = 1.0
        self.renderer.page_h = 800
        self.renderer.page_heights = []
        self.renderer.page_widgets = []
        self.renderer.doc = MagicMock()
        self.view_mode = view_mode
        self.current_page = 0
        self.tts = MagicMock()
        self.tts.is_playing = True
        self.tts_follow_active = True
        self._updating_follow_toggle = False
        self._is_navigating = False
        self._is_tts_auto_scrolling = False
        self._is_zooming = False
        self._last_tts_scroll_value = None
        self._last_vadj_page_size = 600.0
        self._last_vadj_upper = 20000.0
        self.active_tts_sentence = None
        self.active_tts_word_index = -1
        self.btn_follow_tts = MagicMock()
        self.scroller = MagicMock()
        self.vadj = MagicMock()
        self.vadj.get_value.return_value = 0.0
        self.vadj.get_page_size.return_value = 600.0
        self.vadj.get_lower.return_value = 0.0
        self.vadj.get_upper.return_value = 20000.0
        self.scroller.get_vadjustment.return_value = self.vadj
        self.page_entry = MagicMock()
        self.text_buffer = MagicMock()
        self.selection = MagicMock()
        self._update_controls_sensitivity = MagicMock()
        self._on_continuous_page_rendered = MagicMock()
        self._adjust_zoom = MagicMock()
        self._navigate_page = MagicMock()

        # Bind methods
        self._compute_tts_target_scroll_y = WindowNavigationMixin._compute_tts_target_scroll_y.__get__(self)
        self._scroll_to_tts_word = WindowNavigationMixin._scroll_to_tts_word.__get__(self)
        self._scroll_to_tts_sentence = WindowNavigationMixin._scroll_to_tts_sentence.__get__(self)
        self._on_mouse_scroll = WindowNavigationMixin._on_mouse_scroll.__get__(self)
        self._on_viewport_scrolled = WindowNavigationMixin._on_viewport_scrolled.__get__(self)
        self._on_viewport_page_size_changed = WindowNavigationMixin._on_viewport_page_size_changed.__get__(self)
        self._recenter_active_tts_word = WindowNavigationMixin._recenter_active_tts_word.__get__(self)
        self._set_tts_follow_active = WindowTtsMixin._set_tts_follow_active.__get__(self)
        self._sync_follow_tts_button = WindowTtsMixin._sync_follow_tts_button.__get__(self)
        self._on_follow_tts_toggled = WindowTtsMixin._on_follow_tts_toggled.__get__(self)
        self._release_tts_follow_if_playing = WindowTtsMixin._release_tts_follow_if_playing.__get__(self)
        self._on_tts_page_change_requested = MainWindow._on_tts_page_change_requested.__get__(self)
        self._navigate_to_page_index = MagicMock(side_effect=self._fake_nav)

    def _fake_nav(self, idx, from_tts=False):
        if not from_tts:
            self._release_tts_follow_if_playing()
        self.current_page = idx


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

    def test_active_word_centered_in_viewport_not_sentence_top(self):
        win = _DummyNavWindow(ViewMode.CONTINUOUS)
        win.renderer.zoom = 1.5
        win.renderer.page_heights = [1200]
        win.vadj.get_page_size.return_value = 600.0
        win.vadj.get_upper.return_value = 1500.0

        sent = TtsSentence(
            page_index=0,
            paragraph_index=0,
            sentence_index=0,
            text="linha um linha dois linha tres",
            words=[
                TtsWord("linha", fitz.Rect(10, 100, 50, 120), 0, 0, 5),
                TtsWord("tres", fitz.Rect(10, 400, 50, 420), 1, 26, 30),
            ],
            line_rects=[fitz.Rect(10, 100, 100, 120), fitz.Rect(10, 400, 100, 420)],
        )
        win._scroll_to_tts_word(sent, word_idx=1)

        # word center in page: ((400 + 420) / 2) * 1.5 = 615.0
        # page 0 top offset: PAGE_SPACING (8) + PAGE_SHADOW_VERTICAL_CHROME / 2 (9) = 17.0
        # global y = 632.0; centered scroll = 632.0 - 300.0 = 332.0
        win.vadj.set_value.assert_called_once()
        self.assertAlmostEqual(win.vadj.set_value.call_args[0][0], 332.0, places=2)

    def test_multipage_variable_heights_and_chrome_no_upward_drift(self):
        win = _DummyNavWindow(ViewMode.CONTINUOUS)
        win.renderer.zoom = 1.0
        heights = [700 if i % 2 == 0 else 950 for i in range(25)]
        win.renderer.page_heights = heights
        win.vadj.get_page_size.return_value = 600.0
        win.vadj.get_upper.return_value = 30000.0

        target_page = 20
        sent = TtsSentence(
            page_index=target_page,
            paragraph_index=0,
            sentence_index=0,
            text="palavra",
            words=[TtsWord("palavra", fitz.Rect(50, 390, 110, 410), 0, 0, 7)],
            line_rects=[fitz.Rect(50, 390, 110, 410)],
        )
        win._scroll_to_tts_word(sent, word_idx=0)

        expected_page_top = (
            PAGE_SPACING
            + (PAGE_SHADOW_VERTICAL_CHROME / 2.0)
            + sum(h + PAGE_SPACING + PAGE_SHADOW_VERTICAL_CHROME for h in heights[:target_page])
        )
        expected_scroll = (expected_page_top + 400.0) - 300.0
        win.vadj.set_value.assert_called_once()
        self.assertAlmostEqual(win.vadj.set_value.call_args[0][0], expected_scroll, places=2)

    def test_deadzone_prevents_jitter_unless_forced(self):
        win = _DummyNavWindow(ViewMode.CONTINUOUS)
        win.renderer.page_heights = [1200]
        # Page 0 top = 17.0; word center = 400.0 -> global = 417.0; target = 417 - 300 = 117.0
        win.vadj.get_value.return_value = 114.0  # delta = 3.0 < 6.0

        sent = TtsSentence(
            page_index=0,
            paragraph_index=0,
            sentence_index=0,
            text="palavra",
            words=[TtsWord("palavra", fitz.Rect(50, 390, 110, 410), 0, 0, 7)],
            line_rects=[fitz.Rect(50, 390, 110, 410)],
        )
        win._scroll_to_tts_word(sent, word_idx=0, force=False)
        win.vadj.set_value.assert_not_called()

        win._scroll_to_tts_word(sent, word_idx=0, force=True)
        win.vadj.set_value.assert_called_once_with(117.0)

    def test_free_scroll_mode_does_not_scroll_or_flip_page(self):
        win = _DummyNavWindow(ViewMode.SINGLE)
        win.tts_follow_active = False

        sent = TtsSentence(
            page_index=3,
            paragraph_index=0,
            sentence_index=0,
            text="palavra",
            words=[TtsWord("palavra", fitz.Rect(50, 390, 110, 410), 0, 0, 7)],
            line_rects=[fitz.Rect(50, 390, 110, 410)],
        )
        win._on_tts_page_change_requested(3)
        win._navigate_to_page_index.assert_not_called()

        win._scroll_to_tts_word(sent, word_idx=0, force=False)
        win.vadj.set_value.assert_not_called()

    def test_single_page_mode_switches_page_and_centers_word_when_zoomed(self):
        win = _DummyNavWindow(ViewMode.SINGLE)
        win.current_page = 0
        win.renderer.zoom = 2.0
        win.vadj.get_value.return_value = 0.0
        win.vadj.get_page_size.return_value = 600.0
        win.vadj.get_upper.return_value = 2000.0

        sent = TtsSentence(
            page_index=2,
            paragraph_index=0,
            sentence_index=0,
            text="palavra",
            words=[TtsWord("palavra", fitz.Rect(50, 490, 110, 510), 0, 0, 7)],
            line_rects=[fitz.Rect(50, 490, 110, 510)],
        )
        win._scroll_to_tts_word(sent, word_idx=0)

        win._navigate_to_page_index.assert_called_once_with(2, from_tts=True)
        self.assertEqual(win.current_page, 2)
        # 500 * 2.0 - 300 = 700.0
        win.vadj.set_value.assert_called_once_with(700.0)

    def test_manual_scroll_releases_follow_but_ctrl_zoom_keeps_follow(self):
        win = _DummyNavWindow(ViewMode.CONTINUOUS)

        ctrl_event = MagicMock()
        ctrl_event.get_current_event_state.return_value = Gdk.ModifierType.CONTROL_MASK
        handled = win._on_mouse_scroll(ctrl_event, 0.0, -1.0)
        self.assertTrue(handled)
        self.assertTrue(win.tts_follow_active)
        win._adjust_zoom.assert_called_once()

        plain_event = MagicMock()
        plain_event.get_current_event_state.return_value = Gdk.ModifierType(0)
        win._on_mouse_scroll(plain_event, 0.0, 1.0)
        self.assertFalse(win.tts_follow_active)
        win.btn_follow_tts.set_active.assert_called_with(False)

    def test_scrollbar_drag_releases_follow_while_geometry_change_keeps_it(self):
        win = _DummyNavWindow(ViewMode.CONTINUOUS)
        win.view_mode = ViewMode.SINGLE  # Isolate vadj detection from continuous lazy render
        win._last_tts_scroll_value = 100.0
        win._last_vadj_page_size = 600.0
        win._last_vadj_upper = 2000.0

        # Window resize changes page_size (notify::page-size before clamped value-changed) -> should NOT release follow
        win.vadj.get_page_size.return_value = 650.0
        win._on_viewport_page_size_changed(win.vadj, None)
        win.vadj.get_value.return_value = 130.0
        win.vadj.get_upper.return_value = 2000.0
        win._on_viewport_scrolled(win.vadj)
        self.assertTrue(win.tts_follow_active)

        # Manual scrollbar drag without geometry change -> releases follow
        win.vadj.get_value.return_value = 250.0
        win.vadj.get_page_size.return_value = 650.0
        win.vadj.get_upper.return_value = 2000.0
        win._on_viewport_scrolled(win.vadj)
        self.assertFalse(win.tts_follow_active)

    def test_toggle_follow_back_on_recenters_active_word(self):
        win = _DummyNavWindow(ViewMode.CONTINUOUS)
        win.renderer.page_heights = [1200]
        win.tts_follow_active = False
        win.vadj.get_value.return_value = 900.0
        win.active_tts_sentence = TtsSentence(
            page_index=0,
            paragraph_index=0,
            sentence_index=0,
            text="palavra",
            words=[TtsWord("palavra", fitz.Rect(50, 390, 110, 410), 0, 0, 7)],
            line_rects=[fitz.Rect(50, 390, 110, 410)],
        )
        win.active_tts_word_index = 0

        win._set_tts_follow_active(True, recenter=True)
        self.assertTrue(win.tts_follow_active)
        win.vadj.set_value.assert_called_once_with(117.0)

    def test_renderer_lazy_render_with_mixed_page_heights(self):
        doc = fitz.open()
        heights_pt = [600, 900, 750, 1100, 800]
        for h in heights_pt:
            doc.new_page(width=500, height=h)

        renderer = PdfRenderer()
        renderer.set_zoom(1.0)
        renderer.set_document(doc)
        renderer.render_page_pixbuf = MagicMock(return_value=None)
        renderer.page_heights = list(heights_pt)
        renderer.page_widgets = [
            {
                "overlay": MagicMock(),
                "picture": MagicMock(),
                "drawing_area": MagicMock(),
                "width": 500,
                "height": h,
                "words": [],
                "rendered": False,
            }
            for h in heights_pt
        ]

        # Compute exact middle of page 3 (index 3)
        page3_start = PAGE_SPACING + sum(
            h + PAGE_SPACING + PAGE_SHADOW_VERTICAL_CHROME for h in heights_pt[:3]
        )
        page3_mid = page3_start + (PAGE_SHADOW_VERTICAL_CHROME / 2.0) + (heights_pt[3] / 2.0)
        viewport_h = 600.0
        scroll_y = page3_mid - (viewport_h / 2.0)

        active = renderer.lazy_render_visible_pages(scroll_y, viewport_h, MagicMock())
        self.assertEqual(active, 3)
        self.assertTrue(renderer.page_widgets[3]["rendered"])
        self.assertFalse(renderer.page_widgets[0]["rendered"])


if __name__ == "__main__":
    unittest.main()
