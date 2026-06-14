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

PAGE_SPACING: int = 24
WORD_HIT_THRESHOLD_PX: int = 18

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

DEFAULT_LANGUAGE: str = "pt-BR"

# ---------------------------------------------------------------------------
# Application metadata
# ---------------------------------------------------------------------------

APP_ID: str = "org.geraldohomero.NarroPdf"
APP_NAME: str = "NarroPDF"
APP_DEVELOPER: str = "Geraldo Homero"
APP_VERSION: str = "1.0.0"
APP_WEBSITE: str = "https://github.com/geraldohomero/NarroPDF"
