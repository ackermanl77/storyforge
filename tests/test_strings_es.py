"""F8: user-visible Spanish strings use accents and tú (no "pestana",
"capitulo", "podes"...). Docstrings and log messages are not UI and are skipped."""
import ast
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.strings_es import UNACCENTED_FORMS, purpose_key, purpose_label, style_key, style_label

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
UI_FILES = ["gui.py", "ui_dialogs.py", "ui_status.py", "task_runner.py", "project.py", "gguf.py", "engine.py"]
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# Stored data keys (kept unaccented on purpose, see app/strings_es.py) and metadata keys.
ALLOWED = {"Dialogo", "Poetica", "Accion rapida", "Escena climatica", "Epilogo", "gguf.version"}


def _ui_strings(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS:
            for sub in ast.walk(node):
                skip.add(id(sub))
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            skip.add(id(node.value))  # bare string statements (comments)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value


class TestSpanishStrings(unittest.TestCase):
    def test_no_unaccented_forms_in_ui_strings(self):
        pattern = re.compile("|".join(UNACCENTED_FORMS), re.IGNORECASE)
        problems = []
        for name in UI_FILES:
            for line, text in _ui_strings(os.path.join(APP_DIR, name)):
                if text in ALLOWED or text.strip().startswith(("http", "<", "#")):
                    continue
                for m in pattern.finditer(text):
                    problems.append(f"{name}:{line}: {m.group(0)!r} in {text[:70]!r}")
        self.assertEqual(problems, [])

    def test_stored_keys_map_to_accented_labels_and_back(self):
        self.assertEqual(style_label("Dialogo"), "Diálogo")
        self.assertEqual(style_key("Diálogo"), "Dialogo")
        self.assertEqual(style_key("Dialogo"), "Dialogo")
        self.assertEqual(purpose_label("Escena climatica"), "Escena climática")
        self.assertEqual(purpose_key("Epílogo"), "Epilogo")
        self.assertEqual(style_key("(Por defecto)"), "")


if __name__ == "__main__":
    unittest.main()
