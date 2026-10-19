"""
``--self-test``: comprueba que un build tiene todo lo que necesita, sin abrir
la ventana.

Se ejecuta como ``StoryForge.exe --self-test`` (o ``python storyforge.py
--self-test``) antes de publicar un release. Revisa:

- la interfaz: que tkinter/customtkinter importan y que Tcl/Tk crea una
  ventana (oculta, se destruye enseguida);
- llama.cpp: que llama_cpp carga sus DLL (las de CUDA en el build cuda13) y si
  puede descargar capas a la GPU;
- NLTK: stopwords y wordnet encontrados sin descargar nada, y un sinonimo real
  de WordNet;
- un proyecto de prueba: guardar/cargar el .json y exportarlo a TXT,
  Markdown, DOCX y EPUB;
- las paginas de StoryForge en el celular (app/web/).

No carga ningun modelo (son de varios GB): solo informa cuantos hay en
models\\. Codigo de salida 0 = todo bien.

El .exe no tiene consola, asi que el informe tambien se escribe en
``%TEMP%\\StoryForge-selftest.txt`` (la ruta se imprime al final).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
import zipfile
from typing import Callable, List

from . import __version__

REPORT_NAME = "StoryForge-selftest.txt"
WEB_FILES = ("index.html", "app.js", "style.css", "generador.html", "generador.js", "manifest.webmanifest")


def _check_gui(log: Callable[[str], None]) -> bool:
    import tkinter

    import customtkinter

    root = tkinter.Tk()
    try:
        root.withdraw()
        tk_version = root.tk.call("info", "patchlevel")
    finally:
        root.destroy()
    log(f"ok    interfaz: Tcl/Tk {tk_version}, customtkinter {customtkinter.__version__}")
    return True


def _check_llama(log: Callable[[str], None]) -> bool:
    from .engine import _ensure_cuda_dlls_discoverable

    _ensure_cuda_dlls_discoverable()
    try:
        import llama_cpp
        from llama_cpp import llama_cpp as lib
    except Exception as exc:  # noqa: BLE001 -- RuntimeError si falta una DLL
        log(f"FAIL  llama_cpp no carga: {exc}")
        return False
    gpu = bool(lib.llama_supports_gpu_offload())
    log(f"ok    llama_cpp {getattr(llama_cpp, '__version__', '?')} cargado")
    log(f"info  descarga de capas a la GPU: {'si' if gpu else 'no (build solo CPU)'}")
    return True


def _check_nltk(log: Callable[[str], None]) -> bool:
    from .repetition import _best_synonym, nltk_data_found

    if not nltk_data_found():
        log("FAIL  NLTK: stopwords/wordnet no estan incluidos (se descargarian al usarlos)")
        return False
    from nltk.corpus import stopwords

    words = stopwords.words("english")
    synonym = _best_synonym("happy", set())
    if len(words) < 100 or not synonym:
        log(f"FAIL  NLTK: {len(words)} stopwords, sinonimo de 'happy': {synonym!r}")
        return False
    log(f"ok    NLTK: {len(words)} stopwords, WordNet ('happy' -> '{synonym}')")
    return True


def _check_project_and_exports(workdir: str, log: Callable[[str], None]) -> bool:
    from .export import export_docx, export_epub, export_markdown, export_txt
    from .project import Chapter, Project

    project = Project(name="Prueba Árbol", plot="Una prueba.")
    project.chapters.append(Chapter(title="Uno", content="Primera *línea* del capítulo.\n\nSegundo párrafo."))
    path = os.path.join(workdir, "prueba.json")
    project.save(path)
    loaded = Project.load(path)
    if loaded.name != project.name or loaded.chapters[0].content != project.chapters[0].content:
        log("FAIL  el proyecto guardado no se carga igual")
        return False
    log("ok    proyecto: guardar y cargar")

    ok = True
    for ext, exporter in (("txt", export_txt), ("md", export_markdown), ("docx", export_docx), ("epub", export_epub)):
        out = os.path.join(workdir, f"prueba.{ext}")
        exporter(loaded, out)
        size = os.path.getsize(out) if os.path.exists(out) else 0
        problem = "" if size else "archivo vacio"
        if size and ext in ("docx", "epub"):
            with zipfile.ZipFile(out) as archive:
                needed = "word/document.xml" if ext == "docx" else "mimetype"
                if needed not in archive.namelist():
                    problem = f"falta {needed}"
        if problem:
            ok = False
            log(f"FAIL  exportar {ext.upper()}: {problem}")
    if ok:
        log("ok    exportar: TXT, Markdown, DOCX, EPUB")
    return ok


def _check_web(log: Callable[[str], None]) -> bool:
    from .web_server import WEB_DIR

    missing = [name for name in WEB_FILES if not (WEB_DIR / name).is_file()]
    if missing:
        log(f"FAIL  faltan paginas web en {WEB_DIR}: {', '.join(missing)}")
        return False
    log(f"ok    paginas web (app/web): {len(WEB_FILES)} archivos")
    return True


def _report_models(log: Callable[[str], None]) -> None:
    from .engine import find_local_models
    from .paths import app_root

    models_dir = os.path.join(app_root(), "models")
    models = find_local_models(models_dir) if os.path.isdir(models_dir) else []
    log(f"info  modelos en {models_dir}: {len(models)}")


def run_self_test(out: Callable[[str], None] = print) -> int:
    lines: List[str] = []

    def log(line: str) -> None:
        lines.append(line)
        try:
            out(line)
        except Exception:  # noqa: BLE001 -- el .exe sin consola puede no tener stdout
            pass

    ok = True
    log(f"StoryForge {__version__} self-test")
    log(f"Python {sys.version.split()[0]} ({'empaquetado' if getattr(sys, 'frozen', False) else 'codigo fuente'})")
    workdir = tempfile.mkdtemp(prefix="storyforge_selftest_")
    checks = (
        lambda: _check_gui(log),
        lambda: _check_llama(log),
        lambda: _check_nltk(log),
        lambda: _check_project_and_exports(workdir, log),
        lambda: _check_web(log),
    )
    try:
        for check in checks:
            try:
                ok = check() and ok
            except Exception as exc:  # noqa: BLE001 -- informar, no caerse
                ok = False
                log(f"FAIL  {exc}")
                log(traceback.format_exc().strip())
        try:
            _report_models(log)
        except Exception as exc:  # noqa: BLE001
            log(f"info  modelos: no se pudieron listar ({exc})")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    log("RESULT: PASS" if ok else "RESULT: FAIL")
    report = os.path.join(tempfile.gettempdir(), REPORT_NAME)
    try:
        with open(report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            out(f"(informe escrito en {report})")
        except Exception:  # noqa: BLE001
            pass
    except OSError:
        pass
    return 0 if ok else 1
