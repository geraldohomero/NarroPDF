"""Text-to-Speech execution, speed control, language options and voice loading for MainWindow."""

import os
import asyncio
import threading
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gio, Gtk

from ..constants import (
    LANGUAGE_TO_VOICES,
    PIPER_VOICES,
)
from ..utils import normalize_text_for_tts
from ..locale import _
from ..settings import load_settings


class WindowTtsMixin:
    """Mixin implementing text selection reading, dynamic voice listing, speed adjusting, and engine switching."""

    def _on_read_page(self, action: Gio.SimpleAction = None, val: Any = None) -> None:
        if not self.renderer.doc:
            return
        page = self.renderer.doc.load_page(self.current_page)
        raw_text = page.get_text("text") or ""
        text = normalize_text_for_tts(raw_text.strip())
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
        if self.current_engine == "piper" and not self._get_piper_voices(self.current_language):
            self.spinner.stop()
            self._show_no_voices_warning()
            return

        self.spinner.start()
        
        selected_idx = self.voice_row.get_selected()
        voice = ""
        if selected_idx != Gtk.INVALID_LIST_POSITION:
            voice = self.voice_model.get_string(selected_idx)
            
        rate_val = int(self.speed_scale.get_value())
        speed_factor = 1.0 + (rate_val / 100.0)

        # Pass current_engine to the TTS reading process
        self.tts.read_aloud(text, voice, self.current_language, speed_factor, self.current_engine)

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
        active_langs = self.settings.get("active_languages", ["pt-BR", "en-US", "es-ES"])
        labels = self.settings.get("language_labels", {})
        for idx, code in enumerate(active_langs):
            dropdown_model.append(labels.get(code, code))
            if code == suggested:
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
            active_langs = self.settings.get("active_languages", ["pt-BR", "en-US", "es-ES"])
            if sel_idx != Gtk.INVALID_LIST_POSITION and sel_idx < len(active_langs):
                chosen = active_langs[sel_idx]
                self.current_language = chosen
                self.lang_row.set_selected(sel_idx)
                self._update_voices_for_lang_code(chosen)
            dialog.close()

        btn_ok.connect("clicked", on_confirm)
        dialog.present(self)

    def _on_language_row_changed(self, row: Adw.ComboRow, pspec: Any) -> None:
        idx = row.get_selected()
        active_langs = self.settings.get("active_languages", ["pt-BR", "en-US", "es-ES"])
        if idx != Gtk.INVALID_LIST_POSITION and idx < len(active_langs):
            code = active_langs[idx]
            self.current_language = code
            self._update_voices_for_lang_code(code)

    def _update_voices_for_lang_code(self, code: str) -> None:
        if not hasattr(self, "voice_model") or not hasattr(self, "voice_row"):
            return
        self.voice_model.splice(0, self.voice_model.get_n_items(), [])
        
        if self.current_engine == "edge":
            voices = self._get_edge_voices_for_lang(code)
        else:
            voices = self._get_piper_voices(code)
            
        for voice in voices:
            self.voice_model.append(voice)
            
        if voices:
            self.voice_row.set_selected(0)

    def _get_piper_voices(self, code: str) -> list[str]:
        piper_lang = code.replace("-", "_").lower()
        voices = []
        
        # Scan voices directory for other voices matching the language
        voices_dir = os.path.expanduser("~/.local/share/narro-pdf/voices/")
        if os.path.exists(voices_dir):
            for name in os.listdir(voices_dir):
                if name.endswith(".onnx") and name.lower().startswith(piper_lang):
                    v_name = name[:-5] # remove .onnx
                    if v_name not in voices:
                        voices.append(v_name)
                        
        return voices

    def _on_engine_row_changed(self, row: Adw.ComboRow, pspec: Any) -> None:
        idx = row.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION:
            self.current_engine = "edge" if idx == 0 else "piper"
            self._update_voices_for_lang_code(self.current_language)

    def _refresh_lang_combo_model(self) -> None:
        if not hasattr(self, "lang_row") or not hasattr(self, "lang_model"):
            return
        self.settings = load_settings()

        self.lang_model.splice(0, self.lang_model.get_n_items(), [])
        active_langs = self.settings.get("active_languages", ["pt-BR", "en-US", "es-ES"])
        labels = self.settings.get("language_labels", {})
        
        for code in active_langs:
            label = labels.get(code, code)
            self.lang_model.append(label)
            
        if self.current_language in active_langs:
            self.lang_row.set_selected(active_langs.index(self.current_language))
        elif active_langs:
            self.current_language = active_langs[0]
            self.lang_row.set_selected(0)

    def _get_edge_voices_for_lang(self, code: str) -> list[str]:
        visible_set = self.settings.get("edge_voices_visibility", {})
        voices = []
        if getattr(self, "edge_all_voices", None):
            normalized = code.replace("-", "_").lower()
            for v in self.edge_all_voices:
                locale = v.get("Locale", "").replace("-", "_").lower()
                if locale == normalized or locale.startswith(normalized + "_") or locale.replace("_", "-") == normalized:
                    name = v.get("ShortName", "")
                    if name and visible_set.get(name, True):
                        voices.append(name)
        if not voices:
            default_voices = LANGUAGE_TO_VOICES.get(code, [])
            for name in default_voices:
                if name and visible_set.get(name, True):
                    voices.append(name)
        return voices

    def _load_edge_voices_list(self) -> None:
        import edge_tts
        
        def run_load():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                voices = loop.run_until_complete(edge_tts.list_voices())
                loop.close()
                GLib.idle_add(self._on_edge_voices_loaded, voices)
            except Exception as exc:
                print(f"Error loading Edge TTS voices list: {exc}")
                
        threading.Thread(target=run_load, daemon=True).start()

    def _on_edge_voices_loaded(self, voices: list) -> None:
        self.edge_all_voices = voices
        if hasattr(self, "voice_model"):
            self._update_voices_for_lang_code(self.current_language)

    def _show_no_voices_warning(self) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("settings"),
            body=_("no_downloaded_voices")
        )
        dialog.add_response("cancel", _("cancel"))
        dialog.add_response("settings", _("settings"))
        dialog.set_response_appearance("settings", Adw.ResponseAppearance.SUGGESTED)
        
        def on_response(d: Adw.MessageDialog, response_id: str) -> None:
            if response_id == "settings":
                self._on_show_settings(None, "")
            d.close()
            
        dialog.connect("response", on_response)
        dialog.present()
