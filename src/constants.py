"""Constants, enums, and configuration for NarroPDF."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ViewMode(StrEnum):
    SINGLE = "single"
    CONTINUOUS = "continuous"


class ToolMode(StrEnum):
    SELECTION = "selection"
    HAND = "hand"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    NOTE = "note"


class AnnotationType(StrEnum):
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    NOTE = "note"


# ---------------------------------------------------------------------------
# Zoom
# ---------------------------------------------------------------------------

DEFAULT_ZOOM: float = 1.4
MIN_ZOOM: float = 0.5
MAX_ZOOM: float = 3.0
ZOOM_STEP: float = 0.15

ZOOM_PRESETS: list[float] = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

PAGE_SPACING: int = 8
WORD_HIT_THRESHOLD_PX: int = 60

# ---------------------------------------------------------------------------
# Languages & Voices
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DocumentLanguage:
    """Represents a supported TTS language."""
    code: str
    label: str


LANGUAGE_OPTIONS: tuple[DocumentLanguage, ...] = (
    DocumentLanguage("pt-BR", "Português (Brasil)"),
    DocumentLanguage("en-US", "English (US)"),
    DocumentLanguage("es-ES", "Español (ES)"),
)

LANGUAGE_TO_VOICES: dict[str, list[str]] = {
    "pt-BR": [
        "pt-BR-FranciscaNeural",
        "pt-BR-AntonioNeural",
        "pt-BR-BrendaNeural",
    ],
    "en-US": [
        "en-US-AriaNeural",
        "en-US-GuyNeural",
        "en-US-JennyNeural",
    ],
    "es-ES": [
        "es-ES-ElviraNeural",
        "es-ES-AlvaroNeural",
    ],
}

PIPER_VOICES: dict[str, dict[str, str]] = {
    "pt-BR": {
        "name": "pt_BR-faber-medium",
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json"
    },
    "en-US": {
        "name": "en_US-amy-medium",
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
    },
    "es-ES": {
        "name": "es_ES-daniele-medium",
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_ES/daniele/medium/es_ES-daniele-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_ES/daniele/medium/es_ES-daniele-medium.onnx.json"
    }
}

DEFAULT_LANGUAGE: str = "pt-BR"

# ---------------------------------------------------------------------------
# Application metadata
# ---------------------------------------------------------------------------

APP_ID: str = "org.geraldohomero.NarroPdf"
APP_NAME: str = "NarroPDF"
APP_DEVELOPER: str = "Geraldo Homero"
APP_VERSION: str = "1.0.0"
APP_WEBSITE: str = "https://github.com/geraldohomero/NarroPDF"


def get_shortcut_groups() -> list[dict]:
    """Catalog of all keyboard shortcuts grouped by category."""
    return [
        {
            "group_id": "document",
            "title_key": "document",
            "items": [
                {"title_key": "open_pdf", "action": "win.open-file", "accels": ["<Control>o"], "accel_label": "Ctrl+O"},
                {"title_key": "save_pdf", "action": "win.save-file", "accels": ["<Control>s"], "accel_label": "Ctrl+S"},
                {"title_key": "search", "action": "win.toggle-search", "accels": ["<Control>f"], "accel_label": "Ctrl+F"},
            ]
        },
        {
            "group_id": "nav_zoom",
            "title_key": "nav_zoom",
            "items": [
                {"title_key": "prev_page", "action": "win.prev-page", "accels": ["Left", "Page_Up"], "accel_label": "Left / Page Up"},
                {"title_key": "next_page", "action": "win.next-page", "accels": ["Right", "Page_Down"], "accel_label": "Right / Page Down"},
                {"title_key": "zoom_in", "action": "win.zoom-in", "accels": ["<Control>plus", "<Control>equal"], "accel_label": "Ctrl + +"},
                {"title_key": "zoom_out", "action": "win.zoom-out", "accels": ["<Control>minus"], "accel_label": "Ctrl + -"},
            ]
        },
        {
            "group_id": "audio_shortcuts",
            "title_key": "audio_shortcuts",
            "items": [
                {"title_key": "read_page", "action": "win.read-page", "accels": ["<Control>r"], "accel_label": "Ctrl+R"},
                {"title_key": "read_selection", "action": "win.read-selection", "accels": ["<Control><Shift>r"], "accel_label": "Ctrl+Shift+R"},
                {"title_key": "play_pause", "action": "win.play-pause", "accels": ["space"], "accel_label": "Espaço / Space"},
                {"title_key": "stop_reading", "action": "win.stop-audio", "accels": ["Escape"], "accel_label": "Esc"},
            ]
        },
        {
            "group_id": "tools_and_edit",
            "title_key": "tools_and_edit",
            "items": [
                {"title_key": "selection_mode", "action": "win.set-tool-selection", "accels": ["<Control>4"], "accel_label": "Ctrl+4"},
                {"title_key": "hand_mode", "action": "win.set-tool-hand", "accels": ["<Control>1"], "accel_label": "Ctrl+1"},
                {"title_key": "highlight", "action": "win.set-tool-highlight", "accels": ["1"], "accel_label": "1"},
                {"title_key": "underline", "action": "win.set-tool-underline", "accels": ["2"], "accel_label": "2"},
                {"title_key": "copy_text", "action": "win.copy-text", "accels": ["<Control>c"], "accel_label": "Ctrl+C"},
                {"title_key": "undo_action", "action": "win.undo", "accels": ["<Control>z"], "accel_label": "Ctrl+Z"},
                {"title_key": "redo_action", "action": "win.redo", "accels": ["<Control><Shift>z", "<Control>y"], "accel_label": "Ctrl+Shift+Z / Ctrl+Y"},
            ]
        },
    ]
