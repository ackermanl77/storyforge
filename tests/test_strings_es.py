"""F8: user-visible Spanish strings use accents and tú (no "pestana",
"capitulo", "podes"...), and they all live in app/strings_es.py: the UI
modules (app/gui.py, app/ui_*.py, app/task_runner.py) only reference them.
Docstrings, log messages and type annotations are not UI and are skipped."""
import ast
import glob
import os
import re
import string
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.strings_es as strings_es
from app.strings_es import UNACCENTED_FORMS, purpose_key, purpose_label, style_key, style_label

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
# Modules whose user-facing text must come from app/strings_es.py.
UI_MODULES = sorted(
    ["gui.py", "task_runner.py"] + [os.path.basename(p) for p in glob.glob(os.path.join(APP_DIR, "ui_*.py"))]
)
# Backend modules whose user-facing messages (raised errors, load warnings, the
# lorebook match reason) also come from app/strings_es.py.
BACKEND_MODULES = ["engine.py", "export.py", "gguf.py", "project.py", "prompts.py"]
# Checked for accents/tú (backend messages that can reach the user too).
UI_FILES = UI_MODULES + ["strings_es.py", "project.py", "gguf.py", "engine.py"]
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# Stored data keys (kept unaccented on purpose, see app/strings_es.py) and metadata keys.
ALLOWED = {"Dialogo", "Poetica", "Accion rapida", "Escena climatica", "Epilogo", "gguf.version"}
# Literals that may stay in the UI modules: Tk names and values, the stored
# heading key, file-dialog patterns and the history "source" keys
# ("refine: ...", parsed by strings_es.history_source_label()).
TECHNICAL_LITERALS = {
    "WM_DELETE_WINDOW", "Text", "Return", "Dark", "Consolas", "Chapter",
    "*.storyforge.json *.json", "refine: ", "rewrite: ",
}


def _skipped_nodes(tree):
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
        annotations = []
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotations.append(node.annotation)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            annotations.append(node.returns)
        if isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            annotations.append(node.value)
        for annotation in annotations:
            for sub in ast.walk(annotation):
                skip.add(id(sub))
    return skip


def _parse(name):
    with open(os.path.join(APP_DIR, name), encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _ui_strings(name):
    tree = _parse(name)
    skip = _skipped_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value


def _looks_like_user_text(text):
    """Heuristic: letters plus a space, a non-ASCII character (accents,
    ¿, ✓...) or a leading capital. Widget options ("disabled", "nsew"),
    colours, Tk events and settings keys don't match."""
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]", text):
        return False
    return bool(re.search(r"\s", text) or re.search(r"[^\x00-\x7f]", text) or text[:1].isupper())


def _inline_literals(name):
    """User-looking literals (plain strings, and the literal parts of each
    f-string joined) left in a UI module."""
    tree = _parse(name)
    skip = _skipped_nodes(tree)
    inside_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for sub in ast.walk(node):
                if sub is not node:
                    inside_fstring.add(id(sub))
    for node in ast.walk(tree):
        if id(node) in skip or id(node) in inside_fstring:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
        else:
            continue
        if text not in TECHNICAL_LITERALS and _looks_like_user_text(text):
            yield node.lineno, text


def _strings_es_references(name):
    """(line, attribute, call) for every S.<NAME> in a UI module; `call` is the
    ast.Call when the text is used as S.<NAME>.format(...)."""
    tree = _parse(name)
    format_calls = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
                and isinstance(node.func.value, ast.Attribute)):
            format_calls[id(node.func.value)] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "S":
            yield node.lineno, node.attr, format_calls.get(id(node))


class TestSpanishStrings(unittest.TestCase):
    def test_no_unaccented_forms_in_ui_strings(self):
        pattern = re.compile("|".join(UNACCENTED_FORMS), re.IGNORECASE)
        problems = []
        for name in UI_FILES:
            for line, text in _ui_strings(name):
                if text in ALLOWED or text.strip().startswith(("http", "<", "#", "\\b")):
                    continue
                for m in pattern.finditer(text):
                    problems.append(f"{name}:{line}: {m.group(0)!r} in {text[:70]!r}")
        self.assertEqual(problems, [])

    def test_ui_modules_have_no_inline_user_text(self):
        self.assertIn("ui_chapter_editor.py", UI_MODULES)
        problems = [
            f"{name}:{line}: {text[:70]!r}"
            for name in UI_MODULES for line, text in _inline_literals(name)
        ]
        self.assertEqual(problems, [], "move these texts to app/strings_es.py")

    def test_backend_messages_come_from_strings_es(self):
        """The first argument of every `raise X(...)` and load-warning append in the
        backend is an S.* text, not a literal (a technical value like a stray
        f-string with only an expression would still be caught here)."""
        problems = []
        for name in BACKEND_MODULES:
            with open(os.path.join(APP_DIR, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                message = None
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                    message = node.exc.args[0]
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                      and "warning" in ast.unparse(node.func.value).lower() and node.args):
                    message = node.args[0]
                if isinstance(message, (ast.Constant, ast.JoinedStr)) and not (
                        isinstance(message, ast.Constant) and not isinstance(message.value, str)):
                    problems.append(f"{name}:{message.lineno}: {ast.unparse(message)[:70]}")
        self.assertEqual(problems, [], "move these messages to app/strings_es.py")

    def test_every_referenced_text_exists_and_is_formatted_with_its_fields(self):
        problems = []
        formatter = string.Formatter()
        for name in UI_MODULES + BACKEND_MODULES:
            for line, attr, call in _strings_es_references(name):
                value = getattr(strings_es, attr, None)
                if value is None:
                    problems.append(f"{name}:{line}: S.{attr} does not exist")
                    continue
                if call is None:
                    continue
                fields = {f.split(".")[0].split("[")[0] for _, f, _, _ in formatter.parse(value) if f}
                given = {kw.arg for kw in call.keywords}
                if call.args or fields != given:
                    problems.append(f"{name}:{line}: S.{attr} needs {sorted(fields)}, got {sorted(given)}")
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
