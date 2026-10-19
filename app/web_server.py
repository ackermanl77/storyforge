"""
StoryForge en el celular: un servidor web en la red local (`storyforge.py
--servidor`) para escribir desde el navegador del celular mientras el modelo
corre en la PC.

Usa el mismo motor (app/engine.py), el mismo formato de proyecto
(app/project.py) y los mismos pasos que la interfaz de escritorio
(ui_chapter_editor._start_generation: resumenes previos desactualizados ->
capitulo -> resumen para continuidad; ui_outline_tab._apply_outline), sin Tk:
la pagina (app/web/) llama a una API JSON y consulta /api/tarea cada segundo
para ver el texto que se va generando.

- Un solo proyecto abierto y una sola tarea a la vez (el modelo es uno). Mientras
  corre una tarea el proyecto no se puede modificar (409).
- Los proyectos viven en una carpeta propia del servidor (por defecto
  user_data_dir()/proyectos; --carpeta la cambia y se recuerda). Cada cambio se
  guarda en el momento (guardado atomico con .bak, Project.save()).
- Acceso: el servidor escucha en toda la red local, asi que la API exige una
  clave (`web_token` en settings.json, generada la primera vez) que viaja en el
  enlace/QR (`/?t=<clave>`) y despues en la cabecera X-StoryForge-Token. La
  pagina de conexion (/conectar, con el QR) y /api/apagar solo responden a la
  propia PC (127.0.0.1).
"""
from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import generator, story_settings
from . import strings_es as S
from .error_text import describe_exception
from .engine import ContextOverflowError, ModelNotLoadedError, OperationCancelled, supports_gpu_offload
from .export import build_epub_bytes, build_markdown, build_txt, export_docx
from .gguf import list_model_entries
from .paths import app_root, is_frozen, user_data_dir
from .project import (
    CHAPTER_PURPOSES,
    MAX_CHAPTERS,
    MAX_WORDS_PER_CHAPTER,
    WRITING_STYLES,
    Project,
    count_words,
    portable_model_path,
)
from .prompts import CUSTOM_PROMPT_TEMPLATE
from .settings import (
    get_chat_format_for_model,
    get_last_model,
    get_model_settings,
    get_ui_preferences,
    load_settings,
    save_settings,
    set_model_settings,
)
from .task_runner import call_supported

logger = logging.getLogger("storyforge.web")

DEFAULT_PORT = 8765
WEB_DIR = Path(__file__).resolve().parent / "web"
PROJECT_SUFFIX = ".storyforge.json"
TOKEN_HEADER = "X-StoryForge-Token"
MAX_BODY_BYTES = 2 * 1024 * 1024  # un capitulo maximo (~10k palabras) cabe de sobra
# Importar manuscrito (F16): el archivo viaja en base64 dentro del JSON.
MAX_IMPORT_BODY_BYTES = 42 * 1024 * 1024
IMPORT_PATH = "/api/proyectos/importar"
DEFAULT_LOAD_OPTIONS = {"n_ctx": 8192, "n_threads": None, "flash_attn": None, "n_batch": None,
                        "n_ubatch": None, "kv_cache_type": "f16"}
EXPORT_FORMATS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "epub": "application/epub+zip",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


# Ajustes de la historia en la API (nombre en la API -> atributo de Project).
_STORY_FIELDS = {"genero": "genre", "tema": "theme", "tono": "tone", "punto_de_vista": "point_of_view",
                 "dialogo": "dialogue_balance"}


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def models_dirs() -> List[str]:
    """Donde se buscan modelos: models\\ junto a la app, la carpeta de --modelos
    (se recuerda), la carpeta extra de Preferencias, la del ultimo modelo
    cargado y, sin empaquetar, la del build (StoryForge-App\\models): asi el
    servidor encuentra los modelos aunque se arranque desde el codigo fuente."""
    candidates = [os.path.join(app_root(), "models"), load_settings().get("web_models_dir"),
                  get_ui_preferences().get("models_dir")]
    last = get_last_model()
    if last:
        candidates.append(os.path.dirname(last))
    if not is_frozen():
        candidates.append(os.path.join(app_root(), "StoryForge-App", "models"))
    dirs: List[str] = []
    for i, folder in enumerate(candidates):
        if not isinstance(folder, str) or not folder.strip():
            continue
        folder = os.path.abspath(folder.strip())
        if i > 0 and not os.path.isdir(folder):
            continue
        if os.path.normcase(folder) not in {os.path.normcase(d) for d in dirs}:
            dirs.append(folder)
    return dirs


def remember_models_dir(path: str) -> None:
    data = load_settings()
    data["web_models_dir"] = os.path.abspath(path)
    save_settings(data)


def default_projects_dir() -> str:
    saved = load_settings().get("web_projects_dir")
    if isinstance(saved, str) and saved.strip():
        return saved
    return os.path.join(user_data_dir(), "proyectos")


def remember_projects_dir(path: str) -> None:
    data = load_settings()
    data["web_projects_dir"] = os.path.abspath(path)
    save_settings(data)


def access_token() -> str:
    """La clave de acceso del servidor: se genera una vez y se guarda, asi el
    enlace guardado en el celular sigue sirviendo despues de reiniciar."""
    data = load_settings()
    token = data.get("web_token")
    if not isinstance(token, str) or len(token) < 16:
        token = secrets.token_urlsafe(18)
        data["web_token"] = token
        save_settings(data)
    return token


