"""Annotations management, selection drawing and popover placement for MainWindow."""

import logging
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from ..constants import AnnotationType, ToolMode, ViewMode
from ..annotations import AnnotationManager
from ..locale import _

log = logging.getLogger(__name__)


class WindowAnnotationsMixin:
    """Mixin implementing annotation drawing overlay, color management, and popover positioning."""

    def _unparent_popover(self) -> None:
        if hasattr(self, "popover") and self.popover:
            if self.popover.get_parent() is not None:
                self.popover.unparent()

    def _apply_annotation(self, annot_type: AnnotationType) -> None:
        if not self.renderer.doc:
            return

        line_rects = self.selection.get_selected_line_rects()
        if not line_rects:
            return

        page = self.renderer.doc.load_page(self.current_page)
        rgb = (self.current_color.red, self.current_color.green, self.current_color.blue)
        opacity = self.current_color.alpha

        try:
            label, xrefs = AnnotationManager.apply(page, annot_type, line_rects, rgb, opacity)
            self.annotation_history.append((self.current_page, xrefs))
            self.selection.clear_selection()
            self.has_unsaved_changes = True
            self._update_save_state()
            self._render_view()
            self.set_status(f"{_('annot_applied')} {label}")
        except Exception as exc:
            log.error("Failed to apply annotation: %s", exc)
            self.set_status(f"{_('err_apply_annot')}: {exc}")

    def _on_undo(self, action: Gio.SimpleAction = None, param: Any = None) -> None:
        if not self.renderer.doc:
            return
        if not self.annotation_history:
            self.set_status("Nada para desfazer.")
            return

        page_num, xrefs = self.annotation_history.pop()
        page = self.renderer.doc.load_page(page_num)

        deleted_any = False
        for xref in xrefs:
            annot = page.first_annot
            while annot:
                if annot.xref == xref:
                    page.delete_annot(annot)
                    deleted_any = True
                    break
                annot = annot.next

        if deleted_any:
            self.has_unsaved_changes = len(self.annotation_history) > 0
            self._update_save_state()
            self._render_view()
            self.set_status("Anotação desfeita.")

    def _get_closest_opacity_index(self, alpha: float) -> int:
        OPACITY_VALUES = [0.10, 0.25, 0.50, 0.75, 0.80, 0.90, 1.00]
        closest_idx = 6
        min_diff = 1.0
        for idx, val in enumerate(OPACITY_VALUES):
            diff = abs(val - alpha)
            if diff < min_diff:
                min_diff = diff
                closest_idx = idx
        return closest_idx

    def _on_color_changed(self, button: Gtk.ColorButton) -> None:
        self.current_color = button.get_rgba()
        if getattr(self, "_updating_opacity", False):
            return
        self._updating_opacity = True
        try:
            closest_idx = self._get_closest_opacity_index(self.current_color.alpha)
            self.opacity_dropdown.set_selected(closest_idx)
            self.pop_opacity_dropdown.set_selected(closest_idx)

            OPACITY_VALUES = [0.10, 0.25, 0.50, 0.75, 0.80, 0.90, 1.00]
            val = OPACITY_VALUES[closest_idx]
            new_color = Gdk.RGBA()
            new_color.red = self.current_color.red
            new_color.green = self.current_color.green
            new_color.blue = self.current_color.blue
            new_color.alpha = val
            self.current_color = new_color

            if button == self.btn_color:
                self.pop_color_btn.set_rgba(self.current_color)
            else:
                self.btn_color.set_rgba(self.current_color)
        finally:
            self._updating_opacity = False

    def _on_opacity_dropdown_changed(self, dropdown: Gtk.DropDown, pspec: Any) -> None:
        if getattr(self, "_updating_opacity", False):
            return
        self._updating_opacity = True
        try:
            idx = dropdown.get_selected()
            if idx == Gtk.INVALID_LIST_POSITION:
                idx = 6
            OPACITY_VALUES = [0.10, 0.25, 0.50, 0.75, 0.80, 0.90, 1.00]
            val = OPACITY_VALUES[idx]

            new_color = Gdk.RGBA()
            new_color.red = self.current_color.red
            new_color.green = self.current_color.green
            new_color.blue = self.current_color.blue
            new_color.alpha = val
            self.current_color = new_color

            if dropdown == self.opacity_dropdown:
                self.pop_opacity_dropdown.set_selected(idx)
            else:
                self.opacity_dropdown.set_selected(idx)

            self.btn_color.set_rgba(self.current_color)
            self.pop_color_btn.set_rgba(self.current_color)
        finally:
            self._updating_opacity = False

    def _update_save_state(self) -> None:
        if self.has_unsaved_changes:
            self.btn_save.add_css_class("suggested-action")
            self.btn_save.set_tooltip_text(f"{_('save_pdf')} ({_('unsaved_tooltip')})")
        else:
            self.btn_save.remove_css_class("suggested-action")
            self.btn_save.set_tooltip_text(_("save_pdf"))

    def check_unsaved_changes_before_exit(self, callback_if_can_close) -> None:
        """Prompt user about unsaved changes."""
        if not self.has_unsaved_changes:
            callback_if_can_close()
            return

        dialog = Adw.Dialog(title=_("unsaved_changes_title"))
        dialog.set_content_width(360)
        dialog.set_content_height(160)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        label = Gtk.Label(label=_("unsaved_changes_prompt"))
        label.set_wrap(True)
        content.append(label)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_halign(Gtk.Align.END)

        btn_cancel = Gtk.Button(label=_("cancel"))
        btn_cancel.connect("clicked", lambda _: dialog.close())
        actions.append(btn_cancel)

        btn_discard = Gtk.Button(label=_("discard"), css_classes=["destructive-action"])
        def on_discard(_btn):
            dialog.close()
            self.has_unsaved_changes = False
            callback_if_can_close()
        btn_discard.connect("clicked", on_discard)
        actions.append(btn_discard)

        btn_save = Gtk.Button(label=_("save_pdf"), css_classes=["suggested-action"])
        def on_save(_btn):
            dialog.close()
            self._on_save_file_clicked(None, None)
            if not self.has_unsaved_changes:
                callback_if_can_close()
        btn_save.connect("clicked", on_save)
        actions.append(btn_save)

        content.append(actions)
        dialog.set_child(content)
        dialog.present(self)

    # ------------------------------------------------------------------
    # Drawing Selection Overlays
    # ------------------------------------------------------------------

    def _draw_selection_overlay(self, area: Gtk.DrawingArea, cr: Any, w: int, h: int) -> None:
        self._render_highlights_on_cr(cr)
        self._render_search_highlights_on_cr(cr, self.current_page)

    def _draw_page_selection_overlay(self, area: Gtk.DrawingArea, cr: Any, w: int, h: int, page_idx: int) -> None:
        if self.current_page == page_idx:
            self._render_highlights_on_cr(cr)
        self._render_search_highlights_on_cr(cr, page_idx)

    def _render_highlights_on_cr(self, cr: Any) -> None:
        selected = self.selection.get_selected_words()
        if not selected:
            return

        # Use standard blue selection color (e.g. #3584e4 with 0.3 alpha for fill)
        cr.set_source_rgba(0.208, 0.518, 0.894, 0.3)
        for item in selected:
            rect = item["rect"]
            x = rect.x0 * self.renderer.zoom
            y = rect.y0 * self.renderer.zoom
            w = (rect.x1 - rect.x0) * self.renderer.zoom
            h = (rect.y1 - rect.y0) * self.renderer.zoom
            cr.rectangle(x, y, w, h)
            cr.fill()

        # Outline with 0.8 alpha
        cr.set_source_rgba(0.208, 0.518, 0.894, 0.8)
        cr.set_line_width(1.0)
        for item in selected:
            rect = item["rect"]
            x = rect.x0 * self.renderer.zoom
            y = rect.y0 * self.renderer.zoom
            w = (rect.x1 - rect.x0) * self.renderer.zoom
            h = (rect.y1 - rect.y0) * self.renderer.zoom
            cr.rectangle(x, y, w, h)
            cr.stroke()

    # ------------------------------------------------------------------
    # Selection Popover positioning
    # ------------------------------------------------------------------

    def _show_selection_popover(self, parent_widget: Gtk.Widget) -> None:
        selected = self.selection.get_selected_words()
        if not selected:
            return

        last_word = selected[-1]
        rect = last_word["rect"]

        rect_gdk = Gdk.Rectangle()
        rect_gdk.x = int(rect.x1 * self.renderer.zoom)
        rect_gdk.y = int(rect.y0 * self.renderer.zoom)
        rect_gdk.width = 1
        rect_gdk.height = int((rect.y1 - rect.y0) * self.renderer.zoom)

        popover_parent = self.popover.get_parent()
        if popover_parent != parent_widget:
            if popover_parent:
                self.popover.unparent()
            self.popover.set_parent(parent_widget)

        self.popover.set_pointing_to(rect_gdk)
        self.popover.popup()
