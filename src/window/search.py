"""Search functionality (Ctrl+F) for text matches and highlighting in MainWindow."""

import logging
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gio, Gtk

from ..locale import _
from ..constants import ViewMode

log = logging.getLogger(__name__)


class WindowSearchMixin:
    """Mixin implementing Ctrl+F search bar, matching logic, highlighting, and search scrolling."""

    def _on_toggle_search(self, action: Gio.SimpleAction = None, parameter: Any = None) -> None:
        if self.search_revealer.get_reveal_child():
            self.search_revealer.set_reveal_child(False)
            self._clear_search()
            self.scroller.grab_focus()
        else:
            self.search_revealer.set_reveal_child(True)
            self.search_entry.grab_focus()

    def _on_close_search(self) -> None:
        self.search_revealer.set_reveal_child(False)
        self._clear_search()
        self.scroller.grab_focus()

    def _clear_search(self) -> None:
        self.search_query = ""
        self.search_entry.set_text("")
        self.search_results.clear()
        self.search_matches_flat.clear()
        self.current_search_match_index = -1
        self._update_search_label()
        self._queue_redraw_all_pages()

    def _on_search_text_changed(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().strip()
        self.search_query = query
        self.search_results.clear()
        self.search_matches_flat.clear()
        self.current_search_match_index = -1

        if query and self.renderer.doc:
            # Search all pages
            for i in range(len(self.renderer.doc)):
                page = self.renderer.doc.load_page(i)
                matches = page.search_for(query)
                if matches:
                    self.search_results[i] = matches
                    for m_idx in range(len(matches)):
                        self.search_matches_flat.append((i, m_idx))
            
            if self.search_matches_flat:
                self.current_search_match_index = 0
                page_idx, m_idx = self.search_matches_flat[0]
                rect = self.search_results[page_idx][m_idx]
                self._scroll_to_match(page_idx, rect)
        
        self._update_search_label()
        self._queue_redraw_all_pages()

    def _on_search_next(self, *args) -> None:
        if not self.search_matches_flat:
            return
        self.current_search_match_index = (self.current_search_match_index + 1) % len(self.search_matches_flat)
        page_idx, m_idx = self.search_matches_flat[self.current_search_match_index]
        rect = self.search_results[page_idx][m_idx]
        self._scroll_to_match(page_idx, rect)
        self._update_search_label()
        self._queue_redraw_all_pages()

    def _on_search_prev(self, *args) -> None:
        if not self.search_matches_flat:
            return
        self.current_search_match_index = (self.current_search_match_index - 1) % len(self.search_matches_flat)
        page_idx, m_idx = self.search_matches_flat[self.current_search_match_index]
        rect = self.search_results[page_idx][m_idx]
        self._scroll_to_match(page_idx, rect)
        self._update_search_label()
        self._queue_redraw_all_pages()

    def _on_search_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._on_close_search()
            return True
        return False

    def _scroll_to_match(self, page_idx: int, rect) -> None:
        if self.view_mode == ViewMode.CONTINUOUS:
            from ..constants import PAGE_SPACING
            h_with_spacing = self.renderer.page_h + PAGE_SPACING
            match_y0 = page_idx * h_with_spacing + PAGE_SPACING + rect.y0 * self.renderer.zoom
            match_h = (rect.y1 - rect.y0) * self.renderer.zoom
            
            vadj = self.scroller.get_vadjustment()
            vp_h = vadj.get_page_size()
            
            # Center the match in the viewport
            target_scroll = match_y0 - (vp_h - match_h) / 2
            target_scroll = max(vadj.get_lower(), min(target_scroll, vadj.get_upper() - vp_h))
            
            self._is_navigating = True
            vadj.set_value(target_scroll)
            self._is_navigating = False
        else:
            if self.current_page != page_idx:
                self._navigate_to_page_index(page_idx)
            else:
                self.selection_layer.queue_draw()

    def _update_search_label(self) -> None:
        total = len(self.search_matches_flat)
        if total == 0:
            if self.search_query:
                self.search_results_label.set_label(_("no_results"))
            else:
                self.search_results_label.set_label("")
        else:
            curr = self.current_search_match_index + 1
            self.search_results_label.set_label(f"{curr} {_('page_of')} {total}")

    def _queue_redraw_all_pages(self) -> None:
        if self.view_mode == ViewMode.SINGLE:
            self.selection_layer.queue_draw()
        else:
            if self.renderer.page_widgets:
                for page_data in self.renderer.page_widgets:
                    page_data["drawing_area"].queue_draw()

    def _render_search_highlights_on_cr(self, cr: Any, page_idx: int) -> None:
        if not self.search_query or page_idx not in self.search_results:
            return

        matches = self.search_results[page_idx]
        zoom = self.renderer.zoom

        # First, draw all secondary matches
        for m_idx, rect in enumerate(matches):
            is_active = False
            if self.current_search_match_index >= 0:
                flat_page, flat_rect_idx = self.search_matches_flat[self.current_search_match_index]
                if flat_page == page_idx and flat_rect_idx == m_idx:
                    is_active = True
            
            x = rect.x0 * zoom
            y = rect.y0 * zoom
            w = (rect.x1 - rect.x0) * zoom
            h = (rect.y1 - rect.y0) * zoom

            if is_active:
                # Active match: semi-transparent orange with solid orange outline
                cr.set_source_rgba(1.0, 0.55, 0.0, 0.5)
                cr.rectangle(x, y, w, h)
                cr.fill()
                
                cr.set_source_rgba(1.0, 0.4, 0.0, 0.9)
                cr.set_line_width(1.5)
                cr.rectangle(x, y, w, h)
                cr.stroke()
            else:
                # Secondary matches: semi-transparent yellow
                cr.set_source_rgba(1.0, 0.92, 0.23, 0.4)
                cr.rectangle(x, y, w, h)
                cr.fill()
