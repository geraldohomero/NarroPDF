"""Settings manager for NarroPDF."""

import json
import os

SETTINGS_FILE = os.path.expanduser("~/.config/narro-pdf/settings.json")

# Default languages and their metadata
DEFAULT_LANGUAGES = {
    "pt-BR": "Português (Brasil)",
    "en-US": "English (US)",
    "es-AR": "Español (Argentina)",
    "es-ES": "Español (España)",
    "es-MX": "Español (México)",
}

DEFAULT_SETTINGS = {
    # Active languages visible in the main UI
    "active_languages": ["pt-BR", "en-US", "es-ES", "es-AR", "es-MX"],
    # Language labels (code -> label)
    "language_labels": dict(DEFAULT_LANGUAGES),
    # Edge TTS voices visibility (ShortName -> boolean)
    # If not present or True, it is visible. If False, it is hidden.
    "edge_voices_visibility": {},
}

def load_settings() -> dict:
    """Loads settings from settings.json, creating it if necessary."""
    if not os.path.exists(SETTINGS_FILE):
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SETTINGS, f, indent=2)
        except Exception as exc:
            print(f"Error creating settings file: {exc}")
        return dict(DEFAULT_SETTINGS)

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Ensure all default keys exist
            updated = False
            for k, v in DEFAULT_SETTINGS.items():
                if k not in data:
                    data[k] = v
                    updated = True
            
            # Ensure dynamic languages are merged
            for code, label in DEFAULT_LANGUAGES.items():
                if code not in data["language_labels"]:
                    data["language_labels"][code] = label
                    updated = True

            if updated:
                save_settings(data)
            return data
    except Exception as exc:
        print(f"Error reading settings: {exc}")
        return dict(DEFAULT_SETTINGS)

def save_settings(settings: dict) -> None:
    """Saves settings dict to settings.json."""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as exc:
        print(f"Error saving settings: {exc}")
