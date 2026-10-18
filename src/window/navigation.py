"""Navigation, zoom control, and PDF rendering orchestration for MainWindow."""

import os
import logging
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gio, GObject, Gtk

try:
    import fitz
except ImportError:
    fitz = None

from ..constants import (
    DEFAULT_ZOOM,
    MIN_ZOOM,
    MAX_ZOOM,
    ZOOM_STEP,
    ViewMode,
    ToolMode,
)
from ..utils import detect_language_from_text
from ..text_selection import TextSelectionHandler
from ..annotations import AnnotationManager
from ..locale import _

log = logging.getLogger(__name__)


class WindowNavigationMixin:
    """Mixin implementing document loading, view rendering, pagination, and zoom controls."""

    def open_pdf(self, path: str) -> None:
        """Load and display the PDF file at *path*."""
        if not fitz:
            self.set_status(_("err_pymupdf"))
            return

        try:
            if self.renderer.doc:
                self._unparent_popover()
                self.renderer.doc.close()
                self.tts.stop()

            self._clear_search()

            doc = fitz.open(path)
            self.pdf_path = path
            self.current_page = 0
            self.selected_annotation = None
            self.selection.clear_selection()
            self.renderer.set_document(doc)
            self.tts.set_document(doc)
            self.has_unsaved_changes = False
            self.annotation_history.clear()
            self.undo_stack.clear()
            self.redo_stack.clear()
            self._update_save_state()

            # Switch view to layout container if needed
            self.scroller.set_child(None)
            if self.view_mode == ViewMode.CONTINUOUS:
                self._setup_continuous_layout()
            else:
                self.scroller.set_child(self.overlay)

            # Heuristics for language detection
            sample_text = ""
            for i in range(min(3, len(doc))):
                sample_text += doc.load_page(i).get_text("text") or ""
            detected = detect_language_from_text(sample_text)
            self._prompt_document_language(detected)

            # Render
            self._render_view()
            self._reload_left_sidebar()
            self._update_cursor()
            self._update_controls_sensitivity()
            self.set_status(f"PDF aberto: {os.path.basename(path)}")

        except Exception as exc:
            log.error("Failed to load PDF: %s", exc)
            self.set_status(f"{_('err_open_pdf')}: {exc}")

    def _render_view(self) -> None:
        if not self.renderer.doc:
            return

        # Update zoom and page count labels
        self.btn_zoom_menu.set_label(f"{int(self.renderer.zoom * 100)}%")
        self.total_pages_label.set_text(f"{_('page_of')} {len(self.renderer.doc)}")

        if self.view_mode == ViewMode.CONTINUOUS:
            self.renderer.update_continuous_dimensions()
            self._on_viewport_scrolled(self.scroller.get_vadjustment())
        else:
            pixbuf = self.renderer.render_page_pixbuf(self.current_page)
            if pixbuf:
                self.picture.set_pixbuf(pixbuf)
                self.picture.set_size_request(pixbuf.get_width(), pixbuf.get_height())
                self.selection_layer.set_content_width(pixbuf.get_width())
                self.selection_layer.set_content_height(pixbuf.get_height())

                # Load words
                page = self.renderer.doc.load_page(self.current_page)
                self.selection.set_words(TextSelectionHandler.extract_words(page))
                
                # Extracted text sidebar
                self.text_buffer.set_text(page.get_text("text") or "")
                self.selection_layer.queue_draw()

            self.page_entry.set_text(str(self.current_page + 1))

    def _navigate_page(self, step: int) -> None:
        if not self.renderer.doc:
            return
        
        target = self.current_page + step
        if 0 <= target < len(self.renderer.doc):
            self.current_page = target
            self._update_controls_sensitivity()
            self.page_entry.set_text(str(self.current_page + 1))

            if self.view_mode == ViewMode.CONTINUOUS:
                h_with_spacing = self.renderer.page_h + 24
                target_y = target * h_with_spacing
                vadj = self.scroller.get_vadjustment()
                self._is_navigating = True
                vadj.set_value(min(target_y, vadj.get_upper() - vadj.get_page_size()))
                self._is_navigating = False
            else:
                self.selected_annotation = None
                self.selection.clear_selection()
                self._render_view()

    # ------------------------------------------------------------------
    # Continuous View Lazy Loading
    # ------------------------------------------------------------------

    def _setup_continuous_layout(self) -> None:
        from ..constants import PAGE_SPACING
        pages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PAGE_SPACING)
        pages_box.set_halign(Gtk.Align.CENTER)
        pages_box.set_margin_top(PAGE_SPACING)
        pages_box.set_margin_bottom(PAGE_SPACING)

        # Call renderer to create structure
        widgets = self.renderer.setup_continuous_layout(
            pages_box,
            self._draw_page_selection_overlay,
            self._on_continuous_drag_begin,
            self._on_continuous_drag_update,
            self._on_continuous_drag_end
        )

        for i, page_data in enumerate(widgets):
            click = Gtk.GestureClick()
            click.connect("pressed", self._on_continuous_click_pressed, i)
            page_data["drawing_area"].add_controller(click)

            motion = Gtk.EventControllerMotion()
            motion.connect("motion", self._on_continuous_selection_motion, i)
            motion.connect("leave", self._on_continuous_selection_motion_leave, i)
            page_data["drawing_area"].add_controller(motion)

        self.scroller.set_child(pages_box)

    def _on_viewport_scrolled(self, vadj: Gtk.Adjustment) -> None:
        if not self.renderer.doc or self.view_mode != ViewMode.CONTINUOUS or self._is_navigating:
            return

        scroll_y = vadj.get_value()
        viewport_h = vadj.get_page_size()

        # Render visible pages
        active = self.renderer.lazy_render_visible_pages(
            scroll_y,
            viewport_h,
            self._on_continuous_page_rendered
        )

        if active != self.current_page:
            self.current_page = active
            self.page_entry.set_text(str(self.current_page + 1))
            self._update_controls_sensitivity()
            
            # Sync extracted text sidebar
            page = self.renderer.doc.load_page(self.current_page)
            self.text_buffer.set_text(page.get_text("text") or "")

            # Sync selection words
            if self.renderer.page_widgets and self.current_page < len(self.renderer.page_widgets):
                self.selection.set_words(self.renderer.page_widgets[self.current_page]["words"])

    def _on_continuous_page_rendered(self, page_idx: int, words: list[dict]) -> None:
        if page_idx == self.current_page:
            self.selection.set_words(words)

    # ------------------------------------------------------------------
    # Drag Selection Handlers
    # ------------------------------------------------------------------

    # Scroller drag (Hand mode)
    def _on_scroller_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        if self.tool_mode == ToolMode.HAND:
            self._initial_scroll_x = self.scroller.get_hadjustment().get_value()
            self._initial_scroll_y = self.scroller.get_vadjustment().get_value()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.scroller.set_cursor(Gdk.Cursor.new_from_name("grabbing", None))

    def _on_scroller_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self.tool_mode == ToolMode.HAND:
            self.scroller.get_hadjustment().set_value(self._initial_scroll_x - offset_x)
            self.scroller.get_vadjustment().set_value(self._initial_scroll_y - offset_y)

    def _on_scroller_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self.tool_mode == ToolMode.HAND:
            self._update_cursor()

    # Single Page Click and Drag
    def _on_single_click_pressed(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        if self.tool_mode != ToolMode.HAND:
            if n_press == 2:
                if getattr(self.tts, "is_playing", False):
                    self._on_pdf_double_clicked(self.current_page, x, y)
                    return
                # Double click: select single word
                self.selected_annotation = None
                hit = self.selection.begin_drag(x, y, self.renderer.zoom)
                if hit:
                    self.selection.end_drag(0, 0, self.renderer.zoom)
                    self._show_selection_popover(self.selection_layer)
                self.selection_layer.queue_draw()
            elif n_press == 1:
                # If clicked on an existing resize handle, don't clear selection!
                if getattr(self, "selected_annotation", None) and self._hit_test_handle(x, y):
                    return

                # Check if hit an existing annotation
                if self.renderer.doc:
                    page = self.renderer.doc.load_page(self.current_page)
                    pt = (x / self.renderer.zoom, y / self.renderer.zoom)
                    annot_hit = AnnotationManager.find_at_point(page, pt)
                    if annot_hit:
                        bounds = self.selection.find_word_range_for_vertices(annot_hit.vertices)
                        if bounds:
                            lo, hi = bounds
                            self.selected_annotation = {
                                "page_idx": self.current_page,
                                "xref": annot_hit.xref,
                                "bounds": (lo, hi),
                            }
                            self.selection.set_selection_bounds(lo, hi)
                            self._show_selection_popover(self.selection_layer)
                            self.selection_layer.queue_draw()
                            return

                # Single click on blank: clear selection
                self.selected_annotation = None
                self.popover.popdown()
                self.selection.clear_selection()
                self.selection_layer.queue_draw()

    def _on_single_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        self._drag_started = False
        self._drag_start_x = start_x
        self._drag_start_y = start_y
        self._handle_drag_mode = None
        if getattr(self, "selected_annotation", None) and self.selected_annotation.get("page_idx") == self.current_page:
            handle = self._hit_test_handle(start_x, start_y)
            if handle in ("start", "end"):
                self._handle_drag_mode = handle
                self._drag_started = True
                self.popover.popdown()
                self.selection_layer.set_cursor(Gdk.Cursor.new_from_name("ew-resize", None))
                if self.renderer.doc:
                    page = self.renderer.doc.load_page(self.current_page)
                    self._resize_before_snapshot = AnnotationManager.snapshot_from_annot(
                        page, self.current_page, self.selected_annotation["xref"]
                    )

    def _on_single_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self.tool_mode != ToolMode.HAND:
            if getattr(self, "_handle_drag_mode", None):
                curr_x = self._drag_start_x + offset_x
                curr_y = self._drag_start_y + offset_y
                target_idx = self.selection._word_index_at(curr_x, curr_y, self.renderer.zoom)
                if target_idx is not None:
                    bounds = self.selection.get_selected_bounds()
                    if bounds:
                        lo, hi = bounds
                        if self._handle_drag_mode == "start":
                            new_lo = min(target_idx, hi)
                            self.selection.set_selection_bounds(new_lo, hi)
                        elif self._handle_drag_mode == "end":
                            new_hi = max(target_idx, lo)
                            self.selection.set_selection_bounds(lo, new_hi)
                        self.selection_layer.queue_draw()
                return

            if not self._drag_started:
                # Start selection only if moved > 4px
                if abs(offset_x) > 4 or abs(offset_y) > 4:
                    self._drag_started = True
                    self.selected_annotation = None
                    self.selection.begin_drag(self._drag_start_x, self._drag_start_y, self.renderer.zoom)
            
            if self._drag_started:
                self.selection.update_drag(offset_x, offset_y, self.renderer.zoom)
                self.selection_layer.queue_draw()

    def _on_single_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self.tool_mode != ToolMode.HAND:
            if getattr(self, "_handle_drag_mode", None):
                self._handle_drag_mode = None
                self._update_cursor()
                sel_annot = getattr(self, "selected_annotation", None)
                if sel_annot and self.renderer.doc:
                    line_rects = self.selection.get_selected_line_rects()
                    if line_rects:
                        try:
                            page = self.renderer.doc.load_page(self.current_page)
                            new_annot = AnnotationManager.update_geometry(page, sel_annot["xref"], line_rects)
                            after_snap = AnnotationManager.snapshot_from_annot(page, self.current_page, new_annot.xref)
                            if getattr(self, "_resize_before_snapshot", None) and after_snap:
                                from ..annotations import AnnotationCommand
                                self._record_annotation_command(
                                    AnnotationCommand(
                                        action="modify",
                                        page_idx=self.current_page,
                                        before=self._resize_before_snapshot,
                                        after=after_snap,
                                        current_xref=new_annot.xref,
                                    )
                                )
                            self._resize_before_snapshot = None
                            bounds = self.selection.get_selected_bounds()
                            self.selected_annotation = {
                                "page_idx": self.current_page,
                                "xref": new_annot.xref,
                                "bounds": bounds or (0, 0),
                            }
                            self.has_unsaved_changes = True
                            self._update_save_state()
                            self._render_view()
                            if bounds:
                                self.selection.set_selection_bounds(bounds[0], bounds[1])
                        except Exception as exc:
                            log.error("Failed to update annotation geometry on single drag end: %s", exc)
                self._show_selection_popover(self.selection_layer)
                self.selection_layer.queue_draw()
                return

            if self._drag_started:
                has_sel = self.selection.end_drag(offset_x, offset_y, self.renderer.zoom)
                if has_sel:
                    self._show_selection_popover(self.selection_layer)
                self.selection_layer.queue_draw()

    def _on_selection_motion(self, controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        if getattr(self, "_handle_drag_mode", None):
            self.selection_layer.set_cursor(Gdk.Cursor.new_from_name("ew-resize", None))
            return

        sel_annot = getattr(self, "selected_annotation", None)
        if sel_annot and sel_annot.get("page_idx") == self.current_page:
            handle = self._hit_test_handle(x, y)
            if handle in ("start", "end"):
                self.selection_layer.set_cursor(Gdk.Cursor.new_from_name("ew-resize", None))
                return

        self._update_cursor()

    def _on_selection_motion_leave(self, controller: Gtk.EventControllerMotion) -> None:
        if not getattr(self, "_handle_drag_mode", None):
            self._update_cursor()

    # Continuous Page Click and Drag
    def _on_continuous_click_pressed(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, page_idx: int) -> None:
        if self.tool_mode != ToolMode.HAND:
            if n_press == 2:
                if getattr(self.tts, "is_playing", False):
                    self._on_pdf_double_clicked(page_idx, x, y)
                    return
                # Sync active page states without scrolling viewport
                self.current_page = page_idx
                self._update_controls_sensitivity()
                self.page_entry.set_text(str(self.current_page + 1))
                page = self.renderer.doc.load_page(page_idx)
                self.text_buffer.set_text(page.get_text("text") or "")
                
                if self.renderer.page_widgets and page_idx < len(self.renderer.page_widgets):
                    self.selection.set_words(self.renderer.page_widgets[page_idx]["words"])
                    
                self.selected_annotation = None
                hit = self.selection.begin_drag(x, y, self.renderer.zoom)
                if hit:
                    self.selection.end_drag(0, 0, self.renderer.zoom)
                    widget = self.renderer.page_widgets[page_idx]["drawing_area"]
                    self._show_selection_popover(widget)
                
                for page_data in self.renderer.page_widgets:
                    page_data["drawing_area"].queue_draw()
            elif n_press == 1:
                # If clicked on an existing resize handle, don't clear selection!
                if getattr(self, "selected_annotation", None) and self._hit_test_handle(x, y):
                    return

                if self.renderer.doc:
                    page = self.renderer.doc.load_page(page_idx)
                    pt = (x / self.renderer.zoom, y / self.renderer.zoom)
                    annot_hit = AnnotationManager.find_at_point(page, pt)
                    if annot_hit:
                        self.current_page = page_idx
                        self._update_controls_sensitivity()
                        self.page_entry.set_text(str(self.current_page + 1))
                        if self.renderer.page_widgets and page_idx < len(self.renderer.page_widgets):
                            self.selection.set_words(self.renderer.page_widgets[page_idx]["words"])
                        bounds = self.selection.find_word_range_for_vertices(annot_hit.vertices)
                        if bounds:
                            lo, hi = bounds
                            self.selected_annotation = {
                                "page_idx": page_idx,
                                "xref": annot_hit.xref,
                                "bounds": (lo, hi),
                            }
                            self.selection.set_selection_bounds(lo, hi)
                            widget = self.renderer.page_widgets[page_idx]["drawing_area"]
                            self._show_selection_popover(widget)
                            for page_data in self.renderer.page_widgets:
                                page_data["drawing_area"].queue_draw()
                            return

                self.selected_annotation = None
                self.popover.popdown()
                self.selection.clear_selection()
                for page_data in self.renderer.page_widgets:
                    page_data["drawing_area"].queue_draw()

    def _on_continuous_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float, page_idx: int) -> None:
        self._drag_started = False
        self._drag_start_x = start_x
        self._drag_start_y = start_y
        self._drag_page_idx = page_idx
        self._handle_drag_mode = None
        if getattr(self, "selected_annotation", None) and self.selected_annotation.get("page_idx") == page_idx:
            handle = self._hit_test_handle(start_x, start_y)
            if handle in ("start", "end"):
                self._handle_drag_mode = handle
                self._drag_started = True
                self.popover.popdown()
                if self.renderer.page_widgets and page_idx < len(self.renderer.page_widgets):
                    widget = self.renderer.page_widgets[page_idx]["drawing_area"]
                    widget.set_cursor(Gdk.Cursor.new_from_name("ew-resize", None))
                if self.renderer.doc:
                    page = self.renderer.doc.load_page(page_idx)
                    self._resize_before_snapshot = AnnotationManager.snapshot_from_annot(
                        page, page_idx, self.selected_annotation["xref"]
                    )

    def _on_continuous_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float, page_idx: int) -> None:
        if self.tool_mode != ToolMode.HAND:
            if getattr(self, "_handle_drag_mode", None):
                curr_x = self._drag_start_x + offset_x
                curr_y = self._drag_start_y + offset_y
                target_idx = self.selection._word_index_at(curr_x, curr_y, self.renderer.zoom)
                if target_idx is not None:
                    bounds = self.selection.get_selected_bounds()
                    if bounds:
                        lo, hi = bounds
                        if self._handle_drag_mode == "start":
                            new_lo = min(target_idx, hi)
                            self.selection.set_selection_bounds(new_lo, hi)
                        elif self._handle_drag_mode == "end":
                            new_hi = max(target_idx, lo)
                            self.selection.set_selection_bounds(lo, new_hi)
                        for page_data in self.renderer.page_widgets:
                            page_data["drawing_area"].queue_draw()
                return

            if not self._drag_started:
                if abs(offset_x) > 4 or abs(offset_y) > 4:
                    self._drag_started = True
                    self.selected_annotation = None
                    self.current_page = self._drag_page_idx
                    self._update_controls_sensitivity()
                    self.page_entry.set_text(str(self.current_page + 1))
                    page = self.renderer.doc.load_page(self._drag_page_idx)
                    self.text_buffer.set_text(page.get_text("text") or "")
                    
                    if self.renderer.page_widgets and self._drag_page_idx < len(self.renderer.page_widgets):
                        self.selection.set_words(self.renderer.page_widgets[self._drag_page_idx]["words"])
                        
                    self.selection.begin_drag(self._drag_start_x, self._drag_start_y, self.renderer.zoom)
            
            if self._drag_started:
                self.selection.update_drag(offset_x, offset_y, self.renderer.zoom)
                for page_data in self.renderer.page_widgets:
                    page_data["drawing_area"].queue_draw()

    def _on_continuous_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float, page_idx: int) -> None:
        if self.tool_mode != ToolMode.HAND:
            if getattr(self, "_handle_drag_mode", None):
                self._handle_drag_mode = None
                if self.renderer.page_widgets and page_idx < len(self.renderer.page_widgets):
                    widget = self.renderer.page_widgets[page_idx]["drawing_area"]
                    if self.tool_mode == ToolMode.HAND:
                        widget.set_cursor(Gdk.Cursor.new_from_name("grab", None))
                    else:
                        widget.set_cursor(Gdk.Cursor.new_from_name("text", None))

                sel_annot = getattr(self, "selected_annotation", None)
                if sel_annot and self.renderer.doc:
                    line_rects = self.selection.get_selected_line_rects()
                    if line_rects:
                        try:
                            page = self.renderer.doc.load_page(self._drag_page_idx)
                            new_annot = AnnotationManager.update_geometry(page, sel_annot["xref"], line_rects)
                            after_snap = AnnotationManager.snapshot_from_annot(page, self._drag_page_idx, new_annot.xref)
                            if getattr(self, "_resize_before_snapshot", None) and after_snap:
                                from ..annotations import AnnotationCommand
                                self._record_annotation_command(
                                    AnnotationCommand(
                                        action="modify",
                                        page_idx=self._drag_page_idx,
                                        before=self._resize_before_snapshot,
                                        after=after_snap,
                                        current_xref=new_annot.xref,
                                    )
                                )
                            self._resize_before_snapshot = None
                            bounds = self.selection.get_selected_bounds()
                            self.selected_annotation = {
                                "page_idx": self._drag_page_idx,
                                "xref": new_annot.xref,
                                "bounds": bounds or (0, 0),
                            }
                            self.has_unsaved_changes = True
                            self._update_save_state()
                            self._render_view()
                            if bounds:
                                self.selection.set_selection_bounds(bounds[0], bounds[1])
                        except Exception as exc:
                            log.error("Failed to update annotation geometry on continuous drag end: %s", exc)
                if self.renderer.page_widgets and self._drag_page_idx < len(self.renderer.page_widgets):
                    widget = self.renderer.page_widgets[self._drag_page_idx]["drawing_area"]
                    self._show_selection_popover(widget)
                for page_data in self.renderer.page_widgets:
                    page_data["drawing_area"].queue_draw()
                return

            if self._drag_started:
                has_sel = self.selection.end_drag(offset_x, offset_y, self.renderer.zoom)
                if has_sel:
                    widget = self.renderer.page_widgets[self._drag_page_idx]["drawing_area"]
                    self._show_selection_popover(widget)
                for page_data in self.renderer.page_widgets:
                    page_data["drawing_area"].queue_draw()

    def _on_continuous_selection_motion(self, controller: Gtk.EventControllerMotion, x: float, y: float, page_idx: int) -> None:
        widget = controller.get_widget()
        if getattr(self, "_handle_drag_mode", None):
            widget.set_cursor(Gdk.Cursor.new_from_name("ew-resize", None))
            return

        sel_annot = getattr(self, "selected_annotation", None)
        if sel_annot and sel_annot.get("page_idx") == page_idx:
            handle = self._hit_test_handle(x, y)
            if handle in ("start", "end"):
                widget.set_cursor(Gdk.Cursor.new_from_name("ew-resize", None))
                return

        if self.tool_mode == ToolMode.HAND:
            widget.set_cursor(Gdk.Cursor.new_from_name("grab", None))
        else:
            widget.set_cursor(Gdk.Cursor.new_from_name("text", None))

    def _on_continuous_selection_motion_leave(self, controller: Gtk.EventControllerMotion, page_idx: int) -> None:
        if not getattr(self, "_handle_drag_mode", None):
            widget = controller.get_widget()
            if self.tool_mode == ToolMode.HAND:
                widget.set_cursor(Gdk.Cursor.new_from_name("grab", None))
            else:
                widget.set_cursor(Gdk.Cursor.new_from_name("text", None))

    # ------------------------------------------------------------------
    # Mouse Scroll & Zoom Options
    # ------------------------------------------------------------------

    def _on_mouse_scroll(self, controller: Gtk.EventControllerScroll, dx: float, dy: float) -> bool:
        if not self.renderer.doc:
            return False

        # Ctrl + Scroll zoom logic
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            if dy > 0:
                self._adjust_zoom(-ZOOM_STEP)
            elif dy < 0:
                self._adjust_zoom(ZOOM_STEP)
            return True

        # Single page view layout scroll navigation fallback
        if self.view_mode == ViewMode.SINGLE:
            vadj = self.scroller.get_vadjustment()
            can_scroll = vadj.get_upper() > vadj.get_page_size()
            
            if dy > 0:  # Scroll down
                if not can_scroll or (vadj.get_value() + vadj.get_page_size() >= vadj.get_upper() - 1.0):
                    self._navigate_page(1)
                    GLib.idle_add(lambda: vadj.set_value(vadj.get_lower()))
                    return True
            elif dy < 0:  # Scroll up
                if not can_scroll or (vadj.get_value() <= vadj.get_lower() + 1.0):
                    self._navigate_page(-1)
                    GLib.idle_add(lambda: vadj.set_value(vadj.get_upper() - vadj.get_page_size()))
                    return True

        return False

    def _adjust_zoom(self, step: float) -> None:
        new_zoom = round(self.renderer.zoom + step, 2)
        self._set_zoom_val(new_zoom)

    def _set_zoom_val(self, zoom: float) -> None:
        val = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self.renderer.set_zoom(val)
        self._render_view()

    def _on_zoom_to_activated(self, action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        zoom = parameter.get_double()
        self._set_zoom_val(zoom)

    def _on_zoom_fit_width(self, action: Gio.SimpleAction, parameter: Any) -> None:
        if not self.renderer.doc:
            return
        width = self.scroller.get_width()
        if width <= 0:
            width = self.scroller.get_allocated_width()
        if width <= 0:
            width = 800
        
        first_page = self.renderer.doc.load_page(0)
        page_rect = first_page.rect
        page_w = page_rect.width
        
        target_w = max(200.0, float(width - 48))
        self._set_zoom_val(target_w / page_w)

    def _on_zoom_fit_page(self, action: Gio.SimpleAction, parameter: Any) -> None:
        if not self.renderer.doc:
            return
        width = self.scroller.get_width() or self.scroller.get_allocated_width() or 800
        height = self.scroller.get_height() or self.scroller.get_allocated_height() or 600
        
        first_page = self.renderer.doc.load_page(0)
        page_rect = first_page.rect
        
        target_w = max(200.0, float(width - 48))
        target_h = max(200.0, float(height - 48))
        
        zoom = min(target_w / page_rect.width, target_h / page_rect.height)
        self._set_zoom_val(zoom)

    def _on_toggle_view_mode(self, action: Gio.SimpleAction, parameter: Any) -> None:
        self._unparent_popover()
        self.view_mode = ViewMode.CONTINUOUS if self.view_mode == ViewMode.SINGLE else ViewMode.SINGLE
        self.selection.clear_selection()
        
        self.scroller.set_child(None)
        if self.view_mode == ViewMode.CONTINUOUS:
            self._setup_continuous_layout()
        else:
            self.scroller.set_child(self.overlay)

        self._render_view()
        self._update_cursor()
        self._update_controls_sensitivity()

    def _on_tool_mode_toggled(self, button: Gtk.ToggleButton, mode: ToolMode | None) -> None:
        if button.get_active():
            if mode is None:
                mode = self.last_annot_mode
            
            if mode == ToolMode.SELECTION:
                self.btn_tool_hand.set_active(False)
                self.btn_tool_annot.set_active(False)
            elif mode == ToolMode.HAND:
                self.btn_tool_select.set_active(False)
                self.btn_tool_annot.set_active(False)
            elif mode in (ToolMode.HIGHLIGHT, ToolMode.UNDERLINE, ToolMode.NOTE):
                self.btn_tool_select.set_active(False)
                self.btn_tool_hand.set_active(False)
                self.last_annot_mode = mode
                
            self.tool_mode = mode
            self._update_cursor()
        else:
            if (not self.btn_tool_select.get_active() and 
                not self.btn_tool_hand.get_active() and 
                not self.btn_tool_annot.get_active()):
                self.btn_tool_select.set_active(True)

    def _set_tool_mode(self, mode: ToolMode) -> None:
        self.last_annot_mode = mode
        self.btn_tool_annot.set_active(True)
        self.tool_mode = mode
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self.tool_mode == ToolMode.HAND:
            cursor_name = "grab"
        elif self.tool_mode in (ToolMode.HIGHLIGHT, ToolMode.UNDERLINE, ToolMode.NOTE):
            cursor_name = "text"
        else:
            cursor_name = "default"

        cursor = Gdk.Cursor.new_from_name(cursor_name, None)
        self.selection_layer.set_cursor(cursor)
        
        if self.view_mode == ViewMode.CONTINUOUS and self.renderer.page_widgets:
            for page_data in self.renderer.page_widgets:
                page_data["drawing_area"].set_cursor(cursor)

    def _scroll_to_tts_sentence(self, sentence: Any) -> None:
        """Ensure the active TTS sentence is scrolled into view smoothly."""
        if not sentence or not sentence.line_rects:
            return

        from ..constants import ViewMode, PAGE_SPACING

        if self.view_mode == ViewMode.CONTINUOUS:
            vadj = self.scroller.get_vadjustment()
            if not vadj:
                return

            # Compute page vertical position in continuous mode
            top_y_in_page = min(r.y0 for r in sentence.line_rects)
            h_with_spacing = self.renderer.page_h + PAGE_SPACING
            target_page_top = sentence.page_index * h_with_spacing
            sentence_global_y = target_page_top + (top_y_in_page * self.renderer.zoom)

            curr_scroll = vadj.get_value()
            page_size = vadj.get_page_size()
            viewport_bottom = curr_scroll + page_size

            # If the sentence is out of bounds or in the lower 20% of the screen, scroll to it
            if sentence_global_y < curr_scroll + 40 or sentence_global_y > (viewport_bottom - 100):
                target_scroll = max(0.0, min(
                    sentence_global_y - (page_size * 0.25),
                    vadj.get_upper() - page_size
                ))
                self._is_navigating = True
                vadj.set_value(target_scroll)
                self._is_navigating = False
        else:
            if self.current_page != sentence.page_index:
                self._navigate_to_page_index(sentence.page_index)