def lan_ip() -> str:
    """La IP de esta PC en la red local (la de la interfaz con ruta por
    defecto; un connect() UDP no envia nada)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _slug(name: str) -> str:
    slug = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip().replace(" ", "_")
    return slug[:60] or "proyecto"


@dataclass
class Job:
    id: int
    kind: str  # "load", "outline", "chapter", "summary"
    label: str
    chapter: Optional[int] = None
    status: str = "running"  # running | ok | error | cancelled
    message: str = ""
    text: str = ""  # texto parcial del capitulo (streaming)
    words: int = 0
    target: int = 0
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    cancel: threading.Event = field(default_factory=threading.Event)


class StoryForgeService:
    """La logica del servidor, sin HTTP (las pruebas la usan directamente)."""

    def __init__(self, engine, projects_dir: str) -> None:
        self.engine = engine
        self.projects_dir = os.path.abspath(projects_dir)
        os.makedirs(self.projects_dir, exist_ok=True)
        self.project: Optional[Project] = None
        self.project_file: Optional[str] = None
        self.job: Optional[Job] = None
        self._job_ids = 0
        self._lock = threading.RLock()

    # ---------------- utilidades ----------------
    def _require_project(self) -> Project:
        if self.project is None:
            raise ApiError(HTTPStatus.CONFLICT, S.WEB_SIN_PROYECTO)
        return self.project

    def _require_idle(self) -> None:
        job = self.job
        if job is not None and job.status == "running":
            raise ApiError(HTTPStatus.CONFLICT, S.WEB_HAY_UNA_TAREA.format(label=job.label))

    def _chapter(self, index: int):
        project = self._require_project()
        if not 0 <= index < len(project.chapters):
            raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_CAPITULO_NO_EXISTE.format(number=index + 1))
        return project.chapters[index]

    def _save(self) -> None:
        if self.project is not None and self.project_file:
            self.project.save(os.path.join(self.projects_dir, self.project_file))

    def _project_path(self, name: str) -> str:
        base = os.path.basename(name or "")
        if not base.endswith(PROJECT_SUFFIX):
            raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_SOLICITUD_INVALIDA)
        path = os.path.join(self.projects_dir, base)
        if not os.path.isfile(path):
            raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_PROYECTO_NO_ENCONTRADO.format(name=base))
        return path

    # ---------------- estado ----------------
    def status(self) -> Dict[str, Any]:
        engine = self.engine
        model = None
        if engine.is_loaded:
            model = {"nombre": os.path.basename(engine.model_path or ""), "n_ctx": engine.n_ctx}
        project = None
        if self.project is not None:
            project = {"nombre": self.project.name, "archivo": self.project_file,
                       "capitulos": len(self.project.chapters), "palabras": self.project.total_words()}
        task = self.job_snapshot()
        if task is not None:
            task["texto"] = ""  # el texto parcial va solo por /api/tarea?desde=N
            task["desde"] = task["largo"]
        return {"modelo": model, "proyecto": project, "tarea": task, "carpeta_proyectos": self.projects_dir,
                "carpetas_modelos": models_dirs()}

    # ---------------- modelos ----------------
    def list_models(self) -> List[Dict[str, str]]:
        models = []
        for folder in models_dirs():
            for entry in list_model_entries(folder):
                if entry.complete:
                    models.append({"id": entry.path, "nombre": entry.label})
        return models

    def load_model(self, model_id: str) -> Dict[str, Any]:
        self._require_idle()
        known = {m["id"] for m in self.list_models()}
        if model_id not in known:
            raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_MODELO_NO_DISPONIBLE)
        options = dict(DEFAULT_LOAD_OPTIONS, n_gpu_layers=-1 if supports_gpu_offload() else 0)
        options.update(get_model_settings(model_id))
        if self.project is not None and self.project.context_size:
            options["n_ctx"] = self.project.context_size
        chat_format = get_chat_format_for_model(model_id)
        engine = self.engine
        name = os.path.basename(model_id)

        def work(_job: Job) -> str:
            call_supported(engine.load, model_id, chat_format=chat_format, **options)
            set_model_settings(model_id, {k: v for k, v in options.items() if v is not None})
            with self._lock:
                if self.project is not None:
                    self.project.model_path = portable_model_path(model_id, models_dirs()[0])
                    self.project.context_size = engine.n_ctx or None
                    self._save()
            return S.WEB_MODELO_CARGADO.format(name=name, n_ctx=engine.n_ctx)

        return self._start("load", S.WEB_TAREA_CARGAR_MODELO.format(name=name), work)

    def unload_model(self) -> None:
        self._require_idle()
        self.engine.unload()

    # ---------------- proyectos ----------------
    def list_projects(self) -> List[Dict[str, Any]]:
        items = []
        for path in sorted(Path(self.projects_dir).glob(f"*{PROJECT_SUFFIX}"),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                project = Project.load(path)
            except (OSError, ValueError) as exc:
                logger.warning("No se pudo leer %s: %s", path, exc)
                continue
            items.append({"archivo": path.name, "nombre": project.name, "capitulos": len(project.chapters),
                          "palabras": project.total_words(), "modificado": path.stat().st_mtime})
        return items

    def create_project(self, name: str) -> Dict[str, Any]:
        self._require_idle()
        name = (name or "").strip()
        if not name:
            raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_NOMBRE_VACIO)
        stem = _slug(name)
        filename = f"{stem}{PROJECT_SUFFIX}"
        n = 2
        while os.path.exists(os.path.join(self.projects_dir, filename)):
            filename = f"{stem}_{n}{PROJECT_SUFFIX}"
            n += 1
        with self._lock:
            self.project = Project(name=name)
            self.project_file = filename
            self.engine.sampling = self.project.sampling
            self._save()
        return self.project_view()

    def import_manuscript(self, filename: str, data_b64: str) -> Dict[str, Any]:
        """Importar manuscrito (F16): crea un proyecto nuevo con los capitulos del archivo y lo abre."""
        import base64
        import binascii

        from .manuscript import read_manuscript
        from .project import MAX_CHAPTERS

        self._require_idle()
        try:
            content = base64.b64decode(data_b64 or "", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, S.MANUSCRITO_VACIO) from exc
        try:
            manuscript = read_manuscript(content, os.path.basename(filename or "manuscrito.txt"))
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        project = manuscript.to_project()
        stem = _slug(project.name)
        name = f"{stem}{PROJECT_SUFFIX}"
        n = 2
        while os.path.exists(os.path.join(self.projects_dir, name)):
            name = f"{stem}_{n}{PROJECT_SUFFIX}"
            n += 1
        with self._lock:
            self.project = project
            self.project_file = name
            self.engine.sampling = project.sampling
            self._save()
        view = self.project_view()
        view["mensaje"] = S.MANUSCRITO_IMPORTADO.format(name=project.name, chapters=len(project.chapters), words=project.total_words())
        if manuscript.merged:
            view["mensaje"] += " " + S.MANUSCRITO_SECCIONES_UNIDAS.format(maximum=MAX_CHAPTERS, merged=manuscript.merged)
        return view

    def open_project(self, filename: str) -> Dict[str, Any]:
        self._require_idle()
        path = self._project_path(filename)
        try:
            project = Project.load(path)
        except (OSError, ValueError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST,
                           S.WEB_PROYECTO_NO_SE_PUDO_ABRIR.format(name=os.path.basename(path), exc=describe_exception(exc))) from exc
        with self._lock:
            self.project = project
            self.project_file = os.path.basename(path)
            self.engine.sampling = project.sampling
        return self.project_view()

    def project_view(self) -> Dict[str, Any]:
        project = self._require_project()
        return {
            "archivo": self.project_file,
            "nombre": project.name,
            "autor": project.author,
            "plot": project.plot,
            "personajes": project.characters,
            "setting": project.setting,
            "estilo": project.writing_style,
            "genero": project.genre,
            "tema": project.theme,
            "tono": project.tone,
            "punto_de_vista": project.point_of_view,
            "dialogo": project.dialogue_balance,
            "sugerencias": {key: list(story_settings.SUGGESTIONS[field]) for key, field in _STORY_FIELDS.items()
                            if field in story_settings.SUGGESTIONS},
            "dialogos": [{"valor": k, "etiqueta": v} for k, v in S.DIALOGUE_LABELS.items()],
            "presets": story_settings.all_presets(),
            "nota_autor": project.author_note,
            "palabras": project.total_words(),
            "estilos": [{"valor": "", "etiqueta": S.style_label("")}]
                       + [{"valor": k, "etiqueta": S.style_label(k)} for k in WRITING_STYLES],
            "propositos": [{"valor": "", "etiqueta": S.purpose_label("")}]
                          + [{"valor": k, "etiqueta": S.purpose_label(k)} for k in CHAPTER_PURPOSES],
            "plantilla_prompt": CUSTOM_PROMPT_TEMPLATE,
            "max_capitulos": MAX_CHAPTERS,
            "max_palabras_capitulo": MAX_WORDS_PER_CHAPTER,
            "capitulos": [
                {"indice": i, "titulo": ch.title, "objetivo": ch.target_words, "palabras": ch.word_count(),
                 "esquema": ch.outline, "proposito": ch.purpose, "tiene_resumen": bool(ch.summary.strip()),
                 "prompt_propio": bool(ch.custom_prompt.strip()),
                 "resumen_desactualizado": ch.summary_is_stale()}
                for i, ch in enumerate(project.chapters)
            ],
        }

    def update_project(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self._require_idle()
        project = self._require_project()
        fields = {"nombre": "name", "autor": "author", "plot": "plot", "personajes": "characters",
                  "setting": "setting", "estilo": "writing_style", "nota_autor": "author_note", **_STORY_FIELDS}
        with self._lock:
            for key, attr in fields.items():
                if key not in data:
                    continue
                value = data[key]
                if not isinstance(value, str):
                    raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name=key))
                if key == "estilo" and value and value not in WRITING_STYLES:
                    raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name=key))
                if key == "dialogo" and value and value not in story_settings.DIALOGUE_BALANCES:
                    raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name=key))
                if key in _STORY_FIELDS:
                    value = value.strip()[: story_settings.MAX_SETTING_CHARS]
                if key == "nombre":
                    value = value.strip() or project.name
                setattr(project, attr, value)
            self._save()
        return self.project_view()

    # ---------------- capitulos ----------------
    def chapter_view(self, index: int) -> Dict[str, Any]:
        ch = self._chapter(index)
        return {"indice": index, "titulo": ch.title, "objetivo": ch.target_words, "texto": ch.content,
                "palabras": ch.word_count(), "esquema": ch.outline, "proposito": ch.purpose,
                "nota_autor": ch.author_note, "prompt": ch.custom_prompt, "resumen": ch.summary,
                "resumen_desactualizado": ch.summary_is_stale(), "versiones": len(ch.history)}

    def update_chapter(self, index: int, data: Dict[str, Any]) -> Dict[str, Any]:
        self._require_idle()
        ch = self._chapter(index)
        project = self._require_project()
        with self._lock:
            for key, attr in (("titulo", "title"), ("esquema", "outline"), ("nota_autor", "author_note"),
                              ("prompt", "custom_prompt")):
                if key in data:
                    if not isinstance(data[key], str):
                        raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name=key))
                    setattr(ch, attr, data[key])
            if "proposito" in data:
                if data["proposito"] not in ("", *CHAPTER_PURPOSES):
                    raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name="proposito"))
                ch.purpose = data["proposito"]
            if "objetivo" in data:
                target = data["objetivo"]
                if not isinstance(target, int) or isinstance(target, bool) or not 1 <= target <= MAX_WORDS_PER_CHAPTER:
                    raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name="objetivo"))
                ch.target_words = target
            if "texto" in data:
                text = data["texto"]
                if not isinstance(text, str):
                    raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name="texto"))
                if text != ch.content:
                    # Igual que una edicion a mano en el escritorio: la version
                    # anterior queda en "Versiones" y las alternativas se descartan.
                    project.push_chapter_history(ch, "phone-edit")
                    ch.content = text
                    ch.alternatives = []
                    ch.alt_index = -1
            self._save()
        return self.chapter_view(index)

    def add_chapter(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self._require_idle()
        project = self._require_project()
        if not project.can_add_chapter():
            raise ApiError(HTTPStatus.CONFLICT, S.MAXIMO_DE_CAPITULOS.format(maximum=MAX_CHAPTERS))
        with self._lock:
            project.add_chapter(title=str(data.get("titulo") or ""))
            self._save()
        index = len(project.chapters) - 1
        if "objetivo" in data:
            self.update_chapter(index, {"objetivo": data["objetivo"]})
        return self.chapter_view(index)

    def delete_chapter(self, index: int) -> None:
        self._require_idle()
        self._chapter(index)
        with self._lock:
            del self.project.chapters[index]
            self._save()

    # ---------------- tareas con el modelo ----------------
    def _start(self, kind: str, label: str, work: Callable[[Job], str], chapter: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            self._require_idle()
            self._job_ids += 1
            job = Job(id=self._job_ids, kind=kind, label=label, chapter=chapter)
            self.job = job
        clear = getattr(self.engine, "clear_stop", None)
        if callable(clear):
            clear()

        def run() -> None:
            try:
                job.message = work(job) or S.LISTO
                job.status = "cancelled" if job.cancel.is_set() else "ok"
            except OperationCancelled:
                job.status = "cancelled"
                job.message = S.WEB_TAREA_DETENIDA
            except ModelNotLoadedError as exc:
                job.status, job.message = "error", str(exc)
            except ContextOverflowError as exc:
                job.status, job.message = "error", S.EL_CONTEXTO_ES_DEMASIADO_GRANDE.format(exc=exc)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error en la tarea '%s'", label)
                job.status, job.message = "error", S.ERROR_GENERICO.format(exc=describe_exception(exc))
            finally:
                job.finished = time.time()

        threading.Thread(target=run, name=f"storyforge-web-{kind}", daemon=True).start()
        return self.job_snapshot()

    def stop(self) -> None:
        job = self.job
        if job is None or job.status != "running":
            return
        job.cancel.set()
        stop = getattr(self.engine, "request_stop", None)
        if callable(stop):
            stop()

    def job_snapshot(self, since: int = 0) -> Optional[Dict[str, Any]]:
        """La tarea actual (o la ultima). `since`: cuantos caracteres del texto
        parcial ya tiene la pagina; se devuelve solo lo nuevo (o todo, con
        `reiniciar`, si el texto cambio desde el principio)."""
        job = self.job
        if job is None:
            return None
        text = job.text
        restart = since > len(text) or since < 0
        start = 0 if restart else since
        snapshot = {
            "id": job.id, "tipo": job.kind, "etiqueta": job.label, "capitulo": job.chapter,
            "estado": job.status, "mensaje": job.message, "palabras": job.words, "objetivo": job.target,
            "texto": text[start:], "desde": start, "largo": len(text), "reiniciar": restart,
            "segundos": round((job.finished or time.time()) - job.started, 1),
        }
        stats = getattr(self.engine, "stats", None)
        if job.status == "running" and stats is not None:
            tps = getattr(stats, "tokens_per_second", None)
            eta = stats.eta_seconds() if callable(getattr(stats, "eta_seconds", None)) else None
            snapshot["tokens_por_segundo"] = round(tps, 1) if tps else None
            snapshot["eta_segundos"] = round(eta) if eta else None
            snapshot["operacion"] = getattr(stats, "operation", "")
        return snapshot

    def _check_ready(self) -> Project:
        project = self._require_project()
        if not self.engine.is_loaded:
            raise ApiError(HTTPStatus.CONFLICT, S.NO_HAY_MODELO_CARGADO)
        errors = project.validate_inputs()
        if errors:
            raise ApiError(HTTPStatus.BAD_REQUEST, "\n".join(errors))
        return project

    def start_outline(self, num_chapters: Any) -> Dict[str, Any]:
        self._require_idle()
        project = self._check_ready()
        if not isinstance(num_chapters, int) or isinstance(num_chapters, bool):
            raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_CAMPO_INVALIDO.format(name="capitulos"))
        wanted = max(1, min(num_chapters, MAX_CHAPTERS))
        engine = self.engine

        def work(job: Job) -> str:
            items = call_supported(engine.generate_outline, project, wanted, cancel_check=job.cancel.is_set)
            with self._lock:
                # Como ui_outline_tab._apply_outline: los capitulos existentes
                # conservan su prosa; cambian titulo y esquema.
                for i, (title, outline) in enumerate(items):
                    if i < len(project.chapters):
                        project.chapters[i].title = title or project.chapters[i].title
                        project.chapters[i].outline = outline
                    elif project.can_add_chapter():
                        project.add_chapter(title=title, outline=outline)
                self._save()
            return S.WEB_ESQUEMA_LISTO.format(have=len(items), wanted=wanted)

        return self._start("outline", S.WEB_TAREA_ESQUEMA, work)

    def start_chapter(self, index: int, resume: bool = False) -> Dict[str, Any]:
        """Generar (desde cero) o Continuar un capitulo, con los mismos pasos que
        ui_chapter_editor._start_generation; los resumenes desactualizados de los
        capitulos anteriores (su contexto) se regeneran antes sin preguntar."""
        self._require_idle()
        project = self._check_ready()
        chapter = self._chapter(index)
        engine = self.engine
        base_text = chapter.content.rstrip() if resume else ""
        resume_from = base_text if resume and base_text else None

        def work(job: Job) -> str:
            cancelled = job.cancel.is_set
            with self._lock:
                project.push_chapter_history(chapter, "continue" if resume_from else "generate")
            job.text = base_text
            job.target = chapter.target_words
            job.words = count_words(base_text)
            for i in [i for i in range(index) if project.chapters[i].needs_summary()]:
                if cancelled():
                    break
                job.message = S.REGENERANDO_EL_RESUMEN_DEL_CAPITULO.format(number=i + 1)
                previous = project.chapters[i]
                source_text = previous.content
                try:
                    summary = call_supported(engine.summarize, source_text, cancel_check=cancelled)
                except OperationCancelled:
                    break
                with self._lock:
                    previous.set_summary(summary, source_text=source_text)
                    self._save()
            job.message = ""

            def progress(text: str, words: int, target: int) -> None:
                job.text, job.words, job.target = text, words, target

            kwargs: Dict[str, Any] = dict(progress_callback=progress, cancel_check=cancelled)
            if resume_from is not None:
                kwargs["resume_from"] = resume_from
            result = engine.generate_chapter(project, index, **kwargs)
            if not result.strip() and base_text:
                result = base_text
            with self._lock:
                chapter.content = result
                chapter.set_alternatives([result], 0)
                self._save()
            job.text, job.words = result, count_words(result)
            if not result.strip():
                return S.LISTO
            if cancelled():
                return S.CANCELADO_PUEDES_SEGUIR_CON_CONTINUAR
            job.message = S.GENERANDO_RESUMEN_PARA_CONTINUIDAD_ENTRE
            try:
                summary = call_supported(engine.summarize, result, cancel_check=cancelled)
            except OperationCancelled:
                return S.CANCELADO_ANTES_DEL_RESUMEN_USA
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo generar el resumen del capítulo %d", index + 1)
                return S.LISTO_PERO_NO_SE_PUDO
            with self._lock:
                chapter.set_summary(summary, source_text=result)
                self._save()
            seed = getattr(engine, "last_seed", None)
            return S.LISTO_SEMILLA.format(seed=seed) if seed is not None else S.LISTO

        return self._start("chapter", S.WEB_TAREA_CAPITULO.format(number=index + 1), work, chapter=index)

    # ---------------- generador de historias (/generador, app/generator.py) ----------------
    def start_story(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Escribe una historia del formulario del generador con el motor de los
        capítulos (un proyecto temporal de un capítulo con prompt propio) y la
        guarda en el historial del generador."""
        self._require_idle()
        if not self.engine.is_loaded:
            raise ApiError(HTTPStatus.CONFLICT, S.NO_HAY_MODELO_CARGADO)
        try:
            form = generator.clean_form(data)
        except generator.GeneratorError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        engine = self.engine
        total = int(form.get("chapters", 1) or 1)

        def write(prompt: str, words: int, progress) -> str:
            """Una pieza con el motor de los capítulos (un proyecto temporal de un capítulo con prompt propio)."""
            story = Project(name="Generador", plot=form["plot"], characters=form["characters"], setting=form["setting"])
            chapter = story.add_chapter("Story", target_words=min(words, MAX_WORDS_PER_CHAPTER))
            # Las llaves del usuario no son marcadores del prompt propio ({plot}...): un espacio de ancho cero
            # las separa (prompts._PLACEHOLDER_RE solo reconoce {palabra}).
            chapter.custom_prompt = prompt.replace("{", "{\u200b")
            return engine.generate_chapter(story, 0, progress_callback=progress, cancel_check=job_ref[0].cancel.is_set)

        job_ref: List[Job] = []

        def work(job: Job) -> str:
            job_ref.append(job)
            started = time.time()
            job.target = generator.target_words(form)
            parts: List[str] = []
            summary = ""
            for index in range(total):
                if total > 1:
                    job.label = S.GENERADOR_TAREA_CAPITULO.format(number=index + 1, total=total)
                done = "\n\n".join(parts)
                prefix = (done + "\n\n" if done else "") + (f"Chapter {index + 1}\n\n" if total > 1 else "")

                def progress(text: str, words: int, target: int, _prefix=prefix) -> None:
                    job.text = _prefix + text
                    job.words = count_words(job.text)

                piece = write(generator.build_prompt(form, chapter=index, story_so_far=summary),
                              generator.chapter_words(form), progress).strip()
                parts.append((f"Chapter {index + 1}\n\n" if total > 1 else "") + piece)
                if job.cancel.is_set() or not piece or index == total - 1:
                    break
                job.message = S.GENERADOR_RESUMIENDO.format(number=index + 1)
                chapter_summary = call_supported(engine.summarize, piece, cancel_check=job.cancel.is_set)
                summary = (summary + "\n" if summary else "") + f"Chapter {index + 1}: {chapter_summary.strip()}"
                job.message = ""
            result = "\n\n".join(parts).strip()
            job.text, job.words = result, count_words(result)
            if result:
                generator.add_to_history(form, result, time.time() - started, getattr(engine, "last_seed", None))
            if job.cancel.is_set():
                return S.WEB_TAREA_DETENIDA
            seed = getattr(engine, "last_seed", None)
            return S.LISTO_SEMILLA.format(seed=seed) if seed is not None else S.LISTO

        return self._start("story", S.GENERADOR_TAREA, work)

    def start_story_revision(self, entry_id: str, request: Any) -> Dict[str, Any]:
        """Pedir cambios sobre un resultado del generador: el modelo reescribe la historia según el
        pedido; el resultado es una entrada nueva del historial unida a la original."""
        self._require_idle()
        if not self.engine.is_loaded:
            raise ApiError(HTTPStatus.CONFLICT, S.NO_HAY_MODELO_CARGADO)
        entry = generator.get_entry(entry_id)
        if entry is None:
            raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)
        try:
            text_request = generator.clean_request(request)
        except generator.GeneratorError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        form = entry["form"]
        engine = self.engine

        def work(job: Job) -> str:
            started = time.time()
            words = max(generator.MIN_WORDS, int(entry.get("words") or count_words(entry.get("text", ""))))
            story = Project(name="Generador", plot=form.get("plot", ""))
            chapter = story.add_chapter("Story", target_words=min(words, MAX_WORDS_PER_CHAPTER))
            chapter.custom_prompt = generator.build_revision_prompt(form, entry["text"], text_request).replace("{", "{\u200b")
            job.target = chapter.target_words

            def progress(text: str, words_now: int, target: int) -> None:
                job.text, job.words, job.target = text, words_now, target

            result = engine.generate_chapter(story, 0, progress_callback=progress, cancel_check=job.cancel.is_set)
            job.text, job.words = result, count_words(result)
            if result.strip():
                generator.add_to_history(form, result, time.time() - started, getattr(engine, "last_seed", None),
                                         parent=entry_id, request=text_request)
            return S.WEB_TAREA_DETENIDA if job.cancel.is_set() else S.LISTO

        return self._start("story", S.GENERADOR_TAREA_REVISION, work)

    def story_to_project(self, entry_id: str) -> Dict[str, Any]:
        """Convierte un resultado del generador en un proyecto de StoryForge (archivo nuevo en la carpeta
        de proyectos); no cambia el proyecto abierto."""
        entry = generator.get_entry(entry_id)
        if entry is None:
            raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)
        project = generator.project_from_entry(entry)
        stem = _slug(project.name)
        filename = f"{stem}{PROJECT_SUFFIX}"
        n = 2
        while os.path.exists(os.path.join(self.projects_dir, filename)):
            filename = f"{stem}_{n}{PROJECT_SUFFIX}"
            n += 1
        project.save(os.path.join(self.projects_dir, filename))
        return {"archivo": filename, "nombre": project.name, "capitulos": len(project.chapters),
                "mensaje": S.GENERADOR_PROYECTO_CREADO.format(name=project.name)}

    def start_summary(self, index: int) -> Dict[str, Any]:
        """Regenerar resumen de un capitulo."""
        self._require_idle()
        self._check_ready()
        chapter = self._chapter(index)
        engine = self.engine
        content = chapter.content

        def work(job: Job) -> str:
            summary = call_supported(engine.summarize, content, cancel_check=job.cancel.is_set)
            with self._lock:
                chapter.set_summary(summary, source_text=content)
                self._save()
            return S.WEB_RESUMEN_LISTO

        return self._start("summary", S.WEB_TAREA_RESUMEN.format(number=index + 1), work, chapter=index)

    # ---------------- exportar ----------------
    def export(self, fmt: str) -> Tuple[bytes, str, str]:
        project = self._require_project()
        if fmt not in EXPORT_FORMATS:
            raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_FORMATO_DESCONOCIDO.format(fmt=fmt))
        filename = f"{_slug(project.name)}.{fmt}"
        if fmt == "txt":
            data = build_txt(project).encode("utf-8")
        elif fmt == "md":
            data = build_markdown(project).encode("utf-8")
        elif fmt == "epub":
            data = build_epub_bytes(project)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, filename)
                export_docx(project, path)
                data = Path(path).read_bytes()
        return data, filename, EXPORT_FORMATS[fmt]


