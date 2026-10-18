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

    def test_three_lines_single_annotation(self):
        r1 = fitz.Rect(50, 50, 200, 65)
        r2 = fitz.Rect(50, 70, 250, 85)
        r3 = fitz.Rect(50, 90, 220, 105)
        label, xrefs = AnnotationManager.apply(
            self.page, AnnotationType.HIGHLIGHT, [r1, r2, r3], (1.0, 1.0, 0.0), 0.8
        )
        self.assertEqual(len(xrefs), 1)
        annots = list(self.page.annots())
        self.assertEqual(len(annots), 1)
        self.assertEqual(len(annots[0].vertices), 12)

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

    def test_update_geometry_by_xref_after_page_reload(self):
        r1 = fitz.Rect(50, 50, 200, 65)
        _, xrefs = AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r1], (0.0, 1.0, 0.0), 0.7)
        del self.page
        page2 = self.doc.load_page(0)
        r_new = [fitz.Rect(50, 50, 200, 65), fitz.Rect(50, 70, 250, 85)]
        new_annot = AnnotationManager.update_geometry(page2, xrefs[0], r_new)
        self.assertIsNotNone(new_annot)
        self.assertEqual(len(new_annot.vertices), 8)
        self.assertEqual(len(list(page2.annots())), 1)

    def test_delete_annot_by_xref_after_page_reload(self):
        r = fitz.Rect(50, 50, 200, 65)
        _, xrefs = AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r], (1.0, 1.0, 0.0))
        del self.page
        page2 = self.doc.load_page(0)
        success = AnnotationManager.delete_annot(page2, xrefs[0])
    def test_snapshot_and_restore_cycle_on_resize(self):
        r1 = [fitz.Rect(50, 50, 150, 65)]
        r2 = [fitz.Rect(50, 50, 250, 65), fitz.Rect(50, 70, 200, 85)]
        _, xrefs = AnnotationManager.apply(
            self.page, AnnotationType.HIGHLIGHT, r1, (1.0, 0.5, 0.0), 0.75
        )
        xref_initial = xrefs[0]

        # Snapshot before resize
        before_snap = AnnotationManager.snapshot_from_annot(self.page, 0, xref_initial)
        self.assertIsNotNone(before_snap)
        self.assertEqual(len(before_snap.line_rects), 1)
        self.assertAlmostEqual(before_snap.opacity, 0.75, places=2)

        # Resize annotation
        new_annot = AnnotationManager.update_geometry(self.page, xref_initial, r2)
        after_snap = AnnotationManager.snapshot_from_annot(self.page, 0, new_annot.xref)
        self.assertEqual(len(after_snap.line_rects), 2)

        # Undo: delete resized and restore before_snap
        AnnotationManager.delete_annot(self.page, new_annot.xref)
        restored_xref = AnnotationManager.restore_snapshot(self.page, before_snap)
        restored_annot = self.page.load_annot(restored_xref)
        self.assertEqual(len(restored_annot.vertices), 4)

        # Redo: delete restored and restore after_snap
        AnnotationManager.delete_annot(self.page, restored_xref)
        redone_xref = AnnotationManager.restore_snapshot(self.page, after_snap)
        redone_annot = self.page.load_annot(redone_xref)
        self.assertEqual(len(redone_annot.vertices), 8)

if __name__ == "__main__":
    unittest.main()
