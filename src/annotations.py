"""PDF annotation manager for highlights, underlines, and notes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz

from .constants import AnnotationType

log = logging.getLogger(__name__)


class AnnotationManager:
    """Applies annotations to PDF pages using PyMuPDF."""

    @staticmethod
    def apply(
        page: fitz.Page,
        annotation_type: AnnotationType,
        line_rects: list[fitz.Rect],
        color: tuple[float, float, float],
        opacity: float = 1.0,
    ) -> tuple[str, list[int]]:
        """Apply an annotation to the given page.

        Args:
            page: The PyMuPDF page to annotate.
            annotation_type: Type of annotation to create.
            line_rects: List of fitz.Rect objects covering selected lines.
            color: RGB tuple (0.0–1.0) for annotation color.
            opacity: Opacity float value (0.0 to 1.0).

        Returns:
            A tuple containing:
                - Human-readable label of the applied annotation.
                - List of PDF object xref IDs created.

        Raises:
            ValueError: If line_rects is empty.
        """
        if not line_rects:
            raise ValueError("No selection rects provided for annotation.")

        quads = [rect.quad for rect in line_rects]

        if annotation_type == AnnotationType.HIGHLIGHT:
            annot = page.add_highlight_annot(quads)
            annot.set_colors(stroke=color)
            annot.set_opacity(opacity)
            annot.update()
            return "Highlight", [annot.xref]

        elif annotation_type == AnnotationType.UNDERLINE:
            annot = page.add_underline_annot(quads)
            annot.set_colors(stroke=color)
            annot.set_opacity(opacity)
            annot.update()
            return "Underline", [annot.xref]

        elif annotation_type == AnnotationType.NOTE:
            annot = page.add_text_annot(
                line_rects[0].tl, "Nota criada no editor"
            )
            annot.set_colors(stroke=color)
            annot.set_opacity(opacity)
            annot.update()
            return "Nota", [annot.xref]

        else:
            raise ValueError(f"Unknown annotation type: {annotation_type}")

    @staticmethod
    def find_at_point(
        page: fitz.Page, point: fitz.Point | tuple[float, float]
    ) -> fitz.Annot | None:
        """Find a highlight or underline annotation intersecting point (px, py).

        Args:
            page: PyMuPDF page to inspect.
            point: (x, y) coordinates in PDF points.

        Returns:
            fitz.Annot if hit, else None.
        """
        import fitz

        pt = fitz.Point(*point) if not isinstance(point, fitz.Point) else point

        annot = page.first_annot
        while annot:
            # fitz.PDF_ANNOT_HIGHLIGHT = 8, fitz.PDF_ANNOT_UNDERLINE = 9
            if annot.type[0] in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE):
                if pt in annot.rect:
                    vertices = annot.vertices
                    if vertices and len(vertices) >= 4:
                        for i in range(0, len(vertices), 4):
                            quad_pts = vertices[i : i + 4]
                            if len(quad_pts) == 4:
                                min_x = min(p[0] for p in quad_pts)
                                max_x = max(p[0] for p in quad_pts)
                                min_y = min(p[1] for p in quad_pts)
                                max_y = max(p[1] for p in quad_pts)
                                if (min_x - 3) <= pt.x <= (max_x + 3) and (min_y - 3) <= pt.y <= (max_y + 3):
                                    return annot
                    else:
                        return annot
            annot = annot.next

        return None

    @staticmethod
    def _resolve_annot(page: fitz.Page, annot_or_xref: fitz.Annot | int) -> fitz.Annot | None:
        """Helper to resolve a fitz.Annot bound to the given page."""
        if isinstance(annot_or_xref, int):
            try:
                return page.load_annot(annot_or_xref)
            except Exception:
                pass
        elif getattr(annot_or_xref, "xref", None):
            try:
                return page.load_annot(annot_or_xref.xref)
            except Exception:
                return annot_or_xref
        return annot_or_xref

    @staticmethod
    def update_geometry(
        page: fitz.Page, annot_or_xref: fitz.Annot | int, new_line_rects: list[fitz.Rect]
    ) -> fitz.Annot:
        """Replace an existing annotation's geometry with new line rects.

        Args:
            page: PyMuPDF page containing the annotation.
            annot_or_xref: Existing annotation or its xref ID to replace.
            new_line_rects: New bounding rects.

        Returns:
            The newly created fitz.Annot with updated geometry.
        """
        if not new_line_rects:
            raise ValueError("No selection rects provided for updating geometry.")

        import fitz

        annot = AnnotationManager._resolve_annot(page, annot_or_xref)
        if annot is None:
            raise ValueError(f"Annotation {annot_or_xref} not found on page.")

        annot_type = annot.type[0]
        colors = annot.colors or {}
        stroke = colors.get("stroke", (1.0, 1.0, 0.0))
        opacity = annot.opacity if annot.opacity >= 0 else 1.0

        page.delete_annot(annot)

        quads = [r.quad for r in new_line_rects]
        if annot_type == fitz.PDF_ANNOT_UNDERLINE:
            new_annot = page.add_underline_annot(quads)
        else:
            new_annot = page.add_highlight_annot(quads)

        new_annot.set_colors(stroke=stroke)
        new_annot.set_opacity(opacity)
        new_annot.update()
        return new_annot

    @staticmethod
    def delete_annot(page: fitz.Page, annot_or_xref: fitz.Annot | int) -> bool:
        """Delete an annotation safely from the page.

        Args:
            page: PyMuPDF page.
            annot_or_xref: Annotation or its xref ID to remove.

        Returns:
            True if deleted successfully, False otherwise.
        """
        try:
            annot = AnnotationManager._resolve_annot(page, annot_or_xref)
            if annot is not None:
                page.delete_annot(annot)
                return True
            return False
        except Exception as exc:
            log.error("Failed to delete annotation: %s", exc)
            return False
