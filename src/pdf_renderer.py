"""PDF Rendering logic for single-page and continuous view modes."""

from __future__ import annotations

import logging
from typing import Any, Callable

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GdkPixbuf, GLib, Gtk

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from .constants import DEFAULT_ZOOM, PAGE_SHADOW_VERTICAL_CHROME, PAGE_SPACING

log = logging.getLogger(__name__)


class PdfRenderer:
    """Manages the rendering of PDF pages using PyMuPDF and GdkPixbuf."""

    def __init__(self) -> None:
        self.doc: fitz.Document | None = None
        self.zoom: float = DEFAULT_ZOOM
        self.page_w: int = 0
        self.page_h: int = 0
        self.page_heights: list[int] = []
        self.page_widgets: list[dict[str, Any]] = []

    def set_document(self, doc: fitz.Document) -> None:
        """Set the active PyMuPDF document."""
        self.doc = doc
        self.page_widgets.clear()
        self.page_heights.clear()
        if self.doc and len(self.doc) > 0:
            # Pre-calculate first page size to use as default dimensions
            first_page = self.doc.load_page(0)
            first_pix = first_page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
            self.page_w = first_pix.width
            self.page_h = first_pix.height

    def _get_page_pixel_size(self, page_idx: int) -> tuple[int, int]:
        """Return (width, height) in pixels at the current zoom for *page_idx*."""
        if self.doc and 0 <= page_idx < len(self.doc):
            page = self.doc.load_page(page_idx)
            rect = getattr(page, "rect", None)
            w = getattr(rect, "width", None)
            h = getattr(rect, "height", None)
            if isinstance(w, (int, float)) and isinstance(h, (int, float)):
                return (
                    max(1, int(round(w * self.zoom))),
                    max(1, int(round(h * self.zoom))),
                )
        return (self.page_w, self.page_h)

    def set_zoom(self, zoom: float) -> None:
        """Update zoom factor and recalculate page dimensions."""
        self.zoom = zoom
        if self.doc and len(self.doc) > 0:
            first_page = self.doc.load_page(0)
            first_pix = first_page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
            self.page_w = first_pix.width
            self.page_h = first_pix.height

    def render_page_pixbuf(self, page_idx: int) -> GdkPixbuf.Pixbuf | None:
        """Render a single page at the current zoom level to GdkPixbuf."""
        if not self.doc:
            return None
        try:
            page = self.doc.load_page(page_idx)
            pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False, annots=True)
            
            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(pix.tobytes("png"))
            loader.close()
            return loader.get_pixbuf()
        except Exception as exc:
            log.error("Failed to render page %d: %s", page_idx, exc)
            return None

    def setup_continuous_layout(
        self,
        pages_box: Gtk.Box,
        on_draw_func: Callable[[Gtk.DrawingArea, Any, int, int, int], None],
        on_drag_begin: Callable[[Gtk.GestureDrag, float, float, int], None],
        on_drag_update: Callable[[Gtk.GestureDrag, float, float, int], None],
        on_drag_end: Callable[[Gtk.GestureDrag, float, float, int], None]
    ) -> list[dict[str, Any]]:
        """Construct the widget hierarchy inside a GtkBox for continuous scrolling."""
        if not self.doc:
            return []

        self.page_widgets.clear()
        self.page_heights.clear()
        
        # Remove any existing children of pages_box
        child = pages_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            pages_box.remove(child)
            child = next_child

        for i in range(len(self.doc)):
            pw, ph = self._get_page_pixel_size(i)

            overlay = Gtk.Overlay()
            overlay.set_halign(Gtk.Align.CENTER)
            overlay.set_valign(Gtk.Align.CENTER)
            overlay.add_css_class("pdf-page-shadow")

            picture = Gtk.Picture()
            picture.set_can_shrink(False)
            picture.set_halign(Gtk.Align.START)
            picture.set_valign(Gtk.Align.START)
            picture.set_size_request(pw, ph)
            overlay.set_child(picture)

            drawing_area = Gtk.DrawingArea()
            drawing_area.set_halign(Gtk.Align.START)
            drawing_area.set_valign(Gtk.Align.START)
            drawing_area.set_content_width(pw)
            drawing_area.set_content_height(ph)
            
            # Draw func signature: (drawing_area, cr, width, height, page_idx)
            drawing_area.set_draw_func(on_draw_func, i)
            overlay.add_overlay(drawing_area)

            drag = Gtk.GestureDrag()
            drag.connect("drag-begin", on_drag_begin, i)
            drag.connect("drag-update", on_drag_update, i)
            drag.connect("drag-end", on_drag_end, i)
            drawing_area.add_controller(drag)

            pages_box.append(overlay)

            self.page_heights.append(ph)
            self.page_widgets.append({
                "overlay": overlay,
                "picture": picture,
                "drawing_area": drawing_area,
                "width": pw,
                "height": ph,
                "words": [],
                "rendered": False,
            })

        return self.page_widgets

    def ensure_page_rendered(
        self,
        page_idx: int,
        on_page_rendered: Callable[[int, list[dict]], None],
    ) -> None:
        """Render *page_idx* immediately if it has not been rendered yet."""
        if not self.doc or not (0 <= page_idx < len(self.page_widgets)):
            return

        page_data = self.page_widgets[page_idx]
        if page_data["rendered"]:
            return

        page_data["rendered"] = True
        pixbuf = self.render_page_pixbuf(page_idx)
        if pixbuf:
            pw = pixbuf.get_width()
            ph = pixbuf.get_height()
            page_data["picture"].set_pixbuf(pixbuf)
            page_data["picture"].set_size_request(pw, ph)
            page_data["drawing_area"].set_content_width(pw)
            page_data["drawing_area"].set_content_height(ph)
            page_data["width"] = pw
            page_data["height"] = ph
            if 0 <= page_idx < len(self.page_heights):
                self.page_heights[page_idx] = ph

            # Extract words
            from .text_selection import TextSelectionHandler
            page = self.doc.load_page(page_idx)
            words = TextSelectionHandler.extract_words(page)
            page_data["words"] = words

            # Notify application window
            on_page_rendered(page_idx, words)

    def lazy_render_visible_pages(
        self,
        scroll_y: float,
        viewport_h: float,
        on_page_rendered: Callable[[int, list[dict]], None]
    ) -> int:
        """Scan page positions and render pages currently visible in viewport.
        
        Returns the index of the page occupying the center of the viewport.
        """
        if not self.doc or not self.page_widgets:
            return 0

        mid_y = scroll_y + (viewport_h / 2.0)
        viewport_bottom = scroll_y + viewport_h

        y = float(PAGE_SPACING)
        visible_indices: list[int] = []
        active_page: int | None = None
        num_pages = len(self.page_widgets)

        for i, page_data in enumerate(self.page_widgets):
            ph = page_data.get("height", self.page_h)
            if not isinstance(ph, (int, float)) or ph <= 0:
                ph = self.page_h

            page_start = y
            page_end = y + ph + PAGE_SHADOW_VERTICAL_CHROME
            y = page_end + PAGE_SPACING

            if page_end >= scroll_y and page_start <= viewport_bottom:
                visible_indices.append(i)

            if active_page is None and mid_y <= (page_end + PAGE_SPACING / 2.0):
                active_page = i

        if active_page is None:
            active_page = num_pages - 1

        if visible_indices:
            start_idx = max(0, visible_indices[0] - 1)
            end_idx = min(num_pages - 1, visible_indices[-1] + 1)
        else:
            start_idx = max(0, active_page - 1)
            end_idx = min(num_pages - 1, active_page + 1)

        for i in range(start_idx, end_idx + 1):
            self.ensure_page_rendered(i, on_page_rendered)

        return active_page

    def update_continuous_dimensions(self) -> None:
        """Update existing continuous layout page widgets with new zoom sizes."""
        if not self.page_widgets:
            return

        self.page_heights.clear()
        for i, page_data in enumerate(self.page_widgets):
            pw, ph = self._get_page_pixel_size(i)
            page_data["rendered"] = False
            page_data["picture"].set_pixbuf(None)
            page_data["picture"].set_size_request(pw, ph)
            page_data["drawing_area"].set_content_width(pw)
            page_data["drawing_area"].set_content_height(ph)
            page_data["width"] = pw
            page_data["height"] = ph
            page_data["words"] = []
            self.page_heights.append(ph)
