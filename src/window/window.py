"""Main window class coordinating modular mixins for NarroPDF."""

import logging
import os
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gio, Gtk

try:
    import fitz
except ImportError:
    fitz = None

from ..constants import ViewMode, ToolMode, AnnotationType
from ..utils import detect_language_from_text
from ..tts_engine import TtsEngine
from ..pdf_renderer import PdfRenderer
from ..text_selection import TextSelectionHandler
from ..locale import _

# Import mixins
from .ui import WindowUiMixin
from .actions import WindowActionsMixin
from .navigation import WindowNavigationMixin
from .annotations import WindowAnnotationsMixin
from .tts import WindowTtsMixin
from .search import WindowSearchMixin

log = logging.getLogger(__name__)


class MainWindow(
    Adw.ApplicationWindow,
    WindowUiMixin,
    WindowActionsMixin,
    WindowNavigationMixin,
    WindowAnnotationsMixin,
    WindowTtsMixin,
    WindowSearchMixin,
):
    """The modular MainWindow class for NarroPDF."""

    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)
        self.set_title(_("app_name"))
        self.set_default_size(1150, 750)

        # Core logic helper instances
        self.tts = TtsEngine()
        self.renderer = PdfRenderer()
        self.selection = TextSelectionHandler()

        # State tracking
        self.current_page: int = 0
        self.pdf_path: str | None = None
        self.current_language: str = "pt-BR"
        self.view_mode: ViewMode = ViewMode.CONTINUOUS
        self.tool_mode: ToolMode = ToolMode.SELECTION
        self.last_annot_mode: ToolMode = ToolMode.HIGHLIGHT
        self.current_color: Gdk.RGBA = Gdk.RGBA()
        self.current_color.parse("yellow")
        self.has_unsaved_changes: bool = False
        self.annotation_history: list[tuple[int, list[int]]] = []
        self.btn_sidebar_pause: Gtk.Button | None = None
        self._is_navigating: bool = False

        # Drag scroll state
        self._initial_scroll_x: float = 0.0
        self._initial_scroll_y: float = 0.0

        # Piper Engine state
        self.current_engine: str = "edge"

        # Search state
        self.search_query: str = ""
        self.search_results: dict[int, list] = {}
        self.search_matches_flat: list[tuple[int, int]] = []
        self.current_search_match_index: int = -1

        # Set up callbacks
        self.tts.set_status_callback(self.set_status)
        self.tts.set_state_changed_callback(self.update_playback_bar_state)

        # Connect destroy signal for safety cleanup
        self.connect("destroy", self._on_destroy)

        # Build UI layout & Actions
        self._build_ui()
        self._setup_actions()
        self._update_controls_sensitivity()
        self._update_save_state()

    def _on_destroy(self, *args) -> None:
        self.tts.cleanup()
        self._unparent_popover()

    def close_document(self) -> None:
        self.tts.cleanup()
        self._unparent_popover()
        if self.renderer.doc:
            self.renderer.doc.close()
            self.renderer.doc = None

    def set_status(self, text: str) -> None:
        self.status_label.set_text(text)

    def _update_controls_sensitivity(self) -> None:
        has_doc = self.renderer.doc is not None
        self.btn_save.set_sensitive(has_doc)
        self.btn_prev.set_sensitive(has_doc and self.current_page > 0)
        self.btn_next.set_sensitive(has_doc and (self.current_page < len(self.renderer.doc) - 1))
        self.btn_zoom_in.set_sensitive(has_doc)
        self.btn_zoom_out.set_sensitive(has_doc)
        self.page_entry.set_sensitive(has_doc)

    def _on_page_entry_activated(self, entry: Gtk.Entry) -> None:
        if not self.renderer.doc:
            return
        try:
            val = int(entry.get_text()) - 1
            if 0 <= val < len(self.renderer.doc):
                self._navigate_to_page_index(val)
            else:
                entry.set_text(str(self.current_page + 1))
        except ValueError:
            entry.set_text(str(self.current_page + 1))

    # ------------------------------------------------------------------
    # Left Sidebar Loading & Syncing
    # ------------------------------------------------------------------

    def _reload_left_sidebar(self) -> None:
        if not self.renderer.doc:
            return

        # 1. Pages Tab
        self.left_pages_list.remove_all()
        for i in range(len(self.renderer.doc)):
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=f"{_('tab_pages')} {i + 1}")
            label.set_xalign(0.0)
            label.set_margin_start(12)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            row.set_child(label)
            self.left_pages_list.append(row)

        # 2. Chapters Tab
        self.left_chapters_list.remove_all()
        toc = self.renderer.doc.get_toc()
        if toc:
            for item in toc:
                lvl, title, page = item
                row = Gtk.ListBoxRow()
                
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                box.set_margin_start(12 * lvl)
                box.set_margin_top(6)
                box.set_margin_bottom(6)
                
                label = Gtk.Label(label=title)
                label.set_xalign(0.0)
                box.append(label)
                
                row._target_page = page - 1
                row.set_child(box)
                self.left_chapters_list.append(row)
        else:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=_("no_chapters"))
            label.set_sensitive(False)
            row.set_child(label)
            self.left_chapters_list.append(row)

    def _on_left_page_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        self._navigate_to_page_index(idx)

    def _on_left_chapter_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if hasattr(row, "_target_page"):
            self._navigate_to_page_index(row._target_page)

    def _navigate_to_page_index(self, idx: int) -> None:
        if not self.renderer.doc or not (0 <= idx < len(self.renderer.doc)):
            return
        
        self.current_page = idx
        self._update_controls_sensitivity()
        self.page_entry.set_text(str(self.current_page + 1))

        if self.view_mode == ViewMode.CONTINUOUS:
            from ..constants import PAGE_SPACING
            h_with_spacing = self.renderer.page_h + PAGE_SPACING
            target_y = idx * h_with_spacing
            vadj = self.scroller.get_vadjustment()
            self._is_navigating = True
            vadj.set_value(min(target_y, vadj.get_upper() - vadj.get_page_size()))
            self._is_navigating = False

            if self.renderer.page_widgets and idx < len(self.renderer.page_widgets):
                self.selection.set_words(self.renderer.page_widgets[idx]["words"])
        else:
            self.selection.clear_selection()
            self._render_view()

    # ------------------------------------------------------------------
    # Open / Save pdf callbacks
    # ------------------------------------------------------------------

    def _on_open_file_clicked(self, action: Gio.SimpleAction, param: Any) -> None:
        dialog = Gtk.FileDialog(title=_("select_pdf_title"))
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        pdf_filter = Gtk.FileFilter()
        pdf_filter.set_name(_("pdf_files_filter"))
        pdf_filter.add_mime_type("application/pdf")
        filters.append(pdf_filter)
        dialog.set_filters(filters)

        def on_open_finished(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                gfile = source.open_finish(result)
                if gfile:
                    self.open_pdf(gfile.get_path())
            except GLib.Error as err:
                log.info("Dialog cancelled or failed: %s", err)

        dialog.open(self, None, on_open_finished)

    def _on_save_file_clicked(self, action: Gio.SimpleAction, param: Any) -> None:
        if not self.renderer.doc or not self.pdf_path:
            return
        try:
            self.renderer.doc.save(
                self.pdf_path,
                incremental=True,
                encryption=fitz.PDF_ENCRYPT_KEEP,
            )
            self.has_unsaved_changes = False
            self._update_save_state()
            self.set_status(_("saved_incremental"))
        except Exception:
            fallback = self.pdf_path.replace(".pdf", "_edited.pdf")
            self.renderer.doc.save(fallback)
            self.has_unsaved_changes = False
            self._update_save_state()
            self.set_status(f"{_('saved_copy')} {fallback}")
