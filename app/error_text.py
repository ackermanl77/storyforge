"""Errores explicados en español para el usuario.

Las excepciones propias de StoryForge ya traen su texto de app/strings_es.py,
pero las de Python, del sistema y de llama-cpp-python llegan en inglés
("[Errno 2] No such file or directory", "Expecting value: line 1 column 1",
"Failed to load model from file", "CUDA error: out of memory"). Las ventanas de
error, el servidor web y el autoguardado muestran describe_exception(exc) en vez
de str(exc): una explicación en español de los casos comunes y, en los que
vienen de llama.cpp, el texto original como detalle técnico. Lo que no se
reconoce se muestra como antes. Los registros siguen guardando el texto original.
"""

from __future__ import annotations

import errno
import json

from . import strings_es as S

_FILE_ERRORS = (
    (FileNotFoundError, S.ERR_ARCHIVO_NO_ENCONTRADO),
    (PermissionError, S.ERR_SIN_PERMISO),
    (IsADirectoryError, S.ERR_ES_CARPETA),
    (NotADirectoryError, S.ERR_NO_ES_CARPETA),
)
# (fragmentos en minúsculas del mensaje de llama.cpp / CUDA, explicación)
_LLAMA_ERRORS = (
    (("out of memory", "cudamalloc", "failed to allocate", "cuda error 2"), S.ERR_SIN_VRAM),
    (("failed to load model", "unknown model architecture", "invalid magic", "failed to read"), S.ERR_MODELO_NO_CARGA),
    (("exceed context window", "context window", "n_ctx"), S.ERR_CONTEXTO_LLAMA),
    (("llama_decode returned", "llama_eval", "ggml_assert"), S.ERR_LLAMA_INTERNO),
)


def _path(exc: OSError, text: str) -> str:
    return str(exc.filename) if getattr(exc, "filename", None) else text


def describe_exception(exc: BaseException) -> str:
    """Un mensaje en español para mostrarle `exc` al usuario (ver el docstring del módulo)."""
    text = str(exc).strip()
    if type(exc).__module__.split(".")[0] == "app":
        return text or type(exc).__name__  # ya viene de strings_es
    for kind, template in _FILE_ERRORS:
        if isinstance(exc, kind):
            return template.format(path=_path(exc, text))
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return S.ERR_DISCO_LLENO.format(path=_path(exc, ""))
    if isinstance(exc, OSError) and exc.errno == errno.ENAMETOOLONG:
        return S.ERR_RUTA_DEMASIADO_LARGA.format(path=_path(exc, text))
    if isinstance(exc, json.JSONDecodeError):
        return S.ERR_JSON_INVALIDO.format(line=exc.lineno, col=exc.colno)
    if isinstance(exc, UnicodeDecodeError):
        return S.ERR_CODIFICACION
    if isinstance(exc, MemoryError):
        return S.ERR_SIN_MEMORIA
    if isinstance(exc, TimeoutError):
        return S.ERR_TIEMPO_AGOTADO
    if isinstance(exc, ConnectionError):
        return S.ERR_DETALLE.format(message=S.ERR_CONEXION, detail=text or type(exc).__name__)
    low = text.lower()
    for fragments, template in _LLAMA_ERRORS:
        if any(fragment in low for fragment in fragments):
            return S.ERR_DETALLE.format(message=template, detail=text)
    return text or type(exc).__name__
