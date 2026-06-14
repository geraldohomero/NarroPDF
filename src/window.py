"""Main application window implementation using modern Libadwaita."""

from __future__ import annotations

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

from .constants import (
    APP_ID,
    APP_VERSION,
    APP_WEBSITE,
    DEFAULT_ZOOM,
    MIN_ZOOM,
    MAX_ZOOM,
    ZOOM_STEP,
    ZOOM_PRESETS,
    LANGUAGE_OPTIONS,
    LANGUAGE_TO_VOICES,
    ViewMode,
    ToolMode,
    AnnotationType,
)
from .utils import normalize_text_for_tts, detect_language_from_text
from .tts_engine import TtsEngine
from .pdf_renderer import PdfRenderer
from .text_selection import TextSelectionHandler
from .annotations import AnnotationManager
from .locale import _

log = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    """The primary GTK4/Libadwaita window for NarroPDF."""

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
        self.view_mode: ViewMode = ViewMode.CONTINUOUS  # Continuous view by default
        self.tool_mode: ToolMode = ToolMode.SELECTION
        self.last_annot_mode: ToolMode = ToolMode.HIGHLIGHT
        self.current_color: Gdk.RGBA = Gdk.RGBA()
        self.current_color.parse("yellow")
        self.has_unsaved_changes: bool = False
        self.annotation_history: list[tuple[int, list[int]]] = []
        self.btn_sidebar_pause: Gtk.Button | None = None
        # Guard flag for scroll navigation loop prevention
        self._is_navigating: bool = False

        # Drag scroll state
        self._initial_scroll_x: float = 0.0
        self._initial_scroll_y: float = 0.0

        # Set up callbacks
        self.tts.set_status_callback(self.set_status)
        self.tts.set_state_changed_callback(self.update_playback_bar_state)

        # Build UI layout
        self._build_ui()
        self._setup_actions()
        self._update_controls_sensitivity()
        self._update_save_state()



    # ------------------------------------------------------------------
    # UI Building
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Load external CSS
        css_provider = Gtk.CssProvider()
        css_path = os.path.join(os.path.dirname(__file__), "style.css")
        if os.path.exists(css_path):
            css_provider.load_from_path(css_path)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        # Main layout container
        self.toolbar_view = Adw.ToolbarView()
        self.set_content(self.toolbar_view)

        # 1. HeaderBar Setup
        self.header_bar = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(self.header_bar)

        # Start section
        self.btn_sidebar_left = Gtk.ToggleButton(tooltip_text=_("sidebar"))
        self.btn_sidebar_left.set_icon_name("sidebar-show-symbolic")
        self.btn_sidebar_left.set_active(True)
        self.header_bar.pack_start(self.btn_sidebar_left)

        self.btn_open = Gtk.Button(tooltip_text=_("open_pdf"))
        self.btn_open.set_icon_name("document-open-symbolic")
        self.btn_open.set_action_name("win.open-file")
        self.header_bar.pack_start(self.btn_open)

        self.btn_save = Gtk.Button(tooltip_text=_("save_pdf"))
        self.btn_save.set_icon_name("document-save-symbolic")
        self.btn_save.set_action_name("win.save-file")
        self.header_bar.pack_start(self.btn_save)

        # Tool selection mode button group (Selection, Hand, Pencil)
        tool_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        tool_box.add_css_class("linked")
        tool_box.set_margin_start(12)

        self.btn_tool_select = Gtk.ToggleButton(tooltip_text=_("selection_mode"))
        self.btn_tool_select.set_icon_name("edit-select-all-symbolic")
        self.btn_tool_select.set_active(True)
        self.btn_tool_select.connect("toggled", self._on_tool_mode_toggled, ToolMode.SELECTION)
        tool_box.append(self.btn_tool_select)

        self.btn_tool_hand = Gtk.ToggleButton(tooltip_text=_("hand_mode"))
        self.btn_tool_hand.set_icon_name("input-mouse-symbolic")
        self.btn_tool_hand.connect("toggled", self._on_tool_mode_toggled, ToolMode.HAND)
        tool_box.append(self.btn_tool_hand)

        self.btn_tool_annot = Gtk.ToggleButton(tooltip_text=_("annot_mode"))
        self.btn_tool_annot.set_icon_name("document-edit-symbolic")
        self.btn_tool_annot.connect("toggled", self._on_tool_mode_toggled, None) # Will check active annot mode inside toggled handler
        tool_box.append(self.btn_tool_annot)

        self.btn_tool_annot_menu = Gtk.MenuButton()
        self.btn_tool_annot_menu.set_tooltip_text(_("annot_mode"))
        
        annot_menu = Gio.Menu()
        annot_menu.append(_("highlight"), "win.set-tool-highlight")
        annot_menu.append(_("underline"), "win.set-tool-underline")
        annot_menu.append(_("add_note"), "win.set-tool-note")
        self.btn_tool_annot_menu.set_menu_model(annot_menu)
        tool_box.append(self.btn_tool_annot_menu)

        # Color picker button directly in the headerbar toolbar box
        self.btn_color = Gtk.ColorButton()
        self.btn_color.set_use_alpha(True)
        self.btn_color.set_tooltip_text(_("choose_color"))
        self.btn_color.set_rgba(self.current_color)
        self.btn_color.connect("color-set", self._on_color_changed)
        tool_box.append(self.btn_color)

        # Opacity dropdown in header bar
        self.opacity_dropdown = Gtk.DropDown.new_from_strings(["10%", "25%", "50%", "75%", "80%", "90%", "100%"])
        self.opacity_dropdown.set_valign(Gtk.Align.CENTER)
        self.opacity_dropdown.set_selected(6)  # Default is 100% (index 6)
        self.opacity_dropdown.set_tooltip_text("Opacidade / Opacity")
        self.opacity_dropdown.connect("notify::selected", self._on_opacity_dropdown_changed)
        tool_box.append(self.opacity_dropdown)

        self.header_bar.pack_start(tool_box)

        # Middle section (custom page entry + navigation)
        self.nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.nav_box.add_css_class("linked")

        self.btn_prev = Gtk.Button(tooltip_text=_("prev_page"))
        self.btn_prev.set_icon_name("go-previous-symbolic")
        self.btn_prev.set_action_name("win.prev-page")
        self.nav_box.append(self.btn_prev)

        self.page_entry = Gtk.Entry()
        self.page_entry.set_width_chars(6)
        self.page_entry.set_alignment(0.5)
        self.page_entry.set_valign(Gtk.Align.CENTER)
        self.page_entry.connect("activate", self._on_page_entry_activated)
        self.nav_box.append(self.page_entry)

        self.total_pages_label = Gtk.Label(label=f"{_('page_of')} 0")
        self.total_pages_label.set_margin_start(4)
        self.total_pages_label.set_margin_end(8)
        self.nav_box.append(self.total_pages_label)

        self.btn_next = Gtk.Button(tooltip_text=_("next_page"))
        self.btn_next.set_icon_name("go-next-symbolic")
        self.btn_next.set_action_name("win.next-page")
        self.nav_box.append(self.btn_next)

        self.header_bar.set_title_widget(self.nav_box)

        # End section
        self.btn_sidebar = Gtk.ToggleButton(tooltip_text=_("sidebar"))
        self.btn_sidebar.set_icon_name("sidebar-show-symbolic")
        self.btn_sidebar.set_active(True)
        self.header_bar.pack_end(self.btn_sidebar)

        # Hamburger Menu
        self.btn_menu = Gtk.MenuButton(tooltip_text=_("main_menu"))
        self.btn_menu.set_icon_name("open-menu-symbolic")
        
        menu = Gio.Menu()
        section_view = Gio.Menu()
        section_view.append(_("continuous_view"), "win.toggle-view-mode")
        menu.append_section(None, section_view)
        
        # Submenu for interface language
        lang_menu = Gio.Menu()
        lang_menu.append("Português (Brasil)", "win.set-interface-lang-pt")
        lang_menu.append("English", "win.set-interface-lang-en")
        menu.append_submenu(_("language"), lang_menu)
        
        section_app = Gio.Menu()
        section_app.append(_("keyboard_shortcuts"), "win.show-shortcuts")
        section_app.append(_("about_app"), "win.show-about")
        menu.append_section(None, section_app)

        self.btn_menu.set_menu_model(menu)
        self.header_bar.pack_end(self.btn_menu)

        # Zoom Controls
        self.zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.zoom_box.add_css_class("linked")

        self.btn_zoom_out = Gtk.Button(tooltip_text=_("zoom_out"))
        self.btn_zoom_out.set_icon_name("zoom-out-symbolic")
        self.btn_zoom_out.set_action_name("win.zoom-out")
        self.zoom_box.append(self.btn_zoom_out)

        self.btn_zoom_menu = Gtk.MenuButton(tooltip_text=_("zoom_options"))
        self.btn_zoom_menu.set_label("100%")
        
        zoom_menu = Gio.Menu()
        zoom_menu.append(_("fit_width"), "win.zoom-fit-width")
        zoom_menu.append(_("fit_page"), "win.zoom-fit-page")
        
        preset_section = Gio.Menu()
        for preset in ZOOM_PRESETS:
            label = f"{int(preset * 100)}%"
            item = Gio.MenuItem.new(label, "win.zoom-to")
            item.set_action_and_target_value("win.zoom-to", GLib.Variant.new_double(preset))
            preset_section.append_item(item)
            
        zoom_menu.append_section(None, preset_section)
        self.btn_zoom_menu.set_menu_model(zoom_menu)
        self.zoom_box.append(self.btn_zoom_menu)

        self.btn_zoom_in = Gtk.Button(tooltip_text=_("zoom_in"))
        self.btn_zoom_in.set_icon_name("zoom-in-symbolic")
        self.btn_zoom_in.set_action_name("win.zoom-in")
        self.zoom_box.append(self.btn_zoom_in)

        self.header_bar.pack_end(self.zoom_box)

        # 2. Main Content nested Split Views (Left Sidebar for Pages/Chapters/Annots, Right Sidebar for TTS)
        # Left Split View container
        self.split_view_left = Adw.OverlaySplitView()
        self.split_view_left.set_sidebar_position(Gtk.PackType.START)
        self.split_view_left.set_min_sidebar_width(280)
        self.split_view_left.set_max_sidebar_width(340)
        self.split_view_left.bind_property("show-sidebar", self.btn_sidebar_left, "active", GObject.BindingFlags.BIDIRECTIONAL)
        self.toolbar_view.set_content(self.split_view_left)

        # Right Split View container
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_sidebar_position(Gtk.PackType.END)
        self.split_view.set_min_sidebar_width(320)
        self.split_view.set_max_sidebar_width(400)
        self.split_view.bind_property("show-sidebar", self.btn_sidebar, "active", GObject.BindingFlags.BIDIRECTIONAL)
        self.split_view_left.set_content(self.split_view)

        # 3. Left Sidebar Content (Notebook or ViewStack with Switcher)
        left_sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left_sidebar_box.set_margin_top(8)
        left_sidebar_box.set_margin_bottom(8)
        left_sidebar_box.set_margin_start(8)
        left_sidebar_box.set_margin_end(8)
        left_sidebar_box.set_vexpand(True)
        
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self.view_stack_switcher = Adw.ViewSwitcher(stack=self.view_stack)
        self.view_stack_switcher.set_halign(Gtk.Align.CENTER)
        left_sidebar_box.append(self.view_stack_switcher)
        left_sidebar_box.append(self.view_stack)

        # Left Tab 1: Pages/Miniaturas
        self.left_pages_list = Gtk.ListBox()
        self.left_pages_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.left_pages_list.set_activate_on_single_click(True)
        self.left_pages_list.connect("row-activated", self._on_left_page_row_activated)
        
        scroller_pages = Gtk.ScrolledWindow()
        scroller_pages.set_child(self.left_pages_list)
        self.view_stack.add_titled_with_icon(
            scroller_pages, "pages", _("tab_pages"), "format-justify-fill-symbolic"
        )

        # Left Tab 2: Sumário/Chapters
        self.left_chapters_list = Gtk.ListBox()
        self.left_chapters_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.left_chapters_list.set_activate_on_single_click(True)
        self.left_chapters_list.connect("row-activated", self._on_left_chapter_row_activated)
        
        scroller_chapters = Gtk.ScrolledWindow()
        scroller_chapters.set_child(self.left_chapters_list)
        self.view_stack.add_titled_with_icon(
            scroller_chapters, "chapters", _("tab_chapters"), "view-list-bullet-symbolic"
        )

        self.split_view_left.set_sidebar(left_sidebar_box)

        # 4. Document Viewport
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.add_css_class("pdf-viewer-scroller")
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)

        # Drag controller on self.scroller for smooth hand/grab scrolling
        self.scroller_drag = Gtk.GestureDrag()
        self.scroller_drag.connect("drag-begin", self._on_scroller_drag_begin)
        self.scroller_drag.connect("drag-update", self._on_scroller_drag_update)
        self.scroller_drag.connect("drag-end", self._on_scroller_drag_end)
        self.scroller.add_controller(self.scroller_drag)

        # Single page view structure
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(False)
        
        self.overlay = Gtk.Overlay()
        self.overlay.set_halign(Gtk.Align.CENTER)
        self.overlay.set_valign(Gtk.Align.CENTER)
        self.overlay.add_css_class("pdf-page-shadow")
        self.overlay.set_child(self.picture)

        self.selection_layer = Gtk.DrawingArea()
        self.selection_layer.set_halign(Gtk.Align.START)
        self.selection_layer.set_valign(Gtk.Align.START)
        self.selection_layer.set_draw_func(self._draw_selection_overlay)
        self.overlay.add_overlay(self.selection_layer)

        # Drag controller for single page
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_single_drag_begin)
        drag.connect("drag-update", self._on_single_drag_update)
        drag.connect("drag-end", self._on_single_drag_end)
        self.selection_layer.add_controller(drag)

        # Mouse scroll zoom controller (Ctrl + Scroll)
        scroll_ctrl = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_ctrl.connect("scroll", self._on_mouse_scroll)
        self.scroller.add_controller(scroll_ctrl)
        self.scroller.get_vadjustment().connect("value-changed", self._on_viewport_scrolled)

        # Welcome Screen (StatusPage) as default content
        self.welcome_page = Adw.StatusPage(
            icon_name="document-open-symbolic",
            title=_("app_name"),
            description=_("welcome_desc"),
        )
        welcome_btn = Gtk.Button(label=_("choose_file"), css_classes=["suggested-action", "pill", "welcome-open-btn"])
        welcome_btn.set_action_name("win.open-file")
        self.welcome_page.set_child(welcome_btn)
        
        self.scroller.set_child(self.welcome_page)
        self.split_view.set_content(self.scroller)

        # Contextual Selection Popover
        self.popover = Gtk.Popover()
        self.popover.set_autohide(True)
        self.popover.set_position(Gtk.PositionType.TOP)

        pop_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pop_box.add_css_class("linked")

        btn_highlight = Gtk.Button(tooltip_text=_("highlight"))
        btn_highlight.set_icon_name("document-edit-symbolic")
        btn_highlight.connect("clicked", lambda _: self._apply_annotation(AnnotationType.HIGHLIGHT))
        pop_box.append(btn_highlight)

        btn_underline = Gtk.Button(tooltip_text=_("underline"))
        btn_underline.set_icon_name("format-text-underline-symbolic")
        btn_underline.connect("clicked", lambda _: self._apply_annotation(AnnotationType.UNDERLINE))
        pop_box.append(btn_underline)

        btn_note = Gtk.Button(tooltip_text=_("add_note"))
        btn_note.set_icon_name("text-x-generic-symbolic")
        btn_note.connect("clicked", lambda _: self._apply_annotation(AnnotationType.NOTE))
        pop_box.append(btn_note)

        btn_speak = Gtk.Button(tooltip_text=_("speak_selection"))
        btn_speak.set_icon_name("audio-volume-high-symbolic")
        btn_speak.connect("clicked", lambda _: self._on_read_selection())
        pop_box.append(btn_speak)

        # Color picker inside popover
        self.pop_color_btn = Gtk.ColorButton()
        self.pop_color_btn.set_use_alpha(True)
        self.pop_color_btn.set_valign(Gtk.Align.CENTER)
        self.pop_color_btn.set_rgba(self.current_color)
        self.pop_color_btn.connect("color-set", self._on_color_changed)
        pop_box.append(self.pop_color_btn)

        # Opacity dropdown inside popover
        self.pop_opacity_dropdown = Gtk.DropDown.new_from_strings(["10%", "25%", "50%", "75%", "80%", "90%", "100%"])
        self.pop_opacity_dropdown.set_valign(Gtk.Align.CENTER)
        self.pop_opacity_dropdown.set_selected(6)  # Default is 100% (index 6)
        self.pop_opacity_dropdown.set_tooltip_text("Opacidade / Opacity")
        self.pop_opacity_dropdown.connect("notify::selected", self._on_opacity_dropdown_changed)
        pop_box.append(self.pop_opacity_dropdown)

        self.popover.set_child(pop_box)

        # 5. Right Sidebar Layout
        sidebar_scroller = Gtk.ScrolledWindow()
        sidebar_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        sidebar_box.add_css_class("sidebar-container")
        sidebar_box.set_margin_top(16)
        sidebar_box.set_margin_bottom(16)
        sidebar_box.set_margin_start(16)
        sidebar_box.set_margin_end(16)

        # TTS Configuration Group
        tts_group = Adw.PreferencesGroup(title=_("audio_reading"))
        sidebar_box.append(tts_group)

        # Language Row using Adw.ComboRow
        self.lang_model = Gtk.StringList()
        for opt in LANGUAGE_OPTIONS:
            self.lang_model.append(opt.label)
            
        self.lang_row = Adw.ComboRow(
            title=_("language"),
            model=self.lang_model,
        )
        self.lang_row.connect("notify::selected", self._on_language_row_changed)
        tts_group.add(self.lang_row)

        # Voice Row using Adw.ComboRow
        self.voice_model = Gtk.StringList()
        self.voice_row = Adw.ComboRow(
            title=_("voice"),
            model=self.voice_model,
        )
        tts_group.add(self.voice_row)

        # Speed Row (Gtk.Scale suffix)
        speed_row = Adw.ActionRow(title=_("speed"))
        self.speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -50, 100, 5)
        self.speed_scale.set_value(0)
        self.speed_scale.set_hexpand(True)
        self.speed_scale.set_size_request(150, -1)
        self.speed_scale.set_valign(Gtk.Align.CENTER)
        self.speed_scale.set_draw_value(True)
        self.speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.speed_scale.set_format_value_func(self._format_speed_value)
        self.speed_scale.connect("value-changed", self._on_speed_changed)
        speed_row.add_suffix(self.speed_scale)
        tts_group.add(speed_row)

        # TTS Action Buttons
        actions_row = Adw.ActionRow()
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_halign(Gtk.Align.CENTER)

        btn_read_page = Gtk.Button(label=_("read_page"), tooltip_text=_("read_page"))
        btn_read_page.set_action_name("win.read-page")
        btn_read_page.add_css_class("suggested-action")
        actions_box.append(btn_read_page)

        btn_read_sel = Gtk.Button(label=_("read_selection"), tooltip_text=_("read_selection"))
        btn_read_sel.set_action_name("win.read-selection")
        btn_read_sel.add_css_class("accent")
        actions_box.append(btn_read_sel)

        # Redundant Sidebar playback control buttons
        self.btn_sidebar_pause = Gtk.Button(tooltip_text=_("play") + " / " + _("pause"))
        self.btn_sidebar_pause.set_icon_name("media-playback-pause-symbolic")
        self.btn_sidebar_pause.set_action_name("win.play-pause")
        actions_box.append(self.btn_sidebar_pause)

        btn_sidebar_stop = Gtk.Button(tooltip_text=_("stop_reading"))
        btn_sidebar_stop.set_icon_name("media-playback-stop-symbolic")
        btn_sidebar_stop.set_action_name("win.stop-audio")
        actions_box.append(btn_sidebar_stop)

        actions_row.set_child(actions_box)
        tts_group.add(actions_row)

        # Extracted Text Group
        text_group = Adw.PreferencesGroup(title=_("extracted_text"))
        sidebar_box.append(text_group)

        self.text_buffer = Gtk.TextBuffer()
        self.text_view = Gtk.TextView(buffer=self.text_buffer)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_vexpand(True)
        self.text_view.add_css_class("sidebar-textview")

        text_scroller = Gtk.ScrolledWindow()
        text_scroller.set_min_content_height(300)
        text_scroller.set_child(self.text_view)
        text_scroller.add_css_class("card")
        text_group.add(text_scroller)

        sidebar_scroller.set_child(sidebar_box)
        self.split_view.set_sidebar(sidebar_scroller)

        # 6. Playback Bottom Toolbar (revealed when playing)
        self.playback_revealer = Gtk.Revealer()
        self.playback_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        
        self.playback_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.playback_bar.add_css_class("playback-bar")
        self.playback_revealer.set_child(self.playback_bar)
        
        # Audio control buttons
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        controls_box.add_css_class("linked")
        controls_box.set_valign(Gtk.Align.CENTER)

        self.btn_play_pause = Gtk.Button()
        self.btn_play_pause.set_icon_name("media-playback-pause-symbolic")
        self.btn_play_pause.set_action_name("win.play-pause")
        controls_box.append(self.btn_play_pause)

        btn_stop = Gtk.Button(tooltip_text=_("stop_reading"))
        btn_stop.set_icon_name("media-playback-stop-symbolic")
        btn_stop.set_action_name("win.stop-audio")
        controls_box.append(btn_stop)
        self.playback_bar.append(controls_box)

        # Status text / Voice labels
        self.status_label = Gtk.Label()
        self.status_label.add_css_class("status-label")
        self.status_label.set_hexpand(True)
        self.status_label.set_xalign(0.0)
        self.playback_bar.append(self.status_label)

        # Loading Spinner
        self.spinner = Gtk.Spinner()
        self.playback_bar.append(self.spinner)

        # Speed slider in bottom playback bar
        self.bottom_speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -50, 100, 5)
        self.bottom_speed_scale.set_valign(Gtk.Align.CENTER)
        self.bottom_speed_scale.set_size_request(120, -1)
        self.bottom_speed_scale.set_value(0)
        self.bottom_speed_scale.set_draw_value(True)
        self.bottom_speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.bottom_speed_scale.set_format_value_func(self._format_speed_value)
        self.bottom_speed_scale.connect("value-changed", self._on_speed_changed)
        self.playback_bar.append(self.bottom_speed_scale)

        self.toolbar_view.add_bottom_bar(self.playback_revealer)

        # Initialize defaults
        self._update_voices_for_lang_code(self.current_language)

    # ------------------------------------------------------------------
    # Action Maps & Hotkeys
    # ------------------------------------------------------------------

    def _setup_actions(self) -> None:
        actions = [
            ("open-file", self._on_open_file_clicked),
            ("save-file", self._on_save_file_clicked),
            ("prev-page", lambda *_: self._navigate_page(-1)),
            ("next-page", lambda *_: self._navigate_page(1)),
            ("zoom-in", lambda *_: self._adjust_zoom(ZOOM_STEP)),
            ("zoom-out", lambda *_: self._adjust_zoom(-ZOOM_STEP)),
            ("zoom-fit-width", self._on_zoom_fit_width),
            ("zoom-fit-page", self._on_zoom_fit_page),
            ("toggle-view-mode", self._on_toggle_view_mode),
            ("read-page", self._on_read_page),
            ("read-selection", self._on_read_selection),
            ("play-pause", lambda *_: self.tts.toggle_pause()),
            ("stop-audio", lambda *_: self.tts.stop()),
            ("show-shortcuts", self._on_show_shortcuts),
            ("show-about", self._on_show_about),
            
            # Undo action
            ("undo", self._on_undo),

            # Tools selection
            ("set-tool-selection", lambda *_: self.btn_tool_select.set_active(True)),
            ("set-tool-hand", lambda *_: self.btn_tool_hand.set_active(True)),
            ("set-tool-highlight", lambda *_: self._set_tool_mode(ToolMode.HIGHLIGHT)),
            ("set-tool-underline", lambda *_: self._set_tool_mode(ToolMode.UNDERLINE)),
            ("set-tool-note", lambda *_: self._set_tool_mode(ToolMode.NOTE)),

            # Interface Language selection
            ("set-interface-lang-pt", lambda *_: self._change_interface_lang("pt")),
            ("set-interface-lang-en", lambda *_: self._change_interface_lang("en")),
        ]

        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        # Parameterized zoom-to action
        zoom_to_act = Gio.SimpleAction.new("zoom-to", GLib.VariantType.new("d"))
        zoom_to_act.connect("activate", self._on_zoom_to_activated)
        self.add_action(zoom_to_act)

    # ------------------------------------------------------------------
    # Tool Selection Handler
    # ------------------------------------------------------------------

    def _on_tool_mode_toggled(self, button: Gtk.ToggleButton, mode: ToolMode | None) -> None:
        if button.get_active():
            # If mode is None, we use last_annot_mode
            if mode is None:
                mode = self.last_annot_mode
            
            # Deactivate others
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
            # Fallback to selection mode if no toggle button is active
            if (not self.btn_tool_select.get_active() and 
                not self.btn_tool_hand.get_active() and 
                not self.btn_tool_annot.get_active()):
                self.btn_tool_select.set_active(True)

    def _set_tool_mode(self, mode: ToolMode) -> None:
        self.last_annot_mode = mode
        self.btn_tool_annot.set_active(True)
        # If the button was already active, toggled signal might not fire, so we force mode set:
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
        
        # Apply cursor to continuous page drawing areas too
        if self.view_mode == ViewMode.CONTINUOUS and self.renderer.page_widgets:
            for page_data in self.renderer.page_widgets:
                page_data["drawing_area"].set_cursor(cursor)

    def _change_interface_lang(self, lang_code: str) -> None:
        from . import locale
        locale.LANG = lang_code
        self._refresh_ui_translations()

    def _refresh_ui_translations(self) -> None:
        self.set_title(_("app_name"))
        
        # Tooltips / Labels
        if hasattr(self, 'btn_sidebar_left'):
            self.btn_sidebar_left.set_tooltip_text(_("sidebar"))
        if hasattr(self, 'btn_sidebar'):
            self.btn_sidebar.set_tooltip_text(_("sidebar"))
        if hasattr(self, 'btn_save'):
            self._update_save_state()
            
        if hasattr(self, 'btn_tool_select'):
            self.btn_tool_select.set_tooltip_text(_("selection_mode"))
        if hasattr(self, 'btn_tool_hand'):
            self.btn_tool_hand.set_tooltip_text(_("hand_mode"))
        if hasattr(self, 'btn_tool_annot'):
            self.btn_tool_annot.set_tooltip_text(_("annot_mode"))
        if hasattr(self, 'btn_tool_annot_menu'):
            self.btn_tool_annot_menu.set_tooltip_text(_("annot_mode"))
        if hasattr(self, 'btn_color'):
            self.btn_color.set_tooltip_text(_("choose_color"))
            
        if hasattr(self, 'btn_prev'):
            self.btn_prev.set_tooltip_text(_("prev_page"))
        if hasattr(self, 'btn_next'):
            self.btn_next.set_tooltip_text(_("next_page"))
            
        if hasattr(self, 'btn_zoom_out'):
            self.btn_zoom_out.set_tooltip_text(_("zoom_out"))
        if hasattr(self, 'btn_zoom_menu'):
            self.btn_zoom_menu.set_tooltip_text(_("zoom_options"))
        if hasattr(self, 'btn_zoom_in'):
            self.btn_zoom_in.set_tooltip_text(_("zoom_in"))
            
        # Left Tabs
        if hasattr(self, 'view_stack'):
            pages_child = self.view_stack.get_child_by_name("pages")
            if pages_child:
                pages_page = self.view_stack.get_page(pages_child)
                if pages_page:
                    pages_page.set_title(_("tab_pages"))
            chapters_child = self.view_stack.get_child_by_name("chapters")
            if chapters_child:
                chapters_page = self.view_stack.get_page(chapters_child)
                if chapters_page:
                    chapters_page.set_title(_("tab_chapters"))
                
        # Right Sidebar labels
        if hasattr(self, 'right_title_label'):
            self.right_title_label.set_label(_("audio_reading"))
        if hasattr(self, 'voice_label'):
            self.voice_label.set_label(_("voice"))
        if hasattr(self, 'speed_label'):
            self.speed_label.set_label(_("speed"))
        if hasattr(self, 'btn_read_page'):
            self.btn_read_page.set_label(_("read_page"))
        if hasattr(self, 'btn_read_sel'):
            self.btn_read_sel.set_label(_("read_selection"))
        if hasattr(self, 'text_title_label'):
            self.text_title_label.set_label(_("extracted_text"))
        if hasattr(self, 'empty_label'):
            self.empty_label.set_label(_("select_text_prompt"))
            
        # Hamburger Menu
        if hasattr(self, 'btn_menu'):
            menu = Gio.Menu()
            section_view = Gio.Menu()
            section_view.append(_("continuous_view"), "win.toggle-view-mode")
            menu.append_section(None, section_view)
            
            lang_menu = Gio.Menu()
            lang_menu.append("Português (Brasil)", "win.set-interface-lang-pt")
            lang_menu.append("English", "win.set-interface-lang-en")
            menu.append_submenu(_("language"), lang_menu)
            
            section_app = Gio.Menu()
            section_app.append(_("keyboard_shortcuts"), "win.show-shortcuts")
            section_app.append(_("about_app"), "win.show-about")
            menu.append_section(None, section_app)
            
            self.btn_menu.set_menu_model(menu)

        # Annotations menu options (refresh actions/labels)
        if hasattr(self, 'btn_tool_annot_menu'):
            annot_menu = Gio.Menu()
            annot_menu.append(_("highlight"), "win.set-tool-highlight")
            annot_menu.append(_("underline"), "win.set-tool-underline")
            annot_menu.append(_("add_note"), "win.set-tool-note")
            self.btn_tool_annot_menu.set_menu_model(annot_menu)
            
        # Reload Left Sidebar lists
        self._reload_left_sidebar()

    # ------------------------------------------------------------------
    # Left Sidebar Loading & Syncing
    # ------------------------------------------------------------------

    def _reload_left_sidebar(self) -> None:
        if not self.renderer.doc:
            return

        # 1. Pages/Miniaturas Tab
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
                
                # Tag reference to destination page
                row._target_page = page - 1
                row.set_child(box)
                self.left_chapters_list.append(row)
        else:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=_("no_chapters"))
            label.set_sensitive(False)
            row.set_child(label)
            self.left_chapters_list.append(row)

        # Annotations Tab removed as requested

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
            h_with_spacing = self.renderer.page_h + 24
            target_y = idx * h_with_spacing
            vadj = self.scroller.get_vadjustment()
            self._is_navigating = True
            vadj.set_value(min(target_y, vadj.get_upper() - vadj.get_page_size()))
            self._is_navigating = False
        else:
            self.selection.clear_selection()
            self._render_view()

    # ------------------------------------------------------------------
    # Navigation & PDF loading
    # ------------------------------------------------------------------

    def open_pdf(self, path: str) -> None:
        """Load and display the PDF file at *path*."""
        if not fitz:
            self.set_status(_("err_pymupdf"))
            return

        try:
            if self.renderer.doc:
                self.renderer.doc.close()
                self.tts.stop()

            doc = fitz.open(path)
            self.pdf_path = path
            self.current_page = 0
            self.selection.clear_selection()
            self.renderer.set_document(doc)
            self.has_unsaved_changes = False
            self.annotation_history.clear()
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

        # Update zoom label
        self.btn_zoom_menu.set_label(f"{int(self.renderer.zoom * 100)}%")

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
            self.total_pages_label.set_text(f"{_('page_of')} {len(self.renderer.doc)}")

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
                self.selection.clear_selection()
                self._render_view()

    # ------------------------------------------------------------------
    # Continuous View Lazy Loading
    # ------------------------------------------------------------------

    def _setup_continuous_layout(self) -> None:
        pages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        pages_box.set_halign(Gtk.Align.CENTER)
        pages_box.set_margin_top(24)
        pages_box.set_margin_bottom(24)

        # Call renderer to create structure
        self.renderer.setup_continuous_layout(
            pages_box,
            self._draw_page_selection_overlay,
            self._on_continuous_drag_begin,
            self._on_continuous_drag_update,
            self._on_continuous_drag_end
        )
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

    def _on_continuous_page_rendered(self, page_idx: int, words: list[dict]) -> None:
        if page_idx == self.current_page:
            self.selection.set_words(words)

    # ------------------------------------------------------------------
    # Drag Selection Handlers (Selection vs Hand vs direct pen)
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

    # Single Page Drag
    def _on_single_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        self.popover.popdown()
        if self.tool_mode == ToolMode.HAND:
            return
        self.selection.begin_drag(start_x, start_y, self.renderer.zoom)
        self.selection_layer.queue_draw()

    def _on_single_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self.tool_mode == ToolMode.HAND:
            return
        self.selection.update_drag(offset_x, offset_y, self.renderer.zoom)
        self.selection_layer.queue_draw()

    def _on_single_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self.tool_mode == ToolMode.HAND:
            return

        has_selection = self.selection.end_drag(offset_x, offset_y, self.renderer.zoom)
        if has_selection:
            if self.tool_mode == ToolMode.SELECTION:
                self._show_selection_popover(self.selection_layer)
            elif self.tool_mode in (ToolMode.HIGHLIGHT, ToolMode.UNDERLINE, ToolMode.NOTE):
                self._apply_annotation(AnnotationType(self.tool_mode.value))
        self.selection_layer.queue_draw()

    # Continuous Scroll Drag
    def _on_continuous_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float, page_idx: int) -> None:
        self.popover.popdown()
        if self.tool_mode == ToolMode.HAND:
            return

        old_page = self.current_page
        self.current_page = page_idx
        
        page_data = self.renderer.page_widgets[page_idx]
        self.selection.set_words(page_data["words"])

        if old_page != page_idx and old_page < len(self.renderer.page_widgets):
            self.renderer.page_widgets[old_page]["drawing_area"].queue_draw()

        self.selection.begin_drag(start_x, start_y, self.renderer.zoom)
        page_data["drawing_area"].queue_draw()

    def _on_continuous_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float, page_idx: int) -> None:
        if self.tool_mode == ToolMode.HAND:
            return
        self.selection.update_drag(offset_x, offset_y, self.renderer.zoom)
        self.renderer.page_widgets[page_idx]["drawing_area"].queue_draw()

    def _on_continuous_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float, page_idx: int) -> None:
        if self.tool_mode == ToolMode.HAND:
            return

        has_selection = self.selection.end_drag(offset_x, offset_y, self.renderer.zoom)
        page_data = self.renderer.page_widgets[page_idx]
        
        if has_selection:
            if self.tool_mode == ToolMode.SELECTION:
                self._show_selection_popover(page_data["drawing_area"])
            elif self.tool_mode in (ToolMode.HIGHLIGHT, ToolMode.UNDERLINE, ToolMode.NOTE):
                self._apply_annotation(AnnotationType(self.tool_mode.value))
                
        page_data["drawing_area"].queue_draw()

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

    # ------------------------------------------------------------------
    # Drawing Selection Overlays
    # ------------------------------------------------------------------

    def _draw_selection_overlay(self, area: Gtk.DrawingArea, cr: Any, w: int, h: int) -> None:
        self._render_highlights_on_cr(cr)

    def _draw_page_selection_overlay(self, area: Gtk.DrawingArea, cr: Any, w: int, h: int, page_idx: int) -> None:
        if self.current_page == page_idx:
            self._render_highlights_on_cr(cr)

    def _render_highlights_on_cr(self, cr: Any) -> None:
        selected = self.selection.get_selected_words()
        if not selected:
            return

        cr.set_source_rgba(self.current_color.red, self.current_color.green, self.current_color.blue, 0.22)
        for item in selected:
            rect = item["rect"]
            x = rect.x0 * self.renderer.zoom
            y = rect.y0 * self.renderer.zoom
            w = (rect.x1 - rect.x0) * self.renderer.zoom
            h = (rect.y1 - rect.y0) * self.renderer.zoom
            cr.rectangle(x, y, w, h)
            cr.fill()

        cr.set_source_rgba(self.current_color.red, self.current_color.green, self.current_color.blue, 0.90)
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
    # Event callbacks
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Annotations & Save states
    # ------------------------------------------------------------------

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
        closest_idx = 6  # Default to 100% (index 6)
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
        """Prompt the user about unsaved changes. Calls callback_if_can_close() if the user consents to exit."""
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
    # TTS Action Handlers
    # ------------------------------------------------------------------

    def _on_read_page(self, action: Gio.SimpleAction = None, val: Any = None) -> None:
        if not self.renderer.doc:
            return
        page = self.renderer.doc.load_page(self.current_page)
        raw_text = page.get_text("text") or ""
        text = normalize_text_for_tts(sample_text := raw_text.strip())
        if not text:
            self.set_status(_("no_extractable_text"))
            return

        self._run_tts(text)

    def _on_read_selection(self, action: Gio.SimpleAction = None, val: Any = None) -> None:
        text = ""
        bounds = self.text_buffer.get_selection_bounds()
        if bounds:
            start_iter, end_iter = bounds
            text = self.text_buffer.get_text(start_iter, end_iter, True).strip()
            
        if not text:
            text = self.selection.get_selected_text().strip()

        text = normalize_text_for_tts(text)
        if not text:
            self.set_status(_("select_text_prompt"))
            return

        self._run_tts(text)

    def _run_tts(self, text: str) -> None:
        self.spinner.start()
        
        selected_idx = self.voice_row.get_selected()
        voice = ""
        if selected_idx != Gtk.INVALID_LIST_POSITION:
            voice = self.voice_model.get_string(selected_idx)
            
        rate_val = int(self.speed_scale.get_value())
        speed_factor = 1.0 + (rate_val / 100.0)

        self.tts.read_aloud(text, voice, self.current_language, speed_factor)

    def _format_speed_value(self, scale: Gtk.Scale, val: float) -> str:
        speed_factor = 1.0 + (val / 100.0)
        return f"{speed_factor:.2f}x"



    def _on_speed_changed(self, scale: Gtk.Scale) -> None:
        if getattr(self, "_updating_speed", False):
            return
        self._updating_speed = True
        try:
            val = scale.get_value()
            if scale == self.speed_scale:
                self.bottom_speed_scale.set_value(val)
            else:
                self.speed_scale.set_value(val)
            
            rate_val = int(val)
            speed_factor = 1.0 + (rate_val / 100.0)
            self.tts.update_speed(speed_factor)
        finally:
            self._updating_speed = False

    def update_playback_bar_state(self) -> None:
        is_playing = self.tts.is_playing
        self.playback_revealer.set_reveal_child(is_playing)
        
        if is_playing:
            self.spinner.stop()
            selected_idx = self.voice_row.get_selected()
            voice = ""
            if selected_idx != Gtk.INVALID_LIST_POSITION:
                voice = self.voice_model.get_string(selected_idx)
            self.status_label.set_text(f"{_('reading_with_voice')}: {voice}")
            
            if self.tts.is_paused:
                self.btn_play_pause.set_icon_name("media-playback-start-symbolic")
                self.btn_play_pause.set_tooltip_text(_("resume"))
                if self.btn_sidebar_pause:
                    self.btn_sidebar_pause.set_icon_name("media-playback-start-symbolic")
                    self.btn_sidebar_pause.set_tooltip_text(_("resume"))
            else:
                self.btn_play_pause.set_icon_name("media-playback-pause-symbolic")
                self.btn_play_pause.set_tooltip_text(_("pause"))
                if self.btn_sidebar_pause:
                    self.btn_sidebar_pause.set_icon_name("media-playback-pause-symbolic")
                    self.btn_sidebar_pause.set_tooltip_text(_("pause"))

    # ------------------------------------------------------------------
    # Dialogs & Language prompts
    # ------------------------------------------------------------------

    def _prompt_document_language(self, suggested: str) -> None:
        dialog = Adw.Dialog(title=_("doc_lang"))
        dialog.set_content_width(340)
        dialog.set_content_height(180)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        label = Gtk.Label(label=_("select_doc_lang"))
        content.append(label)

        dropdown_model = Gtk.StringList()
        active_idx = 0
        for idx, opt in enumerate(LANGUAGE_OPTIONS):
            dropdown_model.append(opt.label)
            if opt.code == suggested:
                active_idx = idx

        dropdown = Gtk.DropDown(model=dropdown_model)
        dropdown.set_selected(active_idx)
        content.append(dropdown)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_halign(Gtk.Align.END)
        
        btn_cancel = Gtk.Button(label=_("cancel"))
        btn_cancel.connect("clicked", lambda _: dialog.close())
        actions.append(btn_cancel)

        btn_ok = Gtk.Button(label=_("confirm"), css_classes=["suggested-action"])
        actions.append(btn_ok)
        content.append(actions)

        dialog.set_child(content)

        def on_confirm(_btn: Gtk.Button) -> None:
            sel_idx = dropdown.get_selected()
            if sel_idx != Gtk.INVALID_LIST_POSITION:
                chosen = LANGUAGE_OPTIONS[sel_idx].code
                self.current_language = chosen
                self.lang_row.set_selected(sel_idx)
                self._update_voices_for_lang_code(chosen)
            dialog.close()

        btn_ok.connect("clicked", on_confirm)
        dialog.present(self)

    def _on_language_row_changed(self, row: Adw.ComboRow, pspec: Any) -> None:
        idx = row.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION:
            code = LANGUAGE_OPTIONS[idx].code
            self.current_language = code
            self._update_voices_for_lang_code(code)

    def _update_voices_for_lang_code(self, code: str) -> None:
        self.voice_model.splice(0, self.voice_model.get_n_items(), [])
        
        voices = LANGUAGE_TO_VOICES.get(code, LANGUAGE_TO_VOICES["pt-BR"])
        for voice in voices:
            self.voice_model.append(voice)
            
        if voices:
            self.voice_row.set_selected(0)

    # ------------------------------------------------------------------
    # Action handlers & Metadata
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

    def _on_show_shortcuts(self, action: Gio.SimpleAction, param: Any) -> None:
        window = Gtk.ShortcutsWindow(transient_for=self, modal=True)
        window.set_title(_("keyboard_shortcuts"))
        
        section = Gtk.ShortcutsSection()
        section.set_visible(True)
        
        group_doc = Gtk.ShortcutsGroup(title=_("document"))
        group_doc.set_visible(True)
        
        shortcut_open = Gtk.ShortcutsShortcut(accelerator="<Control>o", title=_("open_pdf"))
        shortcut_open.set_visible(True)
        group_doc.append(shortcut_open)

        shortcut_save = Gtk.ShortcutsShortcut(accelerator="<Control>s", title=_("save_pdf"))
        shortcut_save.set_visible(True)
        group_doc.append(shortcut_save)
        
        section.append(group_doc)

        group_nav = Gtk.ShortcutsGroup(title=_("nav_zoom"))
        group_nav.set_visible(True)
        
        shortcut_prev = Gtk.ShortcutsShortcut(accelerator="Left", title=_("prev_page"))
        shortcut_prev.set_visible(True)
        group_nav.append(shortcut_prev)

        shortcut_next = Gtk.ShortcutsShortcut(accelerator="Right", title=_("next_page"))
        shortcut_next.set_visible(True)
        group_nav.append(shortcut_next)

        shortcut_zoom_in = Gtk.ShortcutsShortcut(accelerator="<Control>plus", title=_("zoom_in"))
        shortcut_zoom_in.set_visible(True)
        group_nav.append(shortcut_zoom_in)

        shortcut_zoom_out = Gtk.ShortcutsShortcut(accelerator="<Control>minus", title=_("zoom_out"))
        shortcut_zoom_out.set_visible(True)
        group_nav.append(shortcut_zoom_out)

        section.append(group_nav)

        group_play = Gtk.ShortcutsGroup(title=_("audio_shortcuts"))
        group_play.set_visible(True)

        shortcut_read_page = Gtk.ShortcutsShortcut(accelerator="<Control>r", title=_("read_page"))
        shortcut_read_page.set_visible(True)
        group_play.append(shortcut_read_page)

        shortcut_read_sel = Gtk.ShortcutsShortcut(accelerator="<Control><Shift>r", title=_("read_selection"))
        shortcut_read_sel.set_visible(True)
        group_play.append(shortcut_read_sel)

        shortcut_pause = Gtk.ShortcutsShortcut(accelerator="space", title=_("play") + " / " + _("pause"))
        shortcut_pause.set_visible(True)
        group_play.append(shortcut_pause)

        shortcut_stop = Gtk.ShortcutsShortcut(accelerator="Escape", title=_("stop_reading"))
        shortcut_stop.set_visible(True)
        group_play.append(shortcut_stop)

        section.append(group_play)

        group_tools = Gtk.ShortcutsGroup(title=_("tools_and_edit"))
        group_tools.set_visible(True)

        shortcut_select = Gtk.ShortcutsShortcut(accelerator="<Control>4", title=_("selection_mode"))
        shortcut_select.set_visible(True)
        group_tools.append(shortcut_select)

        shortcut_hand = Gtk.ShortcutsShortcut(accelerator="<Control>1", title=_("hand_mode"))
        shortcut_hand.set_visible(True)
        group_tools.append(shortcut_hand)

        shortcut_highlight = Gtk.ShortcutsShortcut(accelerator="1", title=_("highlight"))
        shortcut_highlight.set_visible(True)
        group_tools.append(shortcut_highlight)

        shortcut_underline = Gtk.ShortcutsShortcut(accelerator="2", title=_("underline"))
        shortcut_underline.set_visible(True)
        group_tools.append(shortcut_underline)

        shortcut_undo = Gtk.ShortcutsShortcut(accelerator="<Control>z", title=_("undo_action"))
        shortcut_undo.set_visible(True)
        group_tools.append(shortcut_undo)

        section.append(group_tools)

        window.set_child(section)
        window.present()

    def _on_show_about(self, action: Gio.SimpleAction, param: Any) -> None:
        dialog = Adw.AboutDialog(
            application_name=_("app_name"),
            developer_name="Geraldo Homero",
            version=APP_VERSION,
            comments=_("about_comments"),
            website=APP_WEBSITE,
            copyright="© 2026 Geraldo Homero",
            license_type=Gtk.License.MIT_X11
        )
        dialog.present(self)

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

    def close_document(self) -> None:
        self.tts.cleanup()
        if self.renderer.doc:
            self.renderer.doc.close()
            self.renderer.doc = None
