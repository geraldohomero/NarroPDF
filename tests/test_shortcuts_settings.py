import unittest
from unittest.mock import MagicMock, patch
from src.constants import get_shortcut_groups
from src.window.annotations import WindowAnnotationsMixin
from src.locale import _

class TestShortcutsCatalog(unittest.TestCase):
    def test_shortcut_groups_include_undo_redo_and_copy(self):
        groups = get_shortcut_groups()
        all_actions = {
            item["action"]: item["accel_label"]
            for grp in groups
            for item in grp["items"]
        }
        self.assertIn("win.undo", all_actions)
        self.assertIn("win.redo", all_actions)
        self.assertIn("win.copy-text", all_actions)
        self.assertIn("Ctrl+Z", all_actions["win.undo"])
        self.assertIn("Ctrl+Shift+Z", all_actions["win.redo"])

    def test_app_shortcuts_registered(self):
        from src.main import LeitorPDFApp
        app = MagicMock(spec=LeitorPDFApp)
        # Call unbound method with mock instance to test registered shortcuts mapping
        LeitorPDFApp._setup_shortcuts(app)
        registered = {
            call[0][0]: call[0][1]
            for call in app.set_accels_for_action.call_args_list
        }
        self.assertIn("win.copy-text", registered)
        self.assertEqual(registered["win.copy-text"], ["<Control>c"])
        self.assertIn("win.undo", registered)
        self.assertEqual(registered["win.undo"], ["<Control>z"])
        self.assertIn("win.redo", registered)
        self.assertEqual(registered["win.redo"], ["<Control><Shift>z", "<Control>y"])

    def test_copy_selected_text(self):
        class DummyWindow(WindowAnnotationsMixin):
            def __init__(self):
                self.selection = MagicMock()
                self.popover = MagicMock()
                self.status_msg = ""
            def set_status(self, msg):
                self.status_msg = msg

        win = DummyWindow()
        win.selection.get_selected_text.return_value = "Texto copiado de teste"
        
        with patch("gi.repository.Gdk.Display.get_default") as mock_get_default:
            mock_clipboard = MagicMock()
            mock_get_default.return_value.get_clipboard.return_value = mock_clipboard
            
            win._on_copy_selected_text()
            
            mock_clipboard.set.assert_called_once_with("Texto copiado de teste")
            win.popover.popdown.assert_called_once()
            self.assertEqual(win.status_msg, _("copied_to_clipboard"))


if __name__ == "__main__":
    unittest.main()
