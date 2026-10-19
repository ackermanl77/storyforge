"""--self-test (app/selftest.py): la ruta desde main(), los chequeos que no
dependen del build, el informe y el codigo de salida."""
import os
import tempfile
import unittest
from unittest.mock import patch

from app import main as app_main
from app import selftest


class TestSelfTest(unittest.TestCase):
    def test_main_runs_the_self_test_without_the_gui(self):
        with patch("app.selftest.run_self_test", return_value=0) as run, patch("app.gui.run") as gui:
            self.assertEqual(app_main.main(["--self-test"]), 0)
        run.assert_called_once()
        gui.assert_not_called()

    def test_project_exports_and_web_pages(self):
        lines = []
        with tempfile.TemporaryDirectory() as workdir:
            self.assertTrue(selftest._check_project_and_exports(workdir, lines.append))
        self.assertTrue(selftest._check_web(lines.append))
        self.assertIn("ok    exportar: TXT, Markdown, DOCX, EPUB", lines)

    def test_a_failing_check_fails_the_run_and_writes_the_report(self):
        lines = []
        with tempfile.TemporaryDirectory() as temp, patch("tempfile.gettempdir", return_value=temp), \
                patch.object(selftest, "_check_gui", return_value=True), \
                patch.object(selftest, "_check_llama", side_effect=RuntimeError("sin llama.dll")), \
                patch.object(selftest, "_check_nltk", return_value=True):
            self.assertEqual(selftest.run_self_test(lines.append), 1)
            with open(os.path.join(temp, selftest.REPORT_NAME), encoding="utf-8") as f:
                report = f.read()
        self.assertIn("FAIL  sin llama.dll", report)
        self.assertIn("RESULT: FAIL", lines)


if __name__ == "__main__":
    unittest.main()
