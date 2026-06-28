"""Entry point and application class for NarroPDF."""

from __future__ import annotations

import sys
import logging
from typing import Sequence

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

from .constants import APP_ID
from .window import MainWindow

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger(__name__)


class LeitorPDFApp(Adw.Application):
    """The Adw.Application subclass coordinating lifecycle and action shortcuts."""

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE
        )
        self.win: MainWindow | None = None

        self.connect("activate", self.on_activate)
        self.connect("open", self.on_open)

    def on_activate(self, app: Adw.Application) -> None:
        """Invoked when the application is launched normally."""
        self._ensure_window()
        self.win.present()
        self.win.maximize()

    def on_open(self, app: Adw.Application, files: list[Gio.File], n_files: int, hint: str) -> None:
        """Invoked when the application is requested to open files (e.g. from Nautilus)."""
        self._ensure_window()
        self.win.present()
        self.win.maximize()
        
        if n_files > 0:
            file_path = files[0].get_path()
            if file_path:
                log.info("Opening file via activation: %s", file_path)
                self.win.open_pdf(file_path)

    def _ensure_window(self) -> None:
        if self.win is None:
            self.win = MainWindow(self)
            self.win.connect("close-request", self.on_close_request)
            self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        # Map of actions to shortcut accelerator keys
        shortcuts = {
            "win.open-file": ["<Control>o"],
            "win.save-file": ["<Control>s"],
            "win.prev-page": ["Left", "Page_Up"],
            "win.next-page": ["Right", "Page_Down"],
            "win.zoom-in": ["<Control>plus", "<Control>equal"],
            "win.zoom-out": ["<Control>minus"],
            "win.read-page": ["<Control>r"],
            "win.read-selection": ["<Control><Shift>r"],
            "win.play-pause": ["space"],
            "win.stop-audio": ["Escape"],
            "win.set-tool-selection": ["<Control>4"],
            "win.set-tool-hand": ["<Control>1"],
            "win.set-tool-highlight": ["1"],
            "win.set-tool-underline": ["2"],
            "win.undo": ["<Control>z"],
            "win.toggle-search": ["<Control>f"],
        }
        for action, accels in shortcuts.items():
            self.set_accels_for_action(action, accels)

    def on_close_request(self, window: MainWindow) -> bool:
        """Clean up resources when the main window is closed."""
        if window.has_unsaved_changes:
            window.check_unsaved_changes_before_exit(window.close)
            return True  # Cancel current close request, wait for user response

        log.info("MainWindow closing, cleaning up resources.")
        window.close_document()
        return False


def main() -> int:
    """Main execution function."""
    app = LeitorPDFApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
