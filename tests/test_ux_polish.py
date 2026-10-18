import unittest
from unittest.mock import MagicMock, patch
import fitz

from src.constants import ToolMode, AnnotationType
from src.locale import _, set_language, LANG
from src.window.tts import WindowTtsMixin
from src.window.navigation import WindowNavigationMixin
from src.window.window import MainWindow


class TestUxPolish(unittest.TestCase):
    def test_apply_detected_language_silently(self):
        class DummyTts(WindowTtsMixin):
            def __init__(self):
                self.settings = {"active_languages": ["pt-BR", "en-US", "es-ES"]}
                self.current_language = "pt-BR"
                self.lang_row = MagicMock()
                self._update_voices_for_lang_code = MagicMock()

        tts = DummyTts()
        tts._apply_detected_language_silently("en-US")
        self.assertEqual(tts.current_language, "en-US")
        tts.lang_row.set_selected.assert_called_once_with(1)
        tts._update_voices_for_lang_code.assert_called_once_with("en-US")

    def test_change_interface_lang(self):
        class DummyWindow:
            def __init__(self):
                self.settings = MagicMock()
                self._refresh_ui_translations = MagicMock()
                self.status = ""
            def set_status(self, msg):
                self.status = msg
            _change_interface_lang = MainWindow._change_interface_lang

        win = DummyWindow()
        win._change_interface_lang("en")
        self.assertEqual(_("page_singular"), "Page")
        win.settings.set.assert_called_with("app_language", "en")
        win._refresh_ui_translations.assert_called_once()

        # Reset back to pt
        win._change_interface_lang("pt")
        self.assertEqual(_("page_singular"), "Página")

    def test_sidebar_uses_page_singular(self):
        class DummySidebarWindow:
            def __init__(self):
                self.renderer = MagicMock()
                mock_doc = MagicMock()
                mock_doc.__len__.return_value = 2
                mock_doc.get_toc.return_value = []
                self.renderer.doc = mock_doc
                self.left_pages_list = MagicMock()
                self.left_chapters_list = MagicMock()
            _reload_left_sidebar = MainWindow._reload_left_sidebar

        set_language("pt")
        win = DummySidebarWindow()
        win._reload_left_sidebar()
        
        # Check that rows were added with label containing "Página"
        appended_rows = win.left_pages_list.append.call_args_list
        self.assertEqual(len(appended_rows), 2)
        label_child = appended_rows[0][0][0].get_child()
        self.assertEqual(label_child.get_label(), "Página 1")

    def test_direct_pen_mode_triggers_apply_annotation(self):
        class DummyNavWindow(WindowNavigationMixin):
            def __init__(self):
                self.tool_mode = ToolMode.HIGHLIGHT
                self._drag_started = True
                self.selection = MagicMock()
                self.selection.end_drag.return_value = True
                self.renderer = MagicMock()
                self.renderer.zoom = 1.0
                self.selection_layer = MagicMock()
                self._apply_annotation = MagicMock()
                self._show_selection_popover = MagicMock()

        win = DummyNavWindow()
        win._on_single_drag_end(MagicMock(), 10.0, 10.0)
        
        # Should directly call _apply_annotation(AnnotationType.HIGHLIGHT) and NOT show popover
        win._apply_annotation.assert_called_once_with(AnnotationType.HIGHLIGHT)
        win._show_selection_popover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
