from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz

from .constants import AnnotationType

log = logging.getLogger(__name__)


@dataclass
class AnnotationSnapshot:
    """Serializable snapshot of an annotation's state."""
    page_idx: int
    annot_type: AnnotationType
    line_rects: list[fitz.Rect]
    color: tuple[float, float, float]
    opacity: float = 1.0
    content: str = ""


@dataclass
class AnnotationCommand:
    """Action recorded for Undo and Redo operations."""
    action: str  # "create", "delete", "modify"
    page_idx: int
    before: AnnotationSnapshot | None = None
    after: AnnotationSnapshot | None = None
    current_xref: int | None = None


class AnnotationManager:
    """Applies annotations to PDF pages using PyMuPDF."""

    @staticmethod
    def apply(
        page: fitz.Page,
        annotation_type: AnnotationType,
        line_rects: list[fitz.Rect],
        color: tuple[float, float, float],
        opacity: float = 1.0,
        content: str = "",
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
            text_content = content if content else "Nota criada no editor"
            annot = page.add_text_annot(
                line_rects[0].tl, text_content
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

    @staticmethod
    def snapshot_from_annot(
        page: fitz.Page, page_idx: int, annot_or_xref: fitz.Annot | int
    ) -> AnnotationSnapshot | None:
        """Create an AnnotationSnapshot from an existing annotation."""
        import fitz

        annot = AnnotationManager._resolve_annot(page, annot_or_xref)
        if annot is None:
            return None

        # Resolve annotation type
        t_val = annot.type[0]
        if t_val == fitz.PDF_ANNOT_UNDERLINE:
            annot_type = AnnotationType.UNDERLINE
        elif t_val == fitz.PDF_ANNOT_TEXT:
            annot_type = AnnotationType.NOTE
        else:
            annot_type = AnnotationType.HIGHLIGHT

        # Reconstruct line rects
        line_rects: list[fitz.Rect] = []
        vertices = annot.vertices
        if vertices and len(vertices) >= 4:
            for i in range(0, len(vertices), 4):
                pts = vertices[i : i + 4]
                if len(pts) == 4:
                    x0 = min(p[0] for p in pts)
                    y0 = min(p[1] for p in pts)
                    x1 = max(p[0] for p in pts)
                    y1 = max(p[1] for p in pts)
                    line_rects.append(fitz.Rect(x0, y0, x1, y1))
        if not line_rects:
            line_rects = [annot.rect]

        colors = annot.colors or {}
        stroke = colors.get("stroke") or (1.0, 1.0, 0.0)
        opacity = annot.opacity if annot.opacity >= 0 else 1.0
        content = (annot.info or {}).get("content", "")

        return AnnotationSnapshot(
            page_idx=page_idx,
            annot_type=annot_type,
            line_rects=line_rects,
            color=(stroke[0], stroke[1], stroke[2]) if len(stroke) >= 3 else (1.0, 1.0, 0.0),
            opacity=opacity,
            content=content,
        )

    @staticmethod
    def restore_snapshot(page: fitz.Page, snapshot: AnnotationSnapshot) -> int:
        """Restore an annotation from a snapshot onto the page. Returns its new xref."""
        _, xrefs = AnnotationManager.apply(
            page=page,
            annotation_type=snapshot.annot_type,
            line_rects=snapshot.line_rects,
            color=snapshot.color,
            opacity=snapshot.opacity,
            content=snapshot.content,
        )
        return xrefs[0]

    @staticmethod
    def list_all_annotations(doc: fitz.Document) -> list[dict]:
        """Extract and summarize all annotations across all pages in the document."""
        import fitz

        results: list[dict] = []
        if not doc:
            return results

        for page_idx in range(len(doc)):
            try:
                page = doc.load_page(page_idx)
                for annot in page.annots():
                    t_val = annot.type[0]
                    if t_val == fitz.PDF_ANNOT_UNDERLINE:
                        type_name = "Underline"
                        annot_type = AnnotationType.UNDERLINE
                    elif t_val == fitz.PDF_ANNOT_TEXT:
                        type_name = "Note"
                        annot_type = AnnotationType.NOTE
                    elif t_val == fitz.PDF_ANNOT_HIGHLIGHT:
                        type_name = "Highlight"
                        annot_type = AnnotationType.HIGHLIGHT
                    else:
                        continue

                    rect = annot.rect
                    info = annot.info or {}
                    content = info.get("content", "").strip()

                    # Extract underlying page text for highlights and underlines
                    if not content and annot_type in (AnnotationType.HIGHLIGHT, AnnotationType.UNDERLINE):
                        content = page.get_textbox(rect).strip()

                    if not content:
                        content = type_name

                    colors = annot.colors or {}
                    stroke = colors.get("stroke") or (1.0, 1.0, 0.0)
                    color = (stroke[0], stroke[1], stroke[2]) if len(stroke) >= 3 else (1.0, 1.0, 0.0)
                    opacity = annot.opacity if annot.opacity >= 0 else 1.0

                    results.append({
                        "page_idx": page_idx,
                        "xref": annot.xref,
                        "type_name": type_name,
                        "annot_type": annot_type,
                        "text": content,
                        "rect": rect,
                        "color": color,
                        "opacity": opacity,
                    })
            except Exception as exc:
                log.error("Failed to extract annotations for page %d: %s", page_idx, exc)

        return results

