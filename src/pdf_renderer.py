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

from .constants import DEFAULT_ZOOM, PAGE_SPACING

log = logging.getLogger(__name__)


class PdfRenderer:
    """Manages the rendering of PDF pages using PyMuPDF and GdkPixbuf."""

    def __init__(self) -> None:
        self.doc: fitz.Document | None = None
        self.zoom: float = DEFAULT_ZOOM
        self.page_w: int = 0
        self.page_h: int = 0
        self.page_widgets: list[dict[str, Any]] = []

    def set_document(self, doc: fitz.Document) -> None:
        """Set the active PyMuPDF document."""
        self.doc = doc
        self.page_widgets.clear()
        if self.doc and len(self.doc) > 0:
            # Pre-calculate first page size to use as default dimensions
            first_page = self.doc.load_page(0)
            first_pix = first_page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
            self.page_w = first_pix.width
            self.page_h = first_pix.height

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
        
        # Remove any existing children of pages_box
        child = pages_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            pages_box.remove(child)
            child = next_child

        for i in range(len(self.doc)):
            overlay = Gtk.Overlay()
            overlay.set_halign(Gtk.Align.CENTER)
            overlay.set_valign(Gtk.Align.CENTER)
            overlay.add_css_class("pdf-page-shadow")

            picture = Gtk.Picture()
            picture.set_can_shrink(False)
            picture.set_halign(Gtk.Align.START)
            picture.set_valign(Gtk.Align.START)
            picture.set_size_request(self.page_w, self.page_h)
            overlay.set_child(picture)

            drawing_area = Gtk.DrawingArea()
            drawing_area.set_halign(Gtk.Align.START)
            drawing_area.set_valign(Gtk.Align.START)
            drawing_area.set_content_width(self.page_w)
            drawing_area.set_content_height(self.page_h)
            
            # Draw func signature: (drawing_area, cr, width, height, page_idx)
            drawing_area.set_draw_func(on_draw_func, i)
            overlay.add_overlay(drawing_area)

            drag = Gtk.GestureDrag()
            drag.connect("drag-begin", on_drag_begin, i)
            drag.connect("drag-update", on_drag_update, i)
            drag.connect("drag-end", on_drag_end, i)
            drawing_area.add_controller(drag)

            pages_box.append(overlay)

            self.page_widgets.append({
                "overlay": overlay,
                "picture": picture,
                "drawing_area": drawing_area,
                "words": [],
                "rendered": False,
            })

        return self.page_widgets

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

        h_with_spacing = self.page_h + PAGE_SPACING
        
        start_idx = max(0, int(scroll_y / h_with_spacing) - 1)
        end_idx = min(len(self.doc) - 1, int((scroll_y + viewport_h) / h_with_spacing) + 1)

        for i in range(start_idx, end_idx + 1):
            page_data = self.page_widgets[i]
            if not page_data["rendered"]:
                page_data["rendered"] = True
                pixbuf = self.render_page_pixbuf(i)
                if pixbuf:
                    page_data["picture"].set_pixbuf(pixbuf)
                    page_data["picture"].set_size_request(pixbuf.get_width(), pixbuf.get_height())
                    page_data["drawing_area"].set_content_width(pixbuf.get_width())
                    page_data["drawing_area"].set_content_height(pixbuf.get_height())
                    
                    # Extract words
                    from .text_selection import TextSelectionHandler
                    page = self.doc.load_page(i)
                    words = TextSelectionHandler.extract_words(page)
                    page_data["words"] = words
                    
                    # Notify application window
                    on_page_rendered(i, words)

        # Detect active page (midpoint of viewport)
        mid_y = scroll_y + (viewport_h / 2)
        active_page = max(0, min(len(self.doc) - 1, int(mid_y / h_with_spacing)))
        return active_page

    def update_continuous_dimensions(self) -> None:
        """Update existing continuous layout page widgets with new zoom sizes."""
        if not self.page_widgets:
            return

        for page_data in self.page_widgets:
            page_data["rendered"] = False
            page_data["picture"].set_pixbuf(None)
            page_data["picture"].set_size_request(self.page_w, self.page_h)
            page_data["drawing_area"].set_content_width(self.page_w)
            page_data["drawing_area"].set_content_height(self.page_h)
            page_data["words"] = []
