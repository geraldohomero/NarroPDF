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

        xrefs = []
        if annotation_type == AnnotationType.HIGHLIGHT:
            for rect in line_rects:
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=color)
                annot.set_opacity(opacity)
                annot.update()
                xrefs.append(annot.xref)
            return "Highlight", xrefs

        elif annotation_type == AnnotationType.UNDERLINE:
            for rect in line_rects:
                annot = page.add_underline_annot(rect)
                annot.set_colors(stroke=color)
                annot.set_opacity(opacity)
                annot.update()
                xrefs.append(annot.xref)
            return "Underline", xrefs

        elif annotation_type == AnnotationType.NOTE:
            annot = page.add_text_annot(
                line_rects[0].tl, "Nota criada no editor"
            )
            annot.set_colors(stroke=color)
            annot.set_opacity(opacity)
            annot.update()
            xrefs.append(annot.xref)
            return "Nota", xrefs

        else:
            raise ValueError(f"Unknown annotation type: {annotation_type}")
