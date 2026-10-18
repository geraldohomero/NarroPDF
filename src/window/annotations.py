"""Annotations management, selection drawing and popover placement for MainWindow."""

import logging
import math
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from ..constants import AnnotationType, ToolMode, ViewMode
from ..annotations import AnnotationManager, AnnotationSnapshot, AnnotationCommand
from ..locale import _

log = logging.getLogger(__name__)


class WindowAnnotationsMixin:
    """Mixin implementing annotation drawing overlay, color management, and popover positioning."""

    def _unparent_popover(self) -> None:
        if hasattr(self, "popover") and self.popover:
            if self.popover.get_parent() is not None:
                self.popover.unparent()

    def _record_annotation_command(self, cmd: AnnotationCommand) -> None:
        """Push an annotation command onto the undo stack and clear redo stack."""
        if not hasattr(self, "undo_stack"):
            self.undo_stack = []
        if not hasattr(self, "redo_stack"):
            self.redo_stack = []
        self.undo_stack.append(cmd)
        self.redo_stack.clear()
        self.has_unsaved_changes = True
        self._update_save_state()

    def _apply_annotation(self, annot_type: AnnotationType, content: str = "") -> None:
        if not self.renderer.doc:
            return

        line_rects = self.selection.get_selected_line_rects()
        if not line_rects:
            return

        if annot_type == AnnotationType.NOTE and not content:
            self._prompt_note_dialog(annot_type)
            return

        page = self.renderer.doc.load_page(self.current_page)
        rgb = (self.current_color.red, self.current_color.green, self.current_color.blue)
        opacity = self.current_color.alpha

        try:
            label, xrefs = AnnotationManager.apply(page, annot_type, line_rects, rgb, opacity, content=content)
            after_snap = AnnotationManager.snapshot_from_annot(page, self.current_page, xrefs[0])
            self._record_annotation_command(
                AnnotationCommand(
                    action="create",
                    page_idx=self.current_page,
                    before=None,
                    after=after_snap,
                    current_xref=xrefs[0],
                )
            )
            self.selected_annotation = None
            self.selection.clear_selection()
            self._render_view()
            if hasattr(self, "_reload_annotations_tab"):
                self._reload_annotations_tab()
            self.set_status(f"{_('annot_applied')} {label}")
        except Exception as exc:
            log.error("Failed to apply annotation: %s", exc)
            self.set_status(f"{_('err_apply_annot')}: {exc}")

    def _prompt_note_dialog(self, annot_type: AnnotationType) -> None:
        """Prompt user for note text before creating a NOTE annotation."""
        dialog = Adw.Dialog(title=_("add_note"))
        dialog.set_content_width(360)
        dialog.set_content_height(200)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        label = Gtk.Label(label=_("note_content"))
        label.set_xalign(0.0)
        box.append(label)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_min_content_height(100)
        scroller.add_css_class("card")
        text_view = Gtk.TextView()
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroller.set_child(text_view)
        box.append(scroller)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_halign(Gtk.Align.END)

        btn_cancel = Gtk.Button(label=_("cancel"))
        btn_cancel.connect("clicked", lambda _: dialog.close())
        actions.append(btn_cancel)

        btn_confirm = Gtk.Button(label=_("confirm"), css_classes=["suggested-action"])

        def on_confirm(_btn: Gtk.Button) -> None:
            buf = text_view.get_buffer()
            start, end = buf.get_bounds()
            note_text = buf.get_text(start, end, True).strip()
            dialog.close()
            self._apply_annotation(annot_type, content=note_text or "Nota")

        btn_confirm.connect("clicked", on_confirm)
        actions.append(btn_confirm)

        box.append(actions)
        dialog.set_child(box)
        dialog.present(self)

    def _on_undo(self, action: Gio.SimpleAction = None, param: Any = None) -> None:
        if not self.renderer.doc:
            return
        if not getattr(self, "undo_stack", None):
            self.set_status("Nada para desfazer.")
            return

        cmd = self.undo_stack.pop()
        page = self.renderer.doc.load_page(cmd.page_idx)

        if cmd.action == "create":
            if cmd.current_xref is not None:
                AnnotationManager.delete_annot(page, cmd.current_xref)
                cmd.current_xref = None
            if getattr(self, "selected_annotation", None) and self.selected_annotation.get("xref") == cmd.current_xref:
                self.selected_annotation = None
                self.selection.clear_selection()
        elif cmd.action == "delete":
            if cmd.before:
                new_xref = AnnotationManager.restore_snapshot(page, cmd.before)
                cmd.current_xref = new_xref
        elif cmd.action == "modify":
            if cmd.current_xref is not None:
                AnnotationManager.delete_annot(page, cmd.current_xref)
            if cmd.before:
                new_xref = AnnotationManager.restore_snapshot(page, cmd.before)
                cmd.current_xref = new_xref
                if getattr(self, "selected_annotation", None):
                    self.selected_annotation = None
                    self.selection.clear_selection()

        if not hasattr(self, "redo_stack"):
            self.redo_stack = []
        self.redo_stack.append(cmd)

        self.has_unsaved_changes = True
        self._update_save_state()
        self._render_view()
        if hasattr(self, "_reload_annotations_tab"):
            self._reload_annotations_tab()
        self.set_status("Ação desfeita.")

    def _on_redo(self, action: Gio.SimpleAction = None, param: Any = None) -> None:
        if not self.renderer.doc:
            return
        if not getattr(self, "redo_stack", None):
            self.set_status("Nada para refazer.")
            return

        cmd = self.redo_stack.pop()
        page = self.renderer.doc.load_page(cmd.page_idx)

        if cmd.action == "create":
            if cmd.after:
                new_xref = AnnotationManager.restore_snapshot(page, cmd.after)
                cmd.current_xref = new_xref
        elif cmd.action == "delete":
            if cmd.current_xref is not None:
                AnnotationManager.delete_annot(page, cmd.current_xref)
                cmd.current_xref = None
            if getattr(self, "selected_annotation", None):
                self.selected_annotation = None
                self.selection.clear_selection()
        elif cmd.action == "modify":
            if cmd.current_xref is not None:
                AnnotationManager.delete_annot(page, cmd.current_xref)
            if cmd.after:
                new_xref = AnnotationManager.restore_snapshot(page, cmd.after)
                cmd.current_xref = new_xref
                if getattr(self, "selected_annotation", None):
                    self.selected_annotation = None
                    self.selection.clear_selection()

        if not hasattr(self, "undo_stack"):
            self.undo_stack = []
        self.undo_stack.append(cmd)

        self.has_unsaved_changes = True
        self._update_save_state()
        self._render_view()
        if hasattr(self, "_reload_annotations_tab"):
            self._reload_annotations_tab()
        self.set_status("Ação refeita.")

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
            self._update_selected_annotation_appearance()
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
            self._update_selected_annotation_appearance()
        finally:
            self._updating_opacity = False

    def _update_selected_annotation_appearance(self) -> None:
        sel_annot = getattr(self, "selected_annotation", None)
        if sel_annot and self.renderer.doc:
            try:
                page = self.renderer.doc.load_page(sel_annot["page_idx"])
                before_snap = AnnotationManager.snapshot_from_annot(page, sel_annot["page_idx"], sel_annot["xref"])
                annot = AnnotationManager._resolve_annot(page, sel_annot["xref"])
                if annot:
                    rgb = (self.current_color.red, self.current_color.green, self.current_color.blue)
                    annot.set_colors(stroke=rgb)
                    annot.set_opacity(self.current_color.alpha)
                    annot.update()
                    after_snap = AnnotationManager.snapshot_from_annot(page, sel_annot["page_idx"], annot.xref)
                    if before_snap and after_snap:
                        self._record_annotation_command(
                            AnnotationCommand(
                                action="modify",
                                page_idx=sel_annot["page_idx"],
                                before=before_snap,
                                after=after_snap,
                                current_xref=annot.xref,
                            )
                        )
                    bounds = sel_annot.get("bounds")
                    self._render_view()
                    if hasattr(self, "_reload_annotations_tab"):
                        self._reload_annotations_tab()
                    if bounds:
                        self.selection.set_selection_bounds(bounds[0], bounds[1])
                    if hasattr(self, "selection_layer"):
                        self.selection_layer.queue_draw()
                    if hasattr(self, "renderer") and self.renderer.page_widgets:
                        for page_data in self.renderer.page_widgets:
                            page_data["drawing_area"].queue_draw()
            except Exception as exc:
                log.error("Failed to update annotation appearance: %s", exc)

    def _on_delete_selected_annotation(self) -> None:
        sel_annot = getattr(self, "selected_annotation", None)
        if not sel_annot or not self.renderer.doc:
            return

        try:
            page = self.renderer.doc.load_page(sel_annot["page_idx"])
            before_snap = AnnotationManager.snapshot_from_annot(page, sel_annot["page_idx"], sel_annot["xref"])
            AnnotationManager.delete_annot(page, sel_annot["xref"])
            if before_snap:
                self._record_annotation_command(
                    AnnotationCommand(
                        action="delete",
                        page_idx=sel_annot["page_idx"],
                        before=before_snap,
                        after=None,
                        current_xref=None,
                    )
                )
            self.selected_annotation = None
            self.selection.clear_selection()
            self.popover.popdown()
            self._render_view()
            if hasattr(self, "_reload_annotations_tab"):
                self._reload_annotations_tab()
            self.set_status(_("delete_annotation") + " realizada.")
        except Exception as exc:
            log.error("Failed to delete selected annotation: %s", exc)

    def _on_copy_selected_text(self, action: Gio.SimpleAction = None, param: Any = None) -> None:
        """Copies currently selected text to the system clipboard."""
        text = self.selection.get_selected_text()
        if not text:
            return
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        if hasattr(self, "popover"):
            self.popover.popdown()
        self.set_status(_("copied_to_clipboard"))

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
        self._render_annotation_handles_on_cr(cr, self.current_page)
        self._render_tts_highlights_on_cr(cr, self.current_page)
        self._render_search_highlights_on_cr(cr, self.current_page)

    def _draw_page_selection_overlay(self, area: Gtk.DrawingArea, cr: Any, w: int, h: int, page_idx: int) -> None:
        if self.current_page == page_idx:
            self._render_highlights_on_cr(cr)
            self._render_annotation_handles_on_cr(cr, page_idx)
        self._render_tts_highlights_on_cr(cr, page_idx)
        self._render_search_highlights_on_cr(cr, page_idx)

    def _hit_test_handle(self, screen_x: float, screen_y: float) -> str | None:
        """Check if screen coordinate hits start or end handle."""
        handles = self.selection.get_handle_positions(self.renderer.zoom)
        if not handles:
            return None
        start_pt, end_pt = handles
        threshold_sq = 14.0 * 14.0  # 196 px^2

        dx_start = screen_x - start_pt[0]
        dy_start = screen_y - start_pt[1]
        if (dx_start * dx_start + dy_start * dy_start) <= threshold_sq:
            return "start"

        dx_end = screen_x - end_pt[0]
        dy_end = screen_y - end_pt[1]
        if (dx_end * dx_end + dy_end * dy_end) <= threshold_sq:
            return "end"

        return None

    def _render_annotation_handles_on_cr(self, cr: Any, page_idx: int) -> None:
        """Render circular drag handles at start and end of selection."""
        sel_annot = getattr(self, "selected_annotation", None)
        if not sel_annot or sel_annot.get("page_idx") != page_idx:
            return

        handles = self.selection.get_handle_positions(self.renderer.zoom)
        if not handles:
            return
        start_pt, end_pt = handles

        for pt in (start_pt, end_pt):
            # Outer white border ring for high contrast
            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.set_line_width(2.0)
            cr.arc(pt[0], pt[1], 7.0, 0.0, 2.0 * math.pi)
            cr.stroke()

            # Inner accent blue circle
            cr.set_source_rgba(0.208, 0.518, 0.894, 1.0)
            cr.arc(pt[0], pt[1], 6.0, 0.0, 2.0 * math.pi)
            cr.fill()

    def _render_tts_highlights_on_cr(self, cr: Any, page_idx: int) -> None:
        sentence = getattr(self, "active_tts_sentence", None)
        if not sentence or sentence.page_index != page_idx:
            return

        zoom = self.renderer.zoom

        # 1. Destaque suave da Frase Inteira (Cinza claro)
        cr.set_source_rgba(0.82, 0.82, 0.85, 0.45)
        for r in sentence.line_rects:
            x = r.x0 * zoom
            y = r.y0 * zoom
            w = (r.x1 - r.x0) * zoom
            h = (r.y1 - r.y0) * zoom
            cr.rectangle(x, y, w, h)
            cr.fill()

        # 2. Destaque da Palavra Ativa (Cinza levemente mais escuro)
        word_idx = getattr(self, "active_tts_word_index", -1)
        if 0 <= word_idx < len(sentence.words):
            word = sentence.words[word_idx]
            wr = word.rect
            wx = wr.x0 * zoom
            wy = wr.y0 * zoom
            ww = (wr.x1 - wr.x0) * zoom
            wh = (wr.y1 - wr.y0) * zoom

            # Fundo cinza mais escuro
            cr.set_source_rgba(0.55, 0.55, 0.58, 0.65)
            cr.rectangle(wx, wy, ww, wh)
            cr.fill()

            # Borda sutil de definição
            cr.set_source_rgba(0.38, 0.38, 0.40, 0.85)
            cr.set_line_width(1.0)
            cr.rectangle(wx, wy, ww, wh)
            cr.stroke()

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

        is_annot = getattr(self, "selected_annotation", None) is not None
        if hasattr(self, "btn_delete_annot"):
            self.btn_delete_annot.set_visible(is_annot)

        if is_annot:
            xref = self.selected_annotation.get("xref")
            if xref and self.renderer.doc:
                try:
                    page = self.renderer.doc.load_page(self.selected_annotation["page_idx"])
                    annot = AnnotationManager._resolve_annot(page, xref)
                    if annot:
                        colors = annot.colors or {}
                        stroke = colors.get("stroke")
                        if stroke and len(stroke) >= 3:
                            c = Gdk.RGBA()
                            c.red = stroke[0]
                            c.green = stroke[1]
                            c.blue = stroke[2]
                            c.alpha = annot.opacity if annot.opacity >= 0 else 1.0
                            self.current_color = c
                            if hasattr(self, "btn_color"):
                                self.btn_color.set_rgba(c)
                            if hasattr(self, "pop_color_btn"):
                                self.pop_color_btn.set_rgba(c)
                except Exception as exc:
                    log.error("Failed to sync annotation color: %s", exc)

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
