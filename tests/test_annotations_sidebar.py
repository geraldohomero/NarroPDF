import unittest
from unittest.mock import MagicMock
import fitz

from src.constants import AnnotationType, ViewMode, ToolMode, PAGE_SPACING
from src.annotations import AnnotationManager
from src.pdf_renderer import PdfRenderer
from src.text_selection import TextSelectionHandler
from src.locale import _
from src.window.window import MainWindow


class TestAnnotationsSidebar(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        page1 = self.doc.new_page(width=500, height=800)
        page1.insert_text((72, 100), "Texto de teste da primeira página.")
        r1 = fitz.Rect(72, 90, 200, 110)
        _, xrefs1 = AnnotationManager.apply(page1, AnnotationType.HIGHLIGHT, [r1], (1.0, 1.0, 0.0), 0.8)
        self.xref1 = xrefs1[0]

        page2 = self.doc.new_page(width=500, height=800)
        page2.insert_text((72, 400), "Segunda página para anotação no meio da página.")
        r2 = fitz.Rect(72, 390, 280, 410)
        _, xrefs2 = AnnotationManager.apply(page2, AnnotationType.HIGHLIGHT, [r2], (0.0, 0.5, 1.0), 1.0)
        self.xref2 = xrefs2[0]

    def test_list_all_annotations(self):
        annots = AnnotationManager.list_all_annotations(self.doc)
        self.assertEqual(len(annots), 2)
        
        a0 = annots[0]
        self.assertEqual(a0["page_idx"], 0)
        self.assertEqual(a0["type_name"], "Highlight")
        self.assertTrue(len(a0["text"]) > 0)
        self.assertIsInstance(a0["rect"], fitz.Rect)

        a1 = annots[1]
        self.assertEqual(a1["page_idx"], 1)
        self.assertEqual(a1["type_name"], "Highlight")

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
        
        self.assertEqual(win.left_annots_list.append.call_count, 2)
        first_row = win.left_annots_list.append.call_args_list[0][0][0]
        self.assertEqual(first_row._target_page, 0)
        second_row = win.left_annots_list.append.call_args_list[1][0][0]
        self.assertEqual(second_row._target_page, 1)

    def test_on_left_annotation_row_activated_single_mode_real_renderer(self):
        """Using a real PdfRenderer (which has no .page_words attribute), clicking a sidebar annotation
        must select the annotation words on the page and scroll to its vertical position."""
        renderer = PdfRenderer()
        renderer.set_document(self.doc)

        vadj = MagicMock()
        vadj.get_page_size.return_value = 300.0
        vadj.get_upper.return_value = 1000.0
        vadj.get_lower.return_value = 0.0

        class DummyWindow:
            def __init__(self, doc):
                self.renderer = renderer
                self.view_mode = ViewMode.SINGLE
                self.current_page = 0
                self.selection = TextSelectionHandler()
                self.left_annots_list = MagicMock()
                self.scroller = MagicMock()
                self.scroller.get_vadjustment.return_value = vadj
                self._navigate_to_page_index = MagicMock(side_effect=self._fake_nav)
                self._render_view = MagicMock()
                self._show_selection_popover = MagicMock()
                self.selection_layer = MagicMock()
                self.selected_annotation = None

            def _fake_nav(self, idx):
                self.current_page = idx
                page = self.renderer.doc.load_page(idx)
                self.selection.set_words(TextSelectionHandler.extract_words(page))

            _find_word_bounds_for_annot = MainWindow._find_word_bounds_for_annot
            _scroll_to_annotation_rect = MainWindow._scroll_to_annotation_rect
            _on_left_annotation_row_activated = MainWindow._on_left_annotation_row_activated

        win = DummyWindow(self.doc)
        row = MagicMock()
        row._target_page = 1
        row._target_rect = fitz.Rect(72, 390, 280, 410)
        row._xref = self.xref2

        win._on_left_annotation_row_activated(win.left_annots_list, row)

        win._navigate_to_page_index.assert_called_once_with(1)
        self.assertIsNotNone(win.selected_annotation)
        self.assertEqual(win.selected_annotation["page_idx"], 1)
        self.assertEqual(win.selected_annotation["xref"], self.xref2)
        self.assertTrue(win.selection.has_selection)
        # Should also have scrolled vadj to the annotation position on the page
        vadj.set_value.assert_called()
        scroll_val = vadj.set_value.call_args[0][0]
        self.assertGreater(scroll_val, 100.0)

    def test_on_left_annotation_row_activated_continuous_mode_scrolls_to_exact_rect(self):
        """In continuous mode, activating an annotation row must scroll to the exact rect inside the page
        and trigger lazy rendering so words are available."""
        renderer = PdfRenderer()
        renderer.set_document(self.doc)
        renderer.page_widgets = [
            {"drawing_area": MagicMock(), "words": [], "rendered": False},
            {"drawing_area": MagicMock(), "words": [], "rendered": False},
        ]

        vadj = MagicMock()
        vadj.get_page_size.return_value = 400.0
        vadj.get_upper.return_value = 3000.0
        vadj.get_lower.return_value = 0.0

        class DummyWindow:
            def __init__(self):
                self.renderer = renderer
                self.view_mode = ViewMode.CONTINUOUS
                self.current_page = 0
                self.selection = TextSelectionHandler()
                self.left_annots_list = MagicMock()
                self.scroller = MagicMock()
                self.scroller.get_vadjustment.return_value = vadj
                self.page_entry = MagicMock()
                self._update_controls_sensitivity = MagicMock()
                self._on_continuous_page_rendered = MagicMock()
                self._show_selection_popover = MagicMock()
                self.selection_layer = MagicMock()
                self.selected_annotation = None
                self._is_navigating = False

            _navigate_to_page_index = MainWindow._navigate_to_page_index
            _find_word_bounds_for_annot = MainWindow._find_word_bounds_for_annot
            _scroll_to_annotation_rect = MainWindow._scroll_to_annotation_rect
            _on_left_annotation_row_activated = MainWindow._on_left_annotation_row_activated

        win = DummyWindow()
        row = MagicMock()
        row._target_page = 1
        row._target_rect = fitz.Rect(72, 390, 280, 410)
        row._xref = self.xref2

        # Mock lazy_render_visible_pages to avoid Pixbuf creation
        win.renderer.lazy_render_visible_pages = MagicMock(return_value=1)

        win._on_left_annotation_row_activated(win.left_annots_list, row)

        # Last scroll value on vadj must include both page 1 offset AND rect.y0 * zoom
        last_scroll_val = vadj.set_value.call_args[0][0]
        h_with_spacing = renderer.page_h + PAGE_SPACING
        page_1_top = h_with_spacing
        self.assertGreater(last_scroll_val, page_1_top + 100)
        self.assertIsNotNone(win.selected_annotation)
        self.assertEqual(win.selected_annotation["xref"], self.xref2)
        self.assertTrue(win.selection.has_selection)

    def test_clicking_pdf_annotation_syncs_sidebar_selection(self):
        """Clicking an annotation on the PDF selects the matching row in left_annots_list,
        and clicking blank space unselects all."""
        renderer = PdfRenderer()
        renderer.set_document(self.doc)

        row0 = MagicMock()
        row0._target_page = 0
        row0._xref = self.xref1

        row1 = MagicMock()
        row1._target_page = 1
        row1._xref = self.xref2

        rows = [row0, row1]

        class DummyWindow:
            def __init__(self):
                self.renderer = renderer
                self.tool_mode = ToolMode.SELECTION
                self.view_mode = ViewMode.SINGLE
                self.current_page = 0
                self.selection = TextSelectionHandler()
                page0 = self.renderer.doc.load_page(0)
                self.selection.set_words(TextSelectionHandler.extract_words(page0))
                self.left_annots_list = MagicMock()
                self.left_annots_list.get_row_at_index.side_effect = lambda i: rows[i] if 0 <= i < len(rows) else None
                self.popover = MagicMock()
                self.selection_layer = MagicMock()
                self._show_selection_popover = MagicMock()
                self._hit_test_handle = MagicMock(return_value=None)
                self.selected_annotation = None

            _find_word_bounds_for_annot = MainWindow._find_word_bounds_for_annot
            _sync_sidebar_annotation_selection = MainWindow._sync_sidebar_annotation_selection
            _on_single_click_pressed = MainWindow._on_single_click_pressed

        win = DummyWindow()
        # Click directly on annotation 1 at (100 * zoom, 100 * zoom)
        zoom = renderer.zoom
        win._on_single_click_pressed(MagicMock(), 1, 100.0 * zoom, 100.0 * zoom)

        self.assertIsNotNone(win.selected_annotation)
        self.assertEqual(win.selected_annotation["xref"], self.xref1)
        win.left_annots_list.select_row.assert_called_once_with(row0)

        # Now click on blank area (400 * zoom, 700 * zoom)
        win._on_single_click_pressed(MagicMock(), 1, 400.0 * zoom, 700.0 * zoom)
        self.assertIsNone(win.selected_annotation)
        win.left_annots_list.unselect_all.assert_called_once()


if __name__ == "__main__":
    unittest.main()
