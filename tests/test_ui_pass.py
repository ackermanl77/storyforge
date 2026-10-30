"""Pasada de interfaz (2026-10-29): la ventana recuerda su tamaño y cabe en la pantalla (UI5), y los
atajos de teclado se pueden consultar y cambian de pestaña (UI6)."""
import os
import tempfile
import unittest
from unittest.mock import patch


class FitWindowGeometryTests(unittest.TestCase):
    def setUp(self):
        from app.ui_common import fit_window_geometry
        self.fit = fit_window_geometry

    def test_first_run_uses_the_default_size_capped_to_the_screen(self):
        self.assertEqual(self.fit("", 1920, 1080), "1100x800")
        # 1080p at 150%: about 1280x720 of CustomTkinter units -- 800 tall would not fit.
        self.assertEqual(self.fit("", 1280, 720), "1100x662")

    def test_saved_size_and_position_come_back_inside_the_screen(self):
        self.assertEqual(self.fit("1300x900+40+30", 1920, 1080), "1300x900+40+30")
        self.assertEqual(self.fit("1800x1000+400+200", 1920, 1080), "1766x993+154+87")

    def test_a_position_on_a_missing_monitor_is_dropped(self):
        self.assertEqual(self.fit("1000x700+2500+100", 1920, 1080), "1000x700")
        self.assertEqual(self.fit("1000x700+-1600+100", 1920, 1080), "1000x700")
        self.assertEqual(self.fit("not a geometry", 1920, 1080), "1100x800")


class WindowPreferencesTests(unittest.TestCase):
    def test_geometry_and_maximized_state_round_trip_through_settings(self):
        from app import settings

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"STORYFORGE_USER_DATA_DIR": folder}):
            self.assertEqual(settings.get_ui_preferences()["window_geometry"], "")
            settings.set_ui_preferences({"window_geometry": "1200x820+10+20", "window_zoomed": True})
            prefs = settings.get_ui_preferences()
            self.assertEqual((prefs["window_geometry"], prefs["window_zoomed"]), ("1200x820+10+20", True))


class ShortcutListTests(unittest.TestCase):
    def test_the_list_names_every_global_shortcut_and_f1_opens_it(self):
        from app import strings_es as S
        from app.ui_menu import MenuMixin

        listed = " ".join(keys for keys, _action in S.ATAJOS_LISTA)
        for keys in ("Ctrl+1", "Ctrl+N", "Ctrl+O", "Ctrl+S", "Ctrl+F", "Ctrl+Mayús+F", "Ctrl+Enter", "Esc", "F11", "F1"):
            self.assertIn(keys, listed)
        self.assertEqual(MenuMixin.SHORTCUTS["<F1>"], "show_shortcuts")
        self.assertTrue(callable(MenuMixin.show_shortcuts))


if __name__ == "__main__":
    unittest.main()
