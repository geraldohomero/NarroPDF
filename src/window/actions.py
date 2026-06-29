"""Action mappings, keyboard shortcuts and dialogs setup for MainWindow."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gio, Gtk

from ..constants import (
    APP_VERSION,
    APP_WEBSITE,
    ZOOM_STEP,
    ToolMode,
)
from ..locale import _


class WindowActionsMixin:
    """Mixin implementing action maps, about dialogs, and shortcuts for MainWindow."""

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
            ("show-settings", self._on_show_settings),
            ("undo", self._on_undo),
            ("toggle-search", self._on_toggle_search),
            ("set-tool-selection", lambda *_: self.btn_tool_select.set_active(True)),
            ("set-tool-hand", lambda *_: self.btn_tool_hand.set_active(True)),
            ("set-tool-highlight", lambda *_: self._set_tool_mode(ToolMode.HIGHLIGHT)),
            ("set-tool-underline", lambda *_: self._set_tool_mode(ToolMode.UNDERLINE)),
            ("set-tool-note", lambda *_: self._set_tool_mode(ToolMode.NOTE)),
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

    def _on_show_shortcuts(self, action: Gio.SimpleAction, param: str) -> None:
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

        shortcut_search = Gtk.ShortcutsShortcut(accelerator="<Control>f", title=_("search"))
        shortcut_search.set_visible(True)
        group_doc.append(shortcut_search)
        
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

    def _on_show_about(self, action: Gio.SimpleAction, param: str) -> None:
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

    def _on_show_settings(self, action: Gio.SimpleAction, param: str) -> None:
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self, self._on_settings_changed)
        dialog.present()