# ---------------------------------------------------------------- HTTP

def _int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_SOLICITUD_INVALIDA) from exc


# (metodo, patron) -> funcion(servicio, coincidencias, cuerpo, consulta)
ROUTES: List[Tuple[str, "re.Pattern[str]", Callable[..., Any]]] = []


def route(method: str, pattern: str):
    def register(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return register


@route("GET", r"/api/estado")
def _r_status(svc, m, body, q):
    return svc.status()


@route("GET", r"/api/modelos")
def _r_models(svc, m, body, q):
    return svc.list_models()


@route("POST", r"/api/modelo/cargar")
def _r_load(svc, m, body, q):
    return svc.load_model(str(body.get("modelo") or ""))


@route("POST", r"/api/modelo/descargar")
def _r_unload(svc, m, body, q):
    svc.unload_model()
    return svc.status()


@route("GET", r"/api/proyectos")
def _r_projects(svc, m, body, q):
    return svc.list_projects()


@route("POST", r"/api/proyectos")
def _r_create(svc, m, body, q):
    return svc.create_project(str(body.get("nombre") or ""))


@route("POST", r"/api/proyectos/importar")
def _r_import(svc, m, body, q):
    return svc.import_manuscript(str(body.get("nombre") or ""), str(body.get("datos") or ""))


@route("POST", r"/api/proyecto/abrir")
def _r_open(svc, m, body, q):
    return svc.open_project(str(body.get("archivo") or ""))


@route("GET", r"/api/proyecto")
def _r_project(svc, m, body, q):
    return svc.project_view()


@route("PUT", r"/api/proyecto")
def _r_update_project(svc, m, body, q):
    return svc.update_project(body)


@route("POST", r"/api/capitulos")
def _r_add_chapter(svc, m, body, q):
    return svc.add_chapter(body)


@route("GET", r"/api/capitulo/(\d+)")
def _r_chapter(svc, m, body, q):
    return svc.chapter_view(_int(m.group(1)))


@route("PUT", r"/api/capitulo/(\d+)")
def _r_update_chapter(svc, m, body, q):
    return svc.update_chapter(_int(m.group(1)), body)


@route("DELETE", r"/api/capitulo/(\d+)")
def _r_delete_chapter(svc, m, body, q):
    svc.delete_chapter(_int(m.group(1)))
    return svc.project_view()


@route("POST", r"/api/capitulo/(\d+)/generar")
def _r_generate(svc, m, body, q):
    return svc.start_chapter(_int(m.group(1)), resume=bool(body.get("continuar")))


@route("POST", r"/api/capitulo/(\d+)/resumen")
def _r_summary(svc, m, body, q):
    return svc.start_summary(_int(m.group(1)))


@route("POST", r"/api/esquema")
def _r_outline(svc, m, body, q):
    return svc.start_outline(body.get("capitulos"))


@route("GET", r"/api/generador")
def _r_generator_options(svc, m, body, q):
    return generator.options()


@route("POST", r"/api/generador/generar")
def _r_generator_start(svc, m, body, q):
    return svc.start_story(body)


@route("GET", r"/api/generador/historial")
def _r_generator_history(svc, m, body, q):
    return generator.history()


@route("POST", r"/api/generador/historial/([0-9a-f]{12})/guardar")
def _r_generator_save(svc, m, body, q):
    entry = generator.set_saved(m.group(1), bool(body.get("guardado", True)))
    if entry is None:
        raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)
    return entry


