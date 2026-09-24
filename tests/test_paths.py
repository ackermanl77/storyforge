import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import paths
from app.repetition import _local_nltk_data_dir


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAppPaths(unittest.TestCase):
    def test_dev_root_is_the_project_folder(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertEqual(paths.app_root(), PROJECT_ROOT)
            self.assertEqual(paths.user_data_dir(), PROJECT_ROOT)

    def test_frozen_root_is_the_exe_folder_not_internal(self):
        # PyInstaller 6 onedir: __file__ vive en <dist>/_internal/app/, pero
        # models\ y nltk_data\ estan junto a StoryForge.exe.
        exe = os.path.join("C:\\", "Apps", "StoryForge-App", "StoryForge.exe")
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", exe):
            self.assertEqual(paths.app_root(), os.path.dirname(os.path.abspath(exe)))
            self.assertEqual(
                _local_nltk_data_dir(), os.path.join(os.path.dirname(os.path.abspath(exe)), "nltk_data")
            )

    def test_frozen_user_data_dir_is_under_appdata(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {"APPDATA": os.path.join("C:\\", "Users", "x", "AppData", "Roaming")}):
            self.assertEqual(
                paths.user_data_dir(), os.path.join("C:\\", "Users", "x", "AppData", "Roaming", "StoryForge")
            )


if __name__ == "__main__":
    unittest.main()
