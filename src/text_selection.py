"""Text selection handling for PDF word-level selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz

from .constants import WORD_HIT_THRESHOLD_PX


class TextSelectionHandler:
    """Manages word-level text selection on a rendered PDF page.

    This class unifies the selection logic that was previously duplicated
    between single-page and continuous-scroll modes.
    """

    def __init__(self) -> None:
        self.page_words: list[dict] = []
        self.selection_range: tuple[int, int] | None = None
        self.drag_start_index: int | None = None

    def set_words(self, words: list[dict]) -> None:
        """Replace the current word list (called on page change)."""
        self.page_words = words
        self.clear_selection()

    def clear_selection(self) -> None:
        """Clear any active selection."""
        self.selection_range = None
        self.drag_start_index = None

    # ------------------------------------------------------------------
    # Drag handling
    # ------------------------------------------------------------------

    def begin_drag(self, screen_x: float, screen_y: float, zoom: float) -> bool:
        """Start a drag operation. Returns True if a word was hit."""
        idx = self._word_index_at(screen_x, screen_y, zoom)
        if idx is None:
            self.clear_selection()
            return False
        self.drag_start_index = idx
        self.selection_range = (idx, idx)
        return True

    def update_drag(
        self, offset_x: float, offset_y: float, zoom: float
    ) -> bool:
        """Update drag with offset from start. Returns True if selection changed."""
        if self.drag_start_index is None:
            return False

        start_rect = self.page_words[self.drag_start_index]["rect"]
        start_x = ((start_rect.x0 + start_rect.x1) / 2) * zoom
        start_y = ((start_rect.y0 + start_rect.y1) / 2) * zoom

        current_idx = self._word_index_at(
            start_x + offset_x, start_y + offset_y, zoom
        )
        if current_idx is None:
            current_idx = self.drag_start_index

        self.selection_range = (self.drag_start_index, current_idx)
        return True

    def end_drag(
        self, offset_x: float, offset_y: float, zoom: float
    ) -> bool:
        """Finish drag. Returns True if there's a valid selection."""
        if self.drag_start_index is None:
            return False

        self.update_drag(offset_x, offset_y, zoom)
        self.drag_start_index = None
        return self.has_selection

    # ------------------------------------------------------------------
    # Selection queries
    # ------------------------------------------------------------------

    @property
    def has_selection(self) -> bool:
        return self.selection_range is not None

    def get_selected_bounds(self) -> tuple[int, int] | None:
        """Return (lo, hi) indices of selected words, or None."""
        if not self.selection_range:
            return None
        i0, i1 = self.selection_range
        if i0 is None or i1 is None:
            return None
        lo = max(0, min(i0, i1))
        hi = min(len(self.page_words) - 1, max(i0, i1))
        if hi < lo:
            return None
        return lo, hi

    def set_selection_bounds(self, lo: int, hi: int) -> None:
        """Explicitly set selection range to [lo, hi]."""
        if not self.page_words:
            self.clear_selection()
            return
        lo = max(0, min(lo, len(self.page_words) - 1))
        hi = max(0, min(hi, len(self.page_words) - 1))
        self.selection_range = (lo, hi)

    def get_handle_positions(
        self, zoom: float
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return screen coordinates of (start_handle, end_handle) for current selection."""
        bounds = self.get_selected_bounds()
        if not bounds or not self.page_words:
            return None
        lo, hi = bounds
        start_rect = self.page_words[lo]["rect"]
        end_rect = self.page_words[hi]["rect"]
        start_pt = (start_rect.x0 * zoom, start_rect.y0 * zoom)
        end_pt = (end_rect.x1 * zoom, end_rect.y1 * zoom)
        return start_pt, end_pt

    def get_selected_words(self) -> list[dict]:
        """Return the list of selected word dicts."""
        bounds = self.get_selected_bounds()
        if not bounds:
            return []
        lo, hi = bounds
        return self.page_words[lo : hi + 1]

    def get_selected_text(self) -> str:
        """Build a readable text string from the selected words."""
        selected = self.get_selected_words()
        if not selected:
            return ""

        parts: list[str] = []
        prev_block = None
        prev_line = None

        for item in selected:
            block = item["block"]
            line = item["line"]

            if prev_block is None:
                parts.append(item["text"])
            elif block != prev_block:
                parts.append("\n\n" + item["text"])
            elif line != prev_line:
                parts.append("\n" + item["text"])
            else:
                parts.append(" " + item["text"])

            prev_block = block
            prev_line = line

        return "".join(parts)

    def get_selected_line_rects(self) -> list:
        """Merge selected words into per-line rectangles for annotations."""
        import fitz

        selected = self.get_selected_words()
        if not selected:
            return []

        groups: dict[tuple[int, int], list[float]] = {}
        for item in selected:
            key = (item["block"], item["line"])
            rect = item["rect"]
            if key not in groups:
                groups[key] = [rect.x0, rect.y0, rect.x1, rect.y1]
            else:
                groups[key][0] = min(groups[key][0], rect.x0)
                groups[key][1] = min(groups[key][1], rect.y0)
                groups[key][2] = max(groups[key][2], rect.x1)
                groups[key][3] = max(groups[key][3], rect.y1)

        return [
            fitz.Rect(*groups[key]) for key in sorted(groups.keys())
        ]

    # ------------------------------------------------------------------
    # Word lookup
    # ------------------------------------------------------------------

    def _word_index_at(
        self, screen_x: float, screen_y: float, zoom: float
    ) -> int | None:
        """Find the word index at the given screen coordinates."""
        if not self.page_words:
            return None

        px = screen_x / zoom
        py = screen_y / zoom

        # Exact hit test
        for idx, item in enumerate(self.page_words):
            rect = item["rect"]
            if rect.x0 <= px <= rect.x1 and rect.y0 <= py <= rect.y1:
                return idx

        # Proximity fallback
        threshold = WORD_HIT_THRESHOLD_PX / zoom
        best_idx = None
        best_dist2 = None

        for idx, item in enumerate(self.page_words):
            rect = item["rect"]
            cx = (rect.x0 + rect.x1) / 2
            cy = (rect.y0 + rect.y1) / 2
            dx = px - cx
            dy = py - cy
            dist2 = dx * dx + dy * dy

            if best_dist2 is None or dist2 < best_dist2:
                best_dist2 = dist2
                best_idx = idx

        if best_dist2 is not None and best_dist2 <= threshold * threshold:
            return best_idx

        return None

    # ------------------------------------------------------------------
    # Static helpers for word extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_words(page) -> list[dict]:
        """Extract and sort words from a PyMuPDF page."""
        import fitz

        raw_words = page.get_text("words")
        words = [
            {
                "rect": fitz.Rect(w[0], w[1], w[2], w[3]),
                "text": w[4],
                "block": w[5],
                "line": w[6],
                "word": w[7],
            }
            for w in raw_words
        ]
        words.sort(key=lambda item: (item["block"], item["line"], item["word"]))
        return words

    def find_word_range_for_vertices(
        self, vertices: list
    ) -> tuple[int, int] | None:
        """Find the (lo, hi) word indices in page_words covered by annotation vertices."""
        if not self.page_words or not vertices:
            return None

        import fitz

        # Reconstruct quad rectangles from vertices
        quad_rects: list[fitz.Rect] = []
        for i in range(0, len(vertices), 4):
            pts = vertices[i : i + 4]
            if len(pts) == 4:
                min_x = min(p[0] for p in pts)
                max_x = max(p[0] for p in pts)
                min_y = min(p[1] for p in pts)
                max_y = max(p[1] for p in pts)
                quad_rects.append(fitz.Rect(min_x, min_y, max_x, max_y))

        if not quad_rects:
            return None

        matching_indices = []
        for idx, item in enumerate(self.page_words):
            w_rect = item["rect"]
            for q_rect in quad_rects:
                intersection = w_rect & q_rect
                if not intersection.is_empty and intersection.width > 1 and intersection.height > 1:
                    matching_indices.append(idx)
                    break
                # Fallback to center point proximity
                mid_x = (w_rect.x0 + w_rect.x1) / 2
                mid_y = (w_rect.y0 + w_rect.y1) / 2
                if q_rect.x0 - 2 <= mid_x <= q_rect.x1 + 2 and q_rect.y0 - 2 <= mid_y <= q_rect.y1 + 2:
                    matching_indices.append(idx)
                    break

        if not matching_indices:
            return None

        return min(matching_indices), max(matching_indices)
