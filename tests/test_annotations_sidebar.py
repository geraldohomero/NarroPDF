import unittest
from unittest.mock import MagicMock
import fitz

from src.constants import AnnotationType, ViewMode
from src.annotations import AnnotationManager
from src.locale import _
from src.window.window import MainWindow


class TestAnnotationsSidebar(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        page1 = self.doc.new_page()
        page1.insert_text((72, 100), "Texto de teste da primeira página.")
        r1 = fitz.Rect(72, 90, 200, 110)
        AnnotationManager.apply(page1, AnnotationType.HIGHLIGHT, [r1], (1.0, 1.0, 0.0), 0.8)

        page2 = self.doc.new_page()
        page2.insert_text((72, 100), "Segunda página para anotação de nota.")
        r2 = fitz.Rect(72, 90, 200, 110)
        AnnotationManager.apply(page2, AnnotationType.NOTE, [r2], (0.0, 0.5, 1.0), 1.0, content="Minha nota importante")

    def test_list_all_annotations(self):
        annots = AnnotationManager.list_all_annotations(self.doc)
        self.assertEqual(len(annots), 2)
        
        # Check first annotation (highlight on page 0)
        a0 = annots[0]
        self.assertEqual(a0["page_idx"], 0)
        self.assertEqual(a0["type_name"], "Highlight")
        self.assertTrue(len(a0["text"]) > 0)
        self.assertIsInstance(a0["rect"], fitz.Rect)

        # Check second annotation (note on page 1)
        a1 = annots[1]
        self.assertEqual(a1["page_idx"], 1)
        self.assertEqual(a1["type_name"], "Note")
        self.assertIn("Minha nota importante", a1["text"])

    def test_empty_doc_annotations(self):
        empty_doc = fitz.open()
        empty_doc.new_page()
        annots = AnnotationManager.list_all_annotations(empty_doc)
        self.assertEqual(len(annots), 0)

    def test_reload_annotations_tab_creates_rows(self):
        class DummyWindow:
            def __init__(self, doc):
                self.renderer = MagicMock()
                self.renderer.doc = doc
                self.left_annots_list = MagicMock()
            _reload_annotations_tab = MainWindow._reload_annotations_tab

        win = DummyWindow(self.doc)
        win._reload_annotations_tab()
        
        # Should have appended 2 rows
        self.assertEqual(win.left_annots_list.append.call_count, 2)
        first_row = win.left_annots_list.append.call_args_list[0][0][0]
        self.assertEqual(first_row._target_page, 0)
        second_row = win.left_annots_list.append.call_args_list[1][0][0]
        self.assertEqual(second_row._target_page, 1)

    def test_on_left_annotation_row_activated(self):
        class DummyWindow:
            def __init__(self, doc):
                self.renderer = MagicMock()
                self.renderer.doc = doc
                self.view_mode = ViewMode.SINGLE
                self.selection = MagicMock()
                self._navigate_to_page_index = MagicMock()
                self._render_view = MagicMock()
                self._show_selection_popover = MagicMock()
                self.selection_layer = MagicMock()
            _on_left_annotation_row_activated = MainWindow._on_left_annotation_row_activated

        win = DummyWindow(self.doc)
        row = MagicMock()
        row._target_page = 1
        row._target_rect = fitz.Rect(72, 90, 200, 110)
        row._xref = 123
        win._on_left_annotation_row_activated(MagicMock(), row)
        
        win._navigate_to_page_index.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