@route("POST", r"/api/generador/historial/([0-9a-f]{12})/revisar")
def _r_generator_revise(svc, m, body, q):
    return svc.start_story_revision(m.group(1), body.get("pedido"))


@route("POST", r"/api/generador/historial/([0-9a-f]{12})/valorar")
def _r_generator_rate(svc, m, body, q):
    try:
        entry = generator.set_rating(m.group(1), str(body.get("valor", "")))
    except generator.GeneratorError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    if entry is None:
        raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)
    return entry


@route("POST", r"/api/generador/historial/([0-9a-f]{12})/proyecto")
def _r_generator_project(svc, m, body, q):
    return svc.story_to_project(m.group(1))


@route("DELETE", r"/api/generador/historial/([0-9a-f]{12})")
def _r_generator_delete(svc, m, body, q):
    if not generator.delete_entry(m.group(1)):
        raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)
    return {}


@route("POST", r"/api/generador/presets")
def _r_generator_preset_save(svc, m, body, q):
    try:
        name = generator.save_preset(str(body.get("nombre", "")), generator.clean_form(body.get("formulario")))
    except generator.GeneratorError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    return {"nombre": name, "presets": generator.presets()}


@route("POST", r"/api/generador/presets/borrar")
def _r_generator_preset_delete(svc, m, body, q):
    if not generator.delete_preset(str(body.get("nombre", ""))):
        raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)
    return {"presets": generator.presets()}


