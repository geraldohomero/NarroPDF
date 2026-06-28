"""UI construction and layout setup for MainWindow."""

import os
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gio, GObject, Gtk

from ..constants import (
    LANGUAGE_OPTIONS,
    ZOOM_PRESETS,
    ViewMode,
    ToolMode,
    AnnotationType,
)
from ..locale import _


class WindowUiMixin:
    """Mixin implementing UI building and visual design for MainWindow."""

    def _build_ui(self) -> None:
        # Load external CSS
        css_provider = Gtk.CssProvider()
        css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "style.css")
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
        self.btn_tool_annot.connect("toggled", self._on_tool_mode_toggled, None)
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
        self.opacity_dropdown.set_selected(6)
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

        # 1.5. Search Bar Setup (Ctrl + F)
        self.search_revealer = Gtk.Revealer()
        self.search_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.search_revealer.set_halign(Gtk.Align.END)
        self.search_revealer.set_valign(Gtk.Align.START)
        self.search_revealer.set_margin_top(12)
        self.search_revealer.set_margin_end(12)
        
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_box.add_css_class("search-bar-box")
        search_box.add_css_class("card")
        
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_width_chars(30)
        self.search_entry.connect("search-changed", self._on_search_text_changed)
        self.search_entry.connect("activate", self._on_search_next)
        
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_search_key_pressed)
        self.search_entry.add_controller(key_controller)
        search_box.append(self.search_entry)
        
        self.btn_search_prev = Gtk.Button(tooltip_text=_("prev_page"))
        self.btn_search_prev.set_icon_name("go-up-symbolic")
        self.btn_search_prev.connect("clicked", self._on_search_prev)
        search_box.append(self.btn_search_prev)
        
        self.btn_search_next = Gtk.Button(tooltip_text=_("next_page"))
        self.btn_search_next.set_icon_name("go-down-symbolic")
        self.btn_search_next.connect("clicked", self._on_search_next)
        search_box.append(self.btn_search_next)
        
        self.search_results_label = Gtk.Label()
        self.search_results_label.set_margin_start(6)
        self.search_results_label.set_margin_end(6)
        search_box.append(self.search_results_label)
        
        self.btn_search_close = Gtk.Button(tooltip_text=_("cancel"))
        self.btn_search_close.set_icon_name("window-close-symbolic")
        self.btn_search_close.connect("clicked", lambda *_: self._on_close_search())
        search_box.append(self.btn_search_close)
        
        self.search_revealer.set_child(search_box)

        # 2. Main Content Split Views
        self.split_view_left = Adw.OverlaySplitView()
        self.split_view_left.set_sidebar_position(Gtk.PackType.START)
        self.split_view_left.set_min_sidebar_width(280)
        self.split_view_left.set_max_sidebar_width(340)
        self.split_view_left.bind_property("show-sidebar", self.btn_sidebar_left, "active", GObject.BindingFlags.BIDIRECTIONAL)
        self.toolbar_view.set_content(self.split_view_left)

        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_sidebar_position(Gtk.PackType.END)
        self.split_view.set_min_sidebar_width(320)
        self.split_view.set_max_sidebar_width(400)
        self.split_view.bind_property("show-sidebar", self.btn_sidebar, "active", GObject.BindingFlags.BIDIRECTIONAL)
        self.split_view_left.set_content(self.split_view)

        # 3. Left Sidebar Content
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

        # Left Tab 1: Pages
        self.left_pages_list = Gtk.ListBox()
        self.left_pages_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.left_pages_list.set_activate_on_single_click(True)
        self.left_pages_list.connect("row-activated", self._on_left_page_row_activated)
        
        scroller_pages = Gtk.ScrolledWindow()
        scroller_pages.set_child(self.left_pages_list)
        self.view_stack.add_titled_with_icon(
            scroller_pages, "pages", _("tab_pages"), "format-justify-fill-symbolic"
        )

        # Left Tab 2: Table of Contents
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

        self.scroller_drag = Gtk.GestureDrag()
        self.scroller_drag.connect("drag-begin", self._on_scroller_drag_begin)
        self.scroller_drag.connect("drag-update", self._on_scroller_drag_update)
        self.scroller_drag.connect("drag-end", self._on_scroller_drag_end)
        self.scroller.add_controller(self.scroller_drag)

        # Single page view components
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

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_single_drag_begin)
        drag.connect("drag-update", self._on_single_drag_update)
        drag.connect("drag-end", self._on_single_drag_end)
        self.selection_layer.add_controller(drag)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_single_click_pressed)
        self.selection_layer.add_controller(click)

        scroll_ctrl = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_ctrl.connect("scroll", self._on_mouse_scroll)
        self.scroller.add_controller(scroll_ctrl)
        self.scroller.get_vadjustment().connect("value-changed", self._on_viewport_scrolled)

        # Welcome screen
        self.welcome_page = Adw.StatusPage(
            icon_name="document-open-symbolic",
            title=_("app_name"),
            description=_("welcome_desc"),
        )
        welcome_btn = Gtk.Button(label=_("choose_file"), css_classes=["suggested-action", "pill", "welcome-open-btn"])
        welcome_btn.set_action_name("win.open-file")
        self.welcome_page.set_child(welcome_btn)
        
        self.scroller.set_child(self.welcome_page)

        # Create viewport overlay to contain scroller and floating top-right search box
        self.viewport_overlay = Gtk.Overlay()
        self.viewport_overlay.set_hexpand(True)
        self.viewport_overlay.set_vexpand(True)
        self.viewport_overlay.set_child(self.scroller)
        self.viewport_overlay.add_overlay(self.search_revealer)

        self.split_view.set_content(self.viewport_overlay)

        # Selection Popover
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

        self.pop_color_btn = Gtk.ColorButton()
        self.pop_color_btn.set_use_alpha(True)
        self.pop_color_btn.set_valign(Gtk.Align.CENTER)
        self.pop_color_btn.set_rgba(self.current_color)
        self.pop_color_btn.connect("color-set", self._on_color_changed)
        pop_box.append(self.pop_color_btn)

        self.pop_opacity_dropdown = Gtk.DropDown.new_from_strings(["10%", "25%", "50%", "75%", "80%", "90%", "100%"])
        self.pop_opacity_dropdown.set_valign(Gtk.Align.CENTER)
        self.pop_opacity_dropdown.set_selected(6)
        self.pop_opacity_dropdown.set_tooltip_text("Opacidade / Opacity")
        self.pop_opacity_dropdown.connect("notify::selected", self._on_opacity_dropdown_changed)
        pop_box.append(self.pop_opacity_dropdown)

        self.popover.set_child(pop_box)

        # 5. Right Sidebar (TTS Configs)
        sidebar_scroller = Gtk.ScrolledWindow()
        sidebar_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        sidebar_box.add_css_class("sidebar-container")
        sidebar_box.set_margin_top(16)
        sidebar_box.set_margin_bottom(16)
        sidebar_box.set_margin_start(16)
        sidebar_box.set_margin_end(16)

        tts_group = Adw.PreferencesGroup(title=_("audio_reading"))
        sidebar_box.append(tts_group)

        # Engine row inside sidebar preferences
        self.engine_model = Gtk.StringList.new(["Edge TTS", "Piper TTS"])
        self.engine_row = Adw.ComboRow(
            title=_("engine"),
            model=self.engine_model,
        )
        self.engine_row.connect("notify::selected", self._on_engine_row_changed)
        tts_group.add(self.engine_row)

        self.lang_model = Gtk.StringList()
        for opt in LANGUAGE_OPTIONS:
            self.lang_model.append(opt.label)
            
        self.lang_row = Adw.ComboRow(
            title=_("language"),
            model=self.lang_model,
        )
        self.lang_row.connect("notify::selected", self._on_language_row_changed)
        tts_group.add(self.lang_row)

        self.voice_model = Gtk.StringList()
        self.voice_row = Adw.ComboRow(
            title=_("voice"),
            model=self.voice_model,
        )
        tts_group.add(self.voice_row)

        speed_row = Adw.ActionRow(title=_("speed"))
        self.speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -50, 300, 5)
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

        # 6. Playback Bottom Toolbar
        self.playback_revealer = Gtk.Revealer()
        self.playback_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        
        self.playback_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.playback_bar.add_css_class("playback-bar")
        self.playback_revealer.set_child(self.playback_bar)
        
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

        self.status_label = Gtk.Label()
        self.status_label.add_css_class("status-label")
        self.status_label.set_hexpand(True)
        self.status_label.set_xalign(0.0)
        self.playback_bar.append(self.status_label)

        self.spinner = Gtk.Spinner()
        self.playback_bar.append(self.spinner)

        self.bottom_speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -50, 300, 5)
        self.bottom_speed_scale.set_valign(Gtk.Align.CENTER)
        self.bottom_speed_scale.set_size_request(120, -1)
        self.bottom_speed_scale.set_value(0)
        self.bottom_speed_scale.set_draw_value(True)
        self.bottom_speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.bottom_speed_scale.set_format_value_func(self._format_speed_value)
        self.bottom_speed_scale.connect("value-changed", self._on_speed_changed)
        self.playback_bar.append(self.bottom_speed_scale)

        self.toolbar_view.add_bottom_bar(self.playback_revealer)
        
        # Default initialization values
        self._update_voices_for_lang_code(self.current_language)

    def _refresh_ui_translations(self) -> None:
        self.set_title(_("app_name"))
        
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

        if hasattr(self, 'btn_tool_annot_menu'):
            annot_menu = Gio.Menu()
            annot_menu.append(_("highlight"), "win.set-tool-highlight")
            annot_menu.append(_("underline"), "win.set-tool-underline")
            annot_menu.append(_("add_note"), "win.set-tool-note")
            self.btn_tool_annot_menu.set_menu_model(annot_menu)
            
        self._reload_left_sidebar()
