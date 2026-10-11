import unittest
import fitz
from src.constants import AnnotationType
from src.annotations import AnnotationManager

class TestAnnotationManager(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page()

    def test_unified_multi_line_highlight(self):
        r1 = fitz.Rect(50, 50, 200, 65)
        r2 = fitz.Rect(50, 70, 250, 85)
        label, xrefs = AnnotationManager.apply(
            self.page, AnnotationType.HIGHLIGHT, [r1, r2], (1.0, 1.0, 0.0), 0.8
        )
        self.assertEqual(label, "Highlight")
        self.assertEqual(len(xrefs), 1)
        annots = list(self.page.annots())
        self.assertEqual(len(annots), 1)
        self.assertEqual(len(annots[0].vertices), 8)

    def test_unified_multi_line_underline(self):
        r1 = fitz.Rect(50, 50, 200, 65)
        r2 = fitz.Rect(50, 70, 250, 85)
        label, xrefs = AnnotationManager.apply(
            self.page, AnnotationType.UNDERLINE, [r1, r2], (1.0, 0.0, 0.0), 0.9
        )
        self.assertEqual(label, "Underline")
        self.assertEqual(len(xrefs), 1)
        annots = list(self.page.annots())
        self.assertEqual(len(annots), 1)
        self.assertEqual(len(annots[0].vertices), 8)

    def test_find_at_point(self):
        r = fitz.Rect(50, 50, 200, 65)
        AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r], (1.0, 1.0, 0.0))
        hit = AnnotationManager.find_at_point(self.page, (100, 55))
        self.assertIsNotNone(hit)
        miss = AnnotationManager.find_at_point(self.page, (300, 300))
        self.assertIsNone(miss)

    def test_update_geometry(self):
        r1 = fitz.Rect(50, 50, 200, 65)
        _, xrefs = AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r1], (0.0, 1.0, 0.0), 0.7)
        annot = self.page.first_annot
        r_new = [fitz.Rect(50, 50, 200, 65), fitz.Rect(50, 70, 250, 85)]
        new_annot = AnnotationManager.update_geometry(self.page, annot, r_new)
        self.assertIsNotNone(new_annot)
        self.assertEqual(len(new_annot.vertices), 8)
        self.assertEqual(len(list(self.page.annots())), 1)

    def test_delete_annot(self):
        r = fitz.Rect(50, 50, 200, 65)
        AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r], (1.0, 1.0, 0.0))
        annot = self.page.first_annot
        success = AnnotationManager.delete_annot(self.page, annot)
        self.assertTrue(success)
        self.assertEqual(len(list(self.page.annots())), 0)

if __name__ == "__main__":
    unittest.main()