@route("POST", r"/api/detener")
def _r_stop(svc, m, body, q):
    svc.stop()
    return svc.job_snapshot()


@route("GET", r"/api/tarea")
def _r_job(svc, m, body, q):
    return svc.job_snapshot(_int((q.get("desde") or ["0"])[0]))


class _Handler(BaseHTTPRequestHandler):
    server: "StoryForgeHTTPServer"
    protocol_version = "HTTP/1.1"

    # Sin una linea por peticion en el registro (la pagina consulta cada segundo).
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        logger.debug("%s - %s", self.address_string(), format % args)

    def _is_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _send(self, status: int, payload: bytes, content_type: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _authorized(self) -> bool:
        given = self.headers.get(TOKEN_HEADER, "")
        return bool(given) and hmac.compare_digest(given.encode(), self.server.token.encode())

    def _read_raw_body(self) -> bytes:
        """Lee el cuerpo ANTES de cualquier respuesta: con keep-alive, un cuerpo
        sin leer (p.ej. tras un 401) se mezclaria con la siguiente peticion."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        limit = MAX_IMPORT_BODY_BYTES if self.path.split("?")[0] == IMPORT_PATH else MAX_BODY_BYTES
        if length < 0 or length > limit:
            self.close_connection = True
            return b""
        return self.rfile.read(length) if length else b""

    def _body(self) -> Dict[str, Any]:
        raw = self._raw_body
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_SOLICITUD_INVALIDA) from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, S.WEB_SOLICITUD_INVALIDA)
        return data

    def _handle(self) -> None:
        url = urlparse(self.path)
        path = url.path
        self._raw_body = self._read_raw_body()
        try:
            if path.startswith("/api/"):
                self._api(path, parse_qs(url.query))
            else:
                self._static(path)
        except ApiError as exc:
            self._error(exc.status, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error en %s %s", self.command, path)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, S.ERROR_GENERICO.format(exc=describe_exception(exc)))

    def _api(self, path: str, query: Dict[str, List[str]]) -> None:
        if path == "/api/conexion":
            # La pagina de conexion de la PC: enlace + clave para el QR.
            if not self._is_local():
                raise ApiError(HTTPStatus.FORBIDDEN, S.WEB_SOLO_DESDE_LA_PC)
            self._json(HTTPStatus.OK, {"url": self.server.phone_url, "carpeta": self.server.service.projects_dir,
                                       "token": self.server.token})
            return
        if path == "/api/apagar" and self.command == "POST":
            if not self._is_local():
                raise ApiError(HTTPStatus.FORBIDDEN, S.WEB_SOLO_DESDE_LA_PC)
            self._json(HTTPStatus.OK, {})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if not self._authorized():
            raise ApiError(HTTPStatus.UNAUTHORIZED, S.WEB_NO_AUTORIZADO)
        if path.startswith("/api/exportar/") and self.command == "GET":
            data, filename, mime = self.server.service.export(path.rsplit("/", 1)[-1])
            self._send(HTTPStatus.OK, data, mime, {"Content-Disposition": f'attachment;filename="{filename}"'})
            return
        body = self._body() if self.command in ("POST", "PUT") else {}
        for method, pattern, fn in ROUTES:
            match = pattern.match(path)
            if match and method == self.command:
                self._json(HTTPStatus.OK, fn(self.server.service, match, body, query))
                return
        raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)

    def _static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        elif path == "/generador":
            path = "/generador.html"
        elif path == "/conectar":
            if not self._is_local():
                raise ApiError(HTTPStatus.FORBIDDEN, S.WEB_SOLO_DESDE_LA_PC)
            path = "/conectar.html"
        target = (WEB_DIR / path.lstrip("/")).resolve()
        if WEB_DIR not in target.parents or not target.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, S.WEB_NO_ENCONTRADO)
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
            mime += "; charset=utf-8"
        if target.suffix == ".webmanifest":
            mime = "application/manifest+json"
        self._send(HTTPStatus.OK, target.read_bytes(), mime)

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = _handle


class StoryForgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service: StoryForgeService, token: str) -> None:
        super().__init__(address, _Handler)
        self.service = service
        self.token = token
        port = self.server_address[1]
        self.local_url = f"http://127.0.0.1:{port}/conectar"
        self.phone_url = f"http://{lan_ip()}:{port}/?t={token}"
        self.generator_url = f"http://127.0.0.1:{port}/generador?t={token}"


def create_server(engine, projects_dir: str, port: int = DEFAULT_PORT, host: str = "0.0.0.0",
                  token: Optional[str] = None) -> StoryForgeHTTPServer:
    service = StoryForgeService(engine, projects_dir)
    return StoryForgeHTTPServer((host, port), service, token or access_token())


def serve(port: int = DEFAULT_PORT, projects_dir: Optional[str] = None, open_browser: bool = True,
          models_dir: Optional[str] = None, generator_page: bool = False) -> int:
    """Punto de entrada de `storyforge.py --servidor`."""
    from .engine import LocalStoryEngine

    if models_dir:
        remember_models_dir(models_dir)
    if projects_dir:
        remember_projects_dir(projects_dir)
    folder = projects_dir or default_projects_dir()
    try:
        server = create_server(LocalStoryEngine(), folder, port)
    except OSError as exc:
        _show(S.WEB_PUERTO_OCUPADO.format(port=port, exc=describe_exception(exc)), error=True)
        return 1
    message = S.WEB_SERVIDOR_LISTO.format(local_url=server.local_url, phone_url=server.phone_url,
                                          projects_dir=server.service.projects_dir)
    _show(message)
    if open_browser:
        import webbrowser

        # El generador se abre en esta PC con la clave en el enlace (la página la guarda y la quita).
        webbrowser.open(server.generator_url if generator_page else server.local_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.service.stop()
    return 0


def _show(message: str, error: bool = False) -> None:
    """En la consola si la hay; el .exe no tiene (sys.stdout es None), ahi va al registro."""
    if sys.stdout is not None:
        print(message, flush=True)
    elif error:
        logger.error(message)
    else:
        logger.info(message)
