"""Errors shown to the user in Spanish (app/error_text.describe_exception)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.strings_es as S
from app.engine import ContextOverflowError, ModelNotLoadedError
from app.error_text import describe_exception


def _raised(func):
    try:
        func()
    except BaseException as exc:  # noqa: BLE001
        return exc
    raise AssertionError("no exception")


class DescribeExceptionTests(unittest.TestCase):
    def test_file_errors_name_the_path_in_spanish(self):
        missing = os.path.join(os.path.dirname(__file__), "no-such-file.json")
        exc = _raised(lambda: open(missing, encoding="utf-8"))
        self.assertEqual(describe_exception(exc), S.ERR_ARCHIVO_NO_ENCONTRADO.format(path=missing))
        denied = PermissionError(13, "Permission denied", "C:/x.json")
        self.assertIn("No hay permiso para usar C:/x.json", describe_exception(denied))
        full = OSError(28, "No space left on device", "C:/x.json")
        self.assertEqual(describe_exception(full), S.ERR_DISCO_LLENO.format(path="C:/x.json"))

    def test_broken_json_and_non_utf8_text(self):
        exc = _raised(lambda: json.loads('{"a": 1,\n  oops}'))
        self.assertEqual(describe_exception(exc), S.ERR_JSON_INVALIDO.format(line=2, col=3))
        exc = _raised(lambda: b"\xff\xfe\x00W".decode("utf-8"))
        self.assertEqual(describe_exception(exc), S.ERR_CODIFICACION)
        self.assertEqual(describe_exception(MemoryError()), S.ERR_SIN_MEMORIA)

    def test_llama_cpp_errors_are_explained_with_the_original_as_detail(self):
        exc = ValueError("Failed to load model from file: C:/models/broken.gguf")
        text = describe_exception(exc)
        self.assertTrue(text.startswith(S.ERR_MODELO_NO_CARGA))
        self.assertIn("detalle técnico: Failed to load model from file", text)
        self.assertTrue(describe_exception(RuntimeError("CUDA error: out of memory")).startswith(S.ERR_SIN_VRAM))
        self.assertTrue(describe_exception(ValueError("Requested tokens (9000) exceed context window of 8192"))
                        .startswith(S.ERR_CONTEXTO_LLAMA))
        self.assertTrue(describe_exception(RuntimeError("llama_decode returned -3")).startswith(S.ERR_LLAMA_INTERNO))

    def test_own_errors_and_unknown_ones_are_shown_as_they_are(self):
        self.assertEqual(describe_exception(ModelNotLoadedError("Primero carga un modelo.")), "Primero carga un modelo.")
        self.assertEqual(describe_exception(ContextOverflowError("ya en español")), "ya en español")
        self.assertEqual(describe_exception(ValueError("algo raro")), "algo raro")
        self.assertEqual(describe_exception(KeyError()), "KeyError")


if __name__ == "__main__":
    unittest.main()
