"""Settings and voice management window for NarroPDF."""

import os
import json
import asyncio
import threading
import urllib.request
from typing import Any, Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gio, Gtk

from ..settings import load_settings, save_settings
from ..locale import _

VOICES_DIR = os.path.expanduser("~/.local/share/narro-pdf/voices/")
CATALOG_CACHE = os.path.expanduser("~/.cache/narro-pdf/voices.json")

def load_piper_catalog() -> dict:
    """Loads/downloads the Piper voices catalog."""
    if os.path.exists(CATALOG_CACHE):
        try:
            with open(CATALOG_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        os.makedirs(os.path.dirname(CATALOG_CACHE), exist_ok=True)
        url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            with open(CATALOG_CACHE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return data
    except Exception as exc:
        print(f"Error loading Piper catalog: {exc}")
        return {}

def download_voice_async(
    files: dict,
    progress_cb: Callable[[int], None],
    finish_cb: Callable[[bool, str | None], None]
) -> None:
    """Downloads voice files in a background thread."""
    def worker():
        try:
            os.makedirs(VOICES_DIR, exist_ok=True)
            onnx_rel = None
            json_rel = None
            for path in files.keys():
                if path.endswith(".onnx"):
                    onnx_rel = path
                elif path.endswith(".onnx.json"):
                    json_rel = path
            
            if not onnx_rel:
                raise ValueError("No .onnx file found for this voice.")
            
            onnx_filename = os.path.basename(onnx_rel)
            onnx_dest = os.path.join(VOICES_DIR, onnx_filename)

            # Download json configuration first
            if json_rel:
                json_filename = os.path.basename(json_rel)
                json_dest = os.path.join(VOICES_DIR, json_filename)
                url_json = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/" + json_rel
                req = urllib.request.Request(
                    url_json, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                )
                with urllib.request.urlopen(req) as response:
                    with open(json_dest, "wb") as f:
                        f.write(response.read())

            # Download large ONNX model
            url_onnx = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/" + onnx_rel
            req = urllib.request.Request(
                url_onnx, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req) as response:
                total_size = int(response.headers.get("content-length", 0))
                bytes_downloaded = 0
                block_size = 16384
                with open(onnx_dest, "wb") as f:
                    while True:
                        block = response.read(block_size)
                        if not block:
                            break
                        f.write(block)
                        bytes_downloaded += len(block)
                        percent = 0
                        if total_size > 0:
                            percent = int(100 * bytes_downloaded / total_size)
                        GLib.idle_add(progress_cb, percent)
            
            GLib.idle_add(finish_cb, True, None)
        except Exception as exc:
            GLib.idle_add(finish_cb, False, str(exc))

    threading.Thread(target=worker, daemon=True).start()


class SettingsDialog(Adw.PreferencesWindow):
    """Dialog displaying Settings/Voice manager UI."""

    def __init__(self, parent: Gtk.Window, on_settings_changed_callback: Callable[[], None]) -> None:
        super().__init__(transient_for=parent, modal=True, title=_("settings"))
        self.set_default_size(680, 520)
        self.on_settings_changed = on_settings_changed_callback
        
        self.settings = load_settings()
        self.piper_catalog = {}
        self.edge_all_voices = []
        self.downloading_voices = set() # Track keys of voices currently downloading
        self.piper_download_widgets = {} # voice_key -> (progress_bar, percent_label)

        # Initialize pages
        self._setup_piper_page()
        self._setup_edge_page()
        
        # Load catalogs in background
        self._load_catalogs()

    def _load_catalogs(self) -> None:
        # Load Piper catalog
        def piper_loaded(catalog):
            self.piper_catalog = catalog
            self._refresh_piper_voices()
        
        def run_piper_load():
            catalog = load_piper_catalog()
            GLib.idle_add(piper_loaded, catalog)
        
        threading.Thread(target=run_piper_load, daemon=True).start()

        # Load Edge voices
        try:
            import edge_tts
            def edge_loaded(voices):
                self.edge_all_voices = voices
                self._refresh_edge_voices()

            def run_edge_load():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                voices = loop.run_until_complete(edge_tts.list_voices())
                loop.close()
                GLib.idle_add(edge_loaded, voices)

            threading.Thread(target=run_edge_load, daemon=True).start()
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Piper TTS Tab
    # ------------------------------------------------------------------
    def _setup_piper_page(self) -> None:
        self.piper_page = Adw.PreferencesPage(
            title="Piper TTS",
            icon_name="audio-x-generic-symbolic"
        )
        
        # Language Selector Group
        lang_group = Adw.PreferencesGroup(title=_("language"))
        self.piper_page.add(lang_group)

        self.piper_lang_model = Gtk.StringList()
        self._refresh_piper_lang_model()

        self.piper_lang_row = Adw.ComboRow(
            title=_("language"),
            model=self.piper_lang_model
        )
        self.piper_lang_row.connect("notify::selected", self._on_piper_lang_changed)
        lang_group.add(self.piper_lang_row)

        # Add language button
        add_lang_row = Adw.ActionRow()
        add_btn = Gtk.Button(label=_("add_language"), css_classes=["suggested-action"])
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect("clicked", self._on_add_language_clicked)
        add_lang_row.add_suffix(add_btn)
        lang_group.add(add_lang_row)

        # Voices List Group
        self.piper_voices_group = Adw.PreferencesGroup(title=_("active_voices"))
        self.piper_page.add(self.piper_voices_group)

        # ListBox inside Group to avoid Adw.PreferencesGroup.remove children warnings
        self.piper_listbox = Gtk.ListBox()
        self.piper_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.piper_listbox.add_css_class("boxed-list")
        self.piper_voices_group.add(self.piper_listbox)

        # Loading status or empty list
        self.piper_empty_label = Gtk.Label(label="Carregando vozes...", css_classes=["dim-label"])
        self.piper_empty_label.set_margin_top(16)
        self.piper_empty_label.set_margin_bottom(16)
        self.piper_voices_group.add(self.piper_empty_label)

        self.add(self.piper_page)

    def _refresh_piper_lang_model(self) -> None:
        self.piper_lang_model.splice(0, self.piper_lang_model.get_n_items(), [])
        self.piper_lang_keys = list(self.settings["active_languages"])
        for code in self.piper_lang_keys:
            label = self.settings["language_labels"].get(code, code)
            self.piper_lang_model.append(f"{label} ({code})")

    def _on_piper_lang_changed(self, row: Adw.ComboRow, pspec: Any) -> None:
        self._refresh_piper_voices()

    def _refresh_piper_voices(self) -> None:
        # Clear voices listbox cleanly
        while True:
            row = self.piper_listbox.get_row_at_index(0)
            if not row:
                break
            self.piper_listbox.remove(row)

        self.piper_download_widgets.clear()

        idx = self.piper_lang_row.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or not self.piper_catalog:
            self.piper_empty_label.set_text("Nenhuma voz disponível ou carregando..." if not self.piper_catalog else "Selecione um idioma")
            self.piper_empty_label.set_visible(True)
            self.piper_listbox.set_visible(False)
            return

        lang_code = self.piper_lang_keys[idx]
        piper_lang = lang_code.replace("-", "_").lower()

        # Find matching voices in catalog
        matching_voices = []
        for voice_key, voice_data in self.piper_catalog.items():
            voice_lang = voice_data.get("language", {}).get("code", "").lower()
            if voice_lang == piper_lang or voice_lang.startswith(piper_lang + "_") or voice_lang.replace("_", "-") == piper_lang:
                matching_voices.append((voice_key, voice_data))

        if not matching_voices:
            self.piper_empty_label.set_text("Nenhuma voz encontrada no catálogo para esta língua.")
            self.piper_empty_label.set_visible(True)
            self.piper_listbox.set_visible(False)
            return

        self.piper_empty_label.set_visible(False)
        self.piper_listbox.set_visible(True)

        for voice_key, voice_data in matching_voices:
            row = Adw.ActionRow(
                title=voice_key,
                subtitle=f"Quality: {voice_data.get('quality', 'medium')} | Speakers: {voice_data.get('num_speakers', 1)}"
            )

            # Check if voice file exists locally
            onnx_filename = f"{voice_key}.onnx"
            onnx_path = os.path.join(VOICES_DIR, onnx_filename)
            is_downloaded = os.path.exists(onnx_path)

            status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            status_box.set_valign(Gtk.Align.CENTER)

            if voice_key in self.downloading_voices:
                # Progress widget
                progress_bar = Gtk.ProgressBar()
                progress_bar.set_size_request(100, -1)
                progress_bar.set_valign(Gtk.Align.CENTER)
                progress_bar.set_fraction(0.0)
                status_box.append(progress_bar)
                
                percent_label = Gtk.Label(label="0%")
                percent_label.add_css_class("dim-label")
                status_box.append(percent_label)
                
                self.piper_download_widgets[voice_key] = (progress_bar, percent_label)
            else:
                if is_downloaded:
                    lbl = Gtk.Label(label=_("downloaded"), css_classes=["success-label"])
                    lbl.set_tooltip_text(f"{_('download_location')}: {onnx_path}")
                    status_box.append(lbl)

                    del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("delete"), css_classes=["destructive-action"])
                    del_btn.connect("clicked", self._on_delete_piper_voice, voice_key)
                    status_box.append(del_btn)
                else:
                    dl_btn = Gtk.Button(label=_("download"), css_classes=["suggested-action"])
                    dl_btn.connect("clicked", self._on_download_piper_voice, voice_key, voice_data, row)
                    status_box.append(dl_btn)

            row.add_suffix(status_box)
            self.piper_listbox.append(row)

    def _on_download_piper_voice(self, btn: Gtk.Button, voice_key: str, voice_data: dict, row: Adw.ActionRow) -> None:
        self.downloading_voices.add(voice_key)
        self._refresh_piper_voices() # Redraw list to show progress widgets

        def progress_cb(percent: int) -> None:
            widgets = self.piper_download_widgets.get(voice_key)
            if widgets:
                progress_bar, percent_label = widgets
                progress_bar.set_fraction(percent / 100.0)
                percent_label.set_text(f"{percent}%")

        def finish_cb(success: bool, err_msg: str | None) -> None:
            self.downloading_voices.discard(voice_key)
            if not success:
                # Show error dialog
                dialog = Adw.MessageDialog(
                    transient_for=self,
                    heading="Erro de Download",
                    body=err_msg or "Erro desconhecido."
                )
                dialog.add_response("ok", _("confirm"))
                dialog.connect("response", lambda *_: dialog.close())
                dialog.present()
            else:
                self.on_settings_changed()
            self._refresh_piper_voices()

        download_voice_async(voice_data.get("files", {}), progress_cb, finish_cb)

    def _on_delete_piper_voice(self, btn: Gtk.Button, voice_key: str) -> None:
        onnx_path = os.path.join(VOICES_DIR, f"{voice_key}.onnx")
        json_path = os.path.join(VOICES_DIR, f"{voice_key}.onnx.json")
        try:
            if os.path.exists(onnx_path):
                os.remove(onnx_path)
            if os.path.exists(json_path):
                os.remove(json_path)
        except Exception as exc:
            print(f"Error deleting files: {exc}")
        
        self.on_settings_changed()
        self._refresh_piper_voices()

    def _on_add_language_clicked(self, btn: Gtk.Button) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("add_language")
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.append(Gtk.Label(label="Insira o código do idioma (ex: fr-FR, it-IT):"))
        
        entry = Gtk.Entry()
        entry.set_placeholder_text("fr-FR")
        content.append(entry)
        
        dialog.set_extra_child(content)
        dialog.add_response("cancel", _("cancel"))
        dialog.add_response("add", _("add_language"))
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        def on_response(d: Adw.MessageDialog, response_id: str) -> None:
            if response_id == "add":
                code = entry.get_text().strip()
                if code:
                    # Look up code label in catalog
                    label = code
                    if self.piper_catalog:
                        normalized = code.replace("-", "_").lower()
                        for v in self.piper_catalog.values():
                            if v.get("language", {}).get("code", "").lower() == normalized:
                                name = v["language"].get("name_english", "")
                                country = v["language"].get("country_english", "")
                                label = f"{name} ({country})" if country else name
                                break
                    
                    if code not in self.settings["active_languages"]:
                        self.settings["active_languages"].append(code)
                        self.settings["language_labels"][code] = label
                        save_settings(self.settings)
                        self.on_settings_changed()
                        
                        self._refresh_piper_lang_model()
                        self._refresh_edge_lang_model()
                        self.piper_lang_row.set_selected(len(self.piper_lang_keys) - 1)
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()

    # ------------------------------------------------------------------
    # Edge TTS Tab
    # ------------------------------------------------------------------
    def _setup_edge_page(self) -> None:
        self.edge_page = Adw.PreferencesPage(
            title="Edge TTS",
            icon_name="audio-volume-high-symbolic"
        )
        
        # Languages Management Group
        self.edge_lang_group = Adw.PreferencesGroup(title=_("language"))
        self.edge_page.add(self.edge_lang_group)

        self.edge_lang_model = Gtk.StringList()
        self._refresh_edge_lang_model()

        self.edge_lang_row = Adw.ComboRow(
            title=_("language"),
            model=self.edge_lang_model
        )
        self.edge_lang_row.connect("notify::selected", self._on_edge_lang_changed)
        self.edge_lang_group.add(self.edge_lang_row)

        # Show/Hide Entire Language Toggle
        self.lang_visible_switch = Gtk.Switch()
        self.lang_visible_switch.set_valign(Gtk.Align.CENTER)
        self.lang_visible_switch.connect("state-set", self._on_lang_visibility_toggled)
        
        self.lang_visible_row = Adw.ActionRow(title="Mostrar idioma na aplicação principal")
        self.lang_visible_row.add_suffix(self.lang_visible_switch)
        self.edge_lang_group.add(self.lang_visible_row)

        # Voices visibility Group
        self.edge_voices_group = Adw.PreferencesGroup(title=_("voices_visibility"))
        self.edge_page.add(self.edge_voices_group)

        # ListBox inside Group to avoid Adw.PreferencesGroup.remove children warnings
        self.edge_listbox = Gtk.ListBox()
        self.edge_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.edge_listbox.add_css_class("boxed-list")
        self.edge_voices_group.add(self.edge_listbox)

        self.edge_empty_label = Gtk.Label(label="Carregando vozes...", css_classes=["dim-label"])
        self.edge_empty_label.set_margin_top(16)
        self.edge_empty_label.set_margin_bottom(16)
        self.edge_voices_group.add(self.edge_empty_label)

        self.add(self.edge_page)

    def _refresh_edge_lang_model(self) -> None:
        self.edge_lang_model.splice(0, self.edge_lang_model.get_n_items(), [])
        self.edge_lang_keys = list(self.settings["language_labels"].keys())
        for code in self.edge_lang_keys:
            label = self.settings["language_labels"].get(code, code)
            self.edge_lang_model.append(f"{label} ({code})")

    def _on_edge_lang_changed(self, row: Adw.ComboRow, pspec: Any) -> None:
        idx = row.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION:
            code = self.edge_lang_keys[idx]
            is_active = code in self.settings["active_languages"]
            self.lang_visible_switch.set_state(is_active)
        self._refresh_edge_voices()

    def _on_lang_visibility_toggled(self, widget: Gtk.Switch, state: bool) -> bool:
        idx = self.edge_lang_row.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION:
            code = self.edge_lang_keys[idx]
            if state:
                if code not in self.settings["active_languages"]:
                    self.settings["active_languages"].append(code)
            else:
                if code in self.settings["active_languages"]:
                    self.settings["active_languages"].remove(code)
            
            save_settings(self.settings)
            self.on_settings_changed()
            self._refresh_piper_lang_model()
        return False

    def _refresh_edge_voices(self) -> None:
        # Clear edge voices listbox cleanly
        while True:
            row = self.edge_listbox.get_row_at_index(0)
            if not row:
                break
            self.edge_listbox.remove(row)

        idx = self.edge_lang_row.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or not self.edge_all_voices:
            self.edge_empty_label.set_text("Carregando..." if not self.edge_all_voices else "Selecione um idioma")
            self.edge_empty_label.set_visible(True)
            self.edge_listbox.set_visible(False)
            return

        lang_code = self.edge_lang_keys[idx]
        normalized_code = lang_code.replace("-", "_").lower()

        # Find matching Edge voices
        matching_voices = []
        for voice in self.edge_all_voices:
            locale = voice.get("Locale", "").replace("-", "_").lower()
            if locale == normalized_code or locale.startswith(normalized_code + "_") or locale.replace("_", "-") == normalized_code:
                matching_voices.append(voice)

        if not matching_voices:
            self.edge_empty_label.set_text("Nenhuma voz do Edge TTS disponível para este idioma.")
            self.edge_empty_label.set_visible(True)
            self.edge_listbox.set_visible(False)
            return

        self.edge_empty_label.set_visible(False)
        self.edge_listbox.set_visible(True)

        for voice in matching_voices:
            name = voice.get("ShortName", "")
            friendly_name = voice.get("FriendlyName", "")
            gender = voice.get("Gender", "Female")
            
            row = Adw.ActionRow(
                title=name,
                subtitle=f"{gender} | {friendly_name}"
            )

            # Visiblity switch
            visibility_switch = Gtk.Switch()
            is_visible = self.settings["edge_voices_visibility"].get(name, True)
            visibility_switch.set_state(is_visible)
            visibility_switch.set_valign(Gtk.Align.CENTER)
            
            visibility_switch.connect("state-set", self._on_edge_voice_visibility_toggled, name)

            row.add_suffix(visibility_switch)
            self.edge_listbox.append(row)

    def _on_edge_voice_visibility_toggled(self, widget: Gtk.Switch, state: bool, voice_name: str) -> bool:
        self.settings["edge_voices_visibility"][voice_name] = state
        save_settings(self.settings)
        self.on_settings_changed()
        return False
