"""
Modelo de datos del proyecto de historia: plot, personajes, setting y capitulos.
Incluye conteo de palabras, validacion de limites y persistencia JSON
versionada (ver FORMAT_VERSION / migrate()).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fileutil import atomic_write_text, is_under
from .sampling import SamplingConfig

logger = logging.getLogger(__name__)

# ---- Limites del proyecto (definidos por especificacion de la app) ----
MAX_PLOT_WORDS = 50_000
MAX_CHARACTERS_WORDS = 10_000
MAX_SETTING_WORDS = 10_000
MAX_CHAPTERS = 10
MAX_WORDS_PER_CHAPTER = 10_000
MAX_OUTLINE_WORDS_PER_CHAPTER = 800
MAX_AUTHOR_NOTE_WORDS = 150
# Cuantas versiones anteriores de chapter.content se conservan por defecto
# (la mas vieja se descarta al llegar al limite) cada vez que se regenera,
# refina, reescribe o restaura un capitulo -- ver Chapter.push_history(). Se
# puede cambiar por proyecto (Project.history_limit).
MAX_CHAPTER_HISTORY = 20
HISTORY_LIMIT_RANGE = (1, 100)
# Alternativas de "Reintentar" que se guardan con el capitulo (las mas viejas
# se descartan): cada una es el texto completo del capitulo.
MAX_CHAPTER_ALTERNATIVES = 10

# Limites del Lorebook / World Info: entradas de contexto que solo se
# inyectan en el prompt cuando alguna de sus keywords aparece en el texto
# cercano de la generacion en curso (ver prompts.match_lore_entries), a
# diferencia de plot/personajes/setting que siempre se incluyen completos.
MAX_LORE_ENTRIES = 200
MAX_LORE_ENTRY_WORDS = 500

# Version del formato del archivo de proyecto. 1 = sin "format_version"
# (todo lo guardado antes de esta version). 2 = historial con origen y fecha,
# lorebook con prioridad/activo/siempre, nota del autor, muestreo, titulo y
# autor de la historia, ruta del modelo relativa a models/.
FORMAT_VERSION = 2

# Tipos de escritura seleccionables (aplican a toda la historia, no por
# capitulo). "" (sin seleccionar) significa usar solo el STYLE_GUIDE por
# defecto de prompts.py, sin enfasis adicional. Son CLAVES guardadas en los
# proyectos: no se cambian (los textos que ve el usuario, con acentos, estan
# en app/strings_es.py).
WRITING_STYLES = [
    "Narrativa",
    "Descriptiva",
    "Creativa",
    "Dialogo",
    "Poetica",
    "Accion rapida",
]

# Proposito narrativo de un capitulo especifico (a diferencia de
# writing_style, que aplica a toda la historia). "" = capitulo regular, sin
# instruccion adicional. Tambien son claves guardadas (ver arriba).
CHAPTER_PURPOSES = [
    "Apertura",
    "Escena climatica",
    "Final",
    "Epilogo",
]

# Aqui y no arriba: strings_es importa WRITING_STYLES/CHAPTER_PURPOSES de este
# modulo, asi que tienen que existir antes (funciona en cualquier orden de import:
# los mensajes S.* se leen recien al usarlos).
from . import strings_es as S  # noqa: E402

DEFAULT_PROJECT_NAME = "Historia sin título"
CHAPTER_HEADING_CHOICES = ["Chapter", "Capítulo", ""]

_WORD_RE = re.compile(r"\b[\w'\-]+\b", re.UNICODE)


def count_words(text: str) -> int:
    """Cuenta palabras de forma consistente en toda la app."""
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


def content_hash(text: str) -> str:
    """
    Huella del texto de un capitulo, para saber si su resumen sigue
    correspondiendo a lo que hay escrito (ver Chapter.summary_is_stale()).
    Ignora espacios al principio/final: agregar o quitar un salto de linea
    suelto no deberia marcar el resumen como desactualizado.
    """
    return hashlib.sha1((text or "").strip().encode("utf-8", errors="ignore")).hexdigest()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- lectura tolerante
def _str_field(data: dict, key: str, default: str = "", where: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    logger.warning("Campo %s%s invalido (%s); se usa el valor por defecto", where, key, type(value).__name__)
    return default


def _int_field(data: dict, key: str, default: int, where: str = "") -> int:
    value = data.get(key, default)
    if isinstance(value, bool):
        value = default
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Campo %s%s invalido (%r); se usa %r", where, key, value, default)
        return default


def _bool_field(data: dict, key: str, default: bool) -> bool:
    value = data.get(key, default)
    return value if isinstance(value, bool) else default


def _list_field(data: dict, key: str, where: str = "") -> list:
    value = data.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    logger.warning("Campo %s%s no es una lista; se ignora", where, key)
    return []


@dataclass
class Chapter:
    title: str = ""
    target_words: int = 2000
    content: str = ""
    # breve resumen (generado o manual) usado como contexto para el siguiente capitulo
    summary: str = ""
    # content_hash() del texto que `summary` resume. Si `content` cambia
    # despues (refinar, restaurar una version, reducir repeticion, editar a
    # mano, una generacion cancelada o continuada...), el resumen queda
    # desactualizado -- ver summary_is_stale(). Vacio si no hay resumen.
    summary_source_hash: str = ""
    # esquema/beat sheet de este capitulo (generado o manual), usado para guiar
    # la generacion de prosa antes de escribirla (workflow "outline-first")
    outline: str = ""
    # uno de CHAPTER_PURPOSES, o "" para un capitulo regular sin instruccion
    # narrativa adicional (ver prompts.build_chapter_purpose_instruction)
    purpose: str = ""
    # Nota del autor: una instruccion corta que se inserta CERCA DEL FINAL del
    # prompt de este capitulo (ver prompts.build_author_note_block), donde
    # pesa mas que las reglas del principio de un prompt largo.
    author_note: str = ""
    # versiones anteriores de `content`, mas vieja primero, acotado al limite
    # de historial (ver push_history()) -- permite recuperar el texto de antes
    # de un regenerar/refinar sin depender solo de la confirmacion previa al
    # sobrescribir. `history_meta[i]` describe `history[i]`: {"source": por que
    # se guardo (p.ej. "refinar: hazlo mas oscuro"), "at": fecha ISO}.
    history: List[str] = field(default_factory=list)
    history_meta: List[Dict[str, str]] = field(default_factory=list)
    # Alternativas de la ultima ejecucion de Generar/Continuar + "Reintentar"
    # (se recorren con < >), guardadas con el proyecto; `alt_index` es la que
    # esta en `content`. Una edicion a mano las descarta (ui_chapter_editor).
    alternatives: List[str] = field(default_factory=list)
    alt_index: int = -1

    def set_alternatives(self, texts: List[str], index: int) -> None:
        """Guarda las alternativas (a lo sumo MAX_CHAPTER_ALTERNATIVES, las
        mas nuevas) con `index` apuntando a la misma dentro de la lista."""
        drop = max(0, len(texts) - MAX_CHAPTER_ALTERNATIVES)
        self.alternatives = list(texts[drop:])
        self.alt_index = index - drop if self.alternatives and 0 <= index - drop < len(self.alternatives) else -1
        if self.alt_index < 0:
            self.alternatives = []

    def word_count(self) -> int:
        return count_words(self.content)

    def outline_words(self) -> int:
        return count_words(self.outline)

    def set_summary(self, summary: str, source_text: Optional[str] = None) -> None:
        """Guarda un resumen (generado o escrito a mano) como correspondiente
        a `source_text` (por defecto, el texto ACTUAL del capitulo)."""
        self.summary = summary or ""
        source = self.content if source_text is None else source_text
        self.summary_source_hash = content_hash(source) if self.summary.strip() else ""

    def summary_is_stale(self) -> bool:
        """True si hay un resumen pero el texto del capitulo cambio desde que
        se escribio (el resumen ya no describe lo que hay)."""
        if not self.summary.strip():
            return False
        return self.summary_source_hash != content_hash(self.content)

    def needs_summary(self) -> bool:
        """True si el capitulo tiene texto pero su resumen falta o esta
        desactualizado -- el capitulo siguiente recibiria contexto incorrecto."""
        if not self.content.strip():
            return False
        return not self.summary.strip() or self.summary_is_stale()

    def push_history(self, source: str = "", limit: int = MAX_CHAPTER_HISTORY) -> None:
        """
        Guarda el `content` actual en `history` antes de que algo lo
        sobrescriba (regenerar, refinar, o restaurar otra version). No hace
        nada si el contenido actual esta vacio -- no tiene sentido guardar
        "nada" como una version. `source` dice que accion lo reemplazo.
        """
        if not self.content.strip():
            return
        self._align_meta()
        self.history.append(self.content)
        self.history_meta.append({"source": source, "at": _now_iso()})
        limit = max(1, int(limit))
        if len(self.history) > limit:
            self.history = self.history[-limit:]
            self.history_meta = self.history_meta[-limit:]

    def _align_meta(self) -> None:
        """history_meta siempre tiene un elemento por version (codigo viejo
        o pruebas pueden haber modificado `history` directamente)."""
        if len(self.history_meta) < len(self.history):
            missing = len(self.history) - len(self.history_meta)
            self.history_meta = [{"source": "", "at": ""} for _ in range(missing)] + self.history_meta
        elif len(self.history_meta) > len(self.history):
            self.history_meta = self.history_meta[-len(self.history):] if self.history else []

    def history_entries(self) -> List[Dict[str, str]]:
        """[{"text", "source", "at"}], mas vieja primero."""
        self._align_meta()
        return [
            {"text": text, "source": meta.get("source", ""), "at": meta.get("at", "")}
            for text, meta in zip(self.history, self.history_meta)
        ]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "target_words": self.target_words,
            "content": self.content,
            "summary": self.summary,
            "summary_source_hash": self.summary_source_hash,
            "outline": self.outline,
            "purpose": self.purpose,
            "author_note": self.author_note,
            "history": self.history_entries(),
            **({"alternatives": {"texts": list(self.alternatives), "index": self.alt_index}}
               if self.alternatives else {}),
        }

    @staticmethod
    def from_dict(d: dict, where: str = "") -> "Chapter":
        if not isinstance(d, dict):
            raise ValueError(S.CAPITULO_INVALIDO)
        chapter = Chapter(
            title=_str_field(d, "title", "", where),
            target_words=max(1, min(_int_field(d, "target_words", 2000, where), MAX_WORDS_PER_CHAPTER)),
            content=_str_field(d, "content", "", where),
            summary=_str_field(d, "summary", "", where),
            outline=_str_field(d, "outline", "", where),
            purpose=_str_field(d, "purpose", "", where),
            author_note=_str_field(d, "author_note", "", where),
        )
        for item in _list_field(d, "history", where):
            # Formato 1: lista de textos. Formato 2: {"text", "source", "at"}.
            if isinstance(item, str):
                chapter.history.append(item)
                chapter.history_meta.append({"source": "", "at": ""})
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                chapter.history.append(item["text"])
                chapter.history_meta.append({
                    "source": str(item.get("source") or ""), "at": str(item.get("at") or ""),
                })
            else:
                logger.warning("Version invalida en el historial de %s; se ignora", where or "un capitulo")
        alternatives = d.get("alternatives")
        if isinstance(alternatives, dict):
            texts = alternatives.get("texts")
            index = alternatives.get("index")
            # Solo si la alternativa elegida sigue siendo el texto del capitulo
            # (si no, el texto se edito por fuera y ya no corresponden).
            if (isinstance(texts, list) and all(isinstance(t, str) for t in texts)
                    and isinstance(index, int) and 0 <= index < len(texts) and texts[index] == chapter.content):
                chapter.set_alternatives(texts, index)
        if "summary_source_hash" in d:
            chapter.summary_source_hash = _str_field(d, "summary_source_hash", "", where)
        elif chapter.summary.strip():
            # Proyecto guardado antes de que existiera este campo: no hay
            # forma de saber si el resumen estaba al dia, asi que se asume
            # que si (lo mismo que la app asumia entonces) en vez de marcar
            # todos los resumenes viejos como desactualizados.
            chapter.summary_source_hash = content_hash(chapter.content)
        return chapter


@dataclass
class LoreEntry:
    """
    Una entrada del Lorebook / World Info: un personaje secundario, lugar,
    objeto u otro dato de mundo que no necesita repetirse en el bloque de
    contexto completo de cada capitulo. `keywords` es una lista separada por
    comas; `prompts.match_lore_entries()` busca cada termino en el texto
    cercano de la generacion en curso para decidir si esta entrada es
    relevante ahora mismo.

    - `enabled`: una entrada desactivada nunca se incluye.
    - `constant`: siempre se incluye, coincida o no (personajes principales
      del lorebook, reglas del mundo...).
    - `priority`: cuando coinciden mas entradas de las que caben, primero
      las de mayor prioridad.
    """
    name: str = ""
    keywords: str = ""
    text: str = ""
    enabled: bool = True
    constant: bool = False
    priority: int = 0

    def keyword_list(self) -> List[str]:
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

    def word_count(self) -> int:
        return count_words(self.text)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "keywords": self.keywords, "text": self.text,
            "enabled": self.enabled, "constant": self.constant, "priority": self.priority,
        }

    @staticmethod
    def from_dict(d: dict, where: str = "") -> "LoreEntry":
        if not isinstance(d, dict):
            raise ValueError(S.ENTRADA_LOREBOOK_INVALIDA)
        return LoreEntry(
            name=_str_field(d, "name", "", where),
            keywords=_str_field(d, "keywords", "", where),
            text=_str_field(d, "text", "", where),
            enabled=_bool_field(d, "enabled", True),
            constant=_bool_field(d, "constant", False),
            priority=max(-100, min(_int_field(d, "priority", 0, where), 100)),
        )


def portable_model_path(path: Optional[str], models_dir: Optional[str]) -> Optional[str]:
    """La ruta del modelo como se guarda en el proyecto: relativa a models/
    (con "/") cuando el modelo vive ahi, para que el proyecto siga
    funcionando si se mueve la carpeta del programa; absoluta si no."""
    if not path:
        return None
    if models_dir and is_under(path, models_dir):
        return os.path.relpath(os.path.abspath(path), os.path.abspath(models_dir)).replace(os.sep, "/")
    return path


def resolve_model_path(stored: Optional[str], models_dir: Optional[str]) -> Optional[str]:
    """Inversa de portable_model_path()."""
    if not stored:
        return None
    if os.path.isabs(stored) or not models_dir:
        return stored
    return os.path.join(models_dir, *stored.split("/"))


@dataclass
class Project:
    name: str = DEFAULT_PROJECT_NAME
    plot: str = ""
    characters: str = ""
    setting: str = ""
    chapters: List[Chapter] = field(default_factory=list)
    # Ruta del ultimo modelo cargado para este proyecto: relativa a models/ si
    # vive ahi (ver portable_model_path), absoluta si no.
    model_path: Optional[str] = None
    # Contexto (n_ctx) con el que se escribio el proyecto. La configuracion
    # que depende de la PC (capas en GPU, hilos, flash attention, cache KV)
    # no va aqui sino en settings.json, por modelo (ver app/settings.py).
    context_size: Optional[int] = None
    # Uno de WRITING_STYLES, o "" para no aplicar ningun enfasis adicional.
    writing_style: str = ""
    # Lorebook / World Info -- ver LoreEntry arriba.
    lore_entries: List[LoreEntry] = field(default_factory=list)
    author: str = ""
    # Nota del autor para toda la historia (cada capitulo puede tener la suya).
    author_note: str = ""
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    # Encabezado de capitulo al exportar ("Chapter", "Capítulo" o "" = solo el titulo).
    chapter_heading: str = "Chapter"
    history_limit: int = MAX_CHAPTER_HISTORY

    # ---------------- validaciones ----------------
    def plot_words(self) -> int:
        return count_words(self.plot)

    def characters_words(self) -> int:
        return count_words(self.characters)

    def setting_words(self) -> int:
        return count_words(self.setting)

    def total_words(self) -> int:
        return sum(ch.word_count() for ch in self.chapters)

    def validate_inputs(self) -> List[str]:
        """Devuelve una lista de mensajes de error; vacia si todo es valido."""
        errors = []
        if self.plot_words() > MAX_PLOT_WORDS:
            errors.append(
                f"El plot tiene {self.plot_words():,} palabras (máximo {MAX_PLOT_WORDS:,})."
            )
        if self.characters_words() > MAX_CHARACTERS_WORDS:
            errors.append(
                f"Los personajes tienen {self.characters_words():,} palabras "
                f"(máximo {MAX_CHARACTERS_WORDS:,})."
            )
        if self.setting_words() > MAX_SETTING_WORDS:
            errors.append(
                f"El setting tiene {self.setting_words():,} palabras (máximo {MAX_SETTING_WORDS:,})."
            )
        if count_words(self.author_note) > MAX_AUTHOR_NOTE_WORDS:
            errors.append(
                f"La nota del autor de la historia tiene {count_words(self.author_note):,} palabras "
                f"(máximo {MAX_AUTHOR_NOTE_WORDS:,})."
            )
        if len(self.chapters) > MAX_CHAPTERS:
            errors.append(
                f"Hay {len(self.chapters)} capítulos (máximo {MAX_CHAPTERS})."
            )
        for i, ch in enumerate(self.chapters, start=1):
            if ch.target_words > MAX_WORDS_PER_CHAPTER:
                errors.append(
                    f"Capítulo {i}: objetivo de {ch.target_words:,} palabras "
                    f"excede el máximo ({MAX_WORDS_PER_CHAPTER:,})."
                )
            if ch.outline_words() > MAX_OUTLINE_WORDS_PER_CHAPTER:
                errors.append(
                    f"Capítulo {i}: el esquema tiene {ch.outline_words():,} palabras "
                    f"(máximo {MAX_OUTLINE_WORDS_PER_CHAPTER:,})."
                )
            if count_words(ch.author_note) > MAX_AUTHOR_NOTE_WORDS:
                errors.append(
                    f"Capítulo {i}: la nota del autor tiene {count_words(ch.author_note):,} palabras "
                    f"(máximo {MAX_AUTHOR_NOTE_WORDS:,})."
                )
        if len(self.lore_entries) > MAX_LORE_ENTRIES:
            errors.append(
                f"Hay {len(self.lore_entries)} entradas de lorebook (máximo {MAX_LORE_ENTRIES})."
            )
        for i, entry in enumerate(self.lore_entries, start=1):
            if entry.word_count() > MAX_LORE_ENTRY_WORDS:
                label = entry.name.strip() or f"entrada {i}"
                errors.append(
                    f"Lorebook '{label}': el texto tiene {entry.word_count():,} palabras "
                    f"(máximo {MAX_LORE_ENTRY_WORDS:,})."
                )
        return errors

    def validate_warnings(self) -> List[str]:
        """
        Avisos que NO deben bloquear la generacion. Un capitulo cuyo texto ya
        generado pasa de MAX_WORDS_PER_CHAPTER (la ultima seccion de
        generate_chapter() puede pasarse un poco, o el usuario lo edito a
        mano) antes era un error en validate_inputs(), lo que bloqueaba
        generar CUALQUIER capitulo o el esquema hasta recortarlo a mano.
        """
        warnings = []
        for i, ch in enumerate(self.chapters, start=1):
            if ch.word_count() > MAX_WORDS_PER_CHAPTER:
                warnings.append(
                    S.CAPITULO_DEMASIADO_LARGO.format(number=i, words=ch.word_count(), maximum=MAX_WORDS_PER_CHAPTER)
                )
        return warnings

    def can_add_chapter(self) -> bool:
        return len(self.chapters) < MAX_CHAPTERS

    def add_chapter(self, title: str = "", target_words: int = 2000, outline: str = "") -> Chapter:
        if not self.can_add_chapter():
            raise ValueError(S.MAXIMO_DE_CAPITULOS.format(maximum=MAX_CHAPTERS))
        target_words = min(int(target_words), MAX_WORDS_PER_CHAPTER)
        chapter = Chapter(
            title=title or f"Capítulo {len(self.chapters) + 1}",
            target_words=target_words,
            outline=outline,
        )
        self.chapters.append(chapter)
        return chapter

    def push_chapter_history(self, chapter: Chapter, source: str = "") -> None:
        chapter.push_history(source=source, limit=self.history_limit)

    # ---------------- lorebook / world info ----------------
    def can_add_lore_entry(self) -> bool:
        return len(self.lore_entries) < MAX_LORE_ENTRIES

    def add_lore_entry(self, name: str = "", keywords: str = "", text: str = "") -> LoreEntry:
        if not self.can_add_lore_entry():
            raise ValueError(S.MAXIMO_DE_ENTRADAS_LOREBOOK.format(maximum=MAX_LORE_ENTRIES))
        entry = LoreEntry(name=name, keywords=keywords, text=text)
        self.lore_entries.append(entry)
        return entry

    # ---------------- persistencia ----------------
    def to_dict(self) -> dict:
        return {
            "format_version": FORMAT_VERSION,
            "name": self.name,
            "author": self.author,
            "plot": self.plot,
            "characters": self.characters,
            "setting": self.setting,
            "chapters": [c.to_dict() for c in self.chapters],  # incluye summary_source_hash
            "model_path": self.model_path,
            "context_size": self.context_size,
            "writing_style": self.writing_style,
            "author_note": self.author_note,
            "sampling": self.sampling.to_dict(),
            "chapter_heading": self.chapter_heading,
            "history_limit": self.history_limit,
            "lore_entries": [e.to_dict() for e in self.lore_entries],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path: str | Path) -> None:
        """
        Guardado atomico (ver app/fileutil.py): se escribe a un archivo
        temporal en la misma carpeta y se reemplaza el destino, con
        reintentos si OneDrive/el antivirus lo tiene tomado un instante. Antes
        de reemplazarlo, la version anterior se conserva como `<archivo>.bak`.
        """
        save_json_text(path, self.to_json())

    @staticmethod
    def from_dict(data: Any) -> "Project":
        if not isinstance(data, dict):
            raise ValueError(S.ARCHIVO_NO_ES_PROYECTO)
        data = migrate(data)
        name = _str_field(data, "name", DEFAULT_PROJECT_NAME).strip() or DEFAULT_PROJECT_NAME
        proj = Project(
            name=name,
            author=_str_field(data, "author", ""),
            plot=_str_field(data, "plot", ""),
            characters=_str_field(data, "characters", ""),
            setting=_str_field(data, "setting", ""),
            writing_style=_str_field(data, "writing_style", ""),
            author_note=_str_field(data, "author_note", ""),
        )
        model_path = data.get("model_path")
        proj.model_path = model_path if isinstance(model_path, str) and model_path.strip() else None
        context_size = data.get("context_size")
        if isinstance(context_size, int) and not isinstance(context_size, bool) and context_size > 0:
            proj.context_size = context_size
        proj.sampling = SamplingConfig.from_dict(data.get("sampling"))
        heading = data.get("chapter_heading", "Chapter")
        proj.chapter_heading = heading if isinstance(heading, str) else "Chapter"
        lo, hi = HISTORY_LIMIT_RANGE
        proj.history_limit = max(lo, min(_int_field(data, "history_limit", MAX_CHAPTER_HISTORY), hi))
        for i, item in enumerate(_list_field(data, "chapters")):
            try:
                proj.chapters.append(Chapter.from_dict(item, where=f"capítulo {i + 1}: "))
            except ValueError:
                logger.warning("Capitulo %d invalido en el proyecto; se omite", i + 1)
        if len(proj.chapters) > MAX_CHAPTERS:
            logger.warning("El proyecto tiene %d capitulos (maximo %d)", len(proj.chapters), MAX_CHAPTERS)
        for i, item in enumerate(_list_field(data, "lore_entries")):
            try:
                proj.lore_entries.append(LoreEntry.from_dict(item, where=f"lorebook {i + 1}: "))
            except ValueError:
                logger.warning("Entrada de lorebook %d invalida; se omite", i + 1)
        return proj

    @staticmethod
    def load(path: str | Path) -> "Project":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return Project.from_dict(data)


def save_json_text(path: str | Path, text: str) -> None:
    atomic_write_text(path, text, backup=True)


def migrate(data: dict) -> dict:
    """Lleva un proyecto de cualquier formato anterior al actual. Devuelve un
    dict nuevo (no modifica `data`)."""
    data = dict(data)
    version = data.get("format_version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        logger.warning("format_version invalido (%r); se asume 1", version)
        version = 1
    if version > FORMAT_VERSION:
        logger.warning(
            "El proyecto tiene format_version %d, mas nuevo que esta version de la app (%d); "
            "los campos desconocidos se ignoran", version, FORMAT_VERSION,
        )
    # 1 -> 2: el historial pasa de lista de textos a {"text","source","at"},
    # el lorebook gana enabled/constant/priority. Chapter.from_dict y
    # LoreEntry.from_dict aceptan ambos formatos con valores por defecto, asi
    # que no hay que transformar nada aqui; solo se registra la version.
    data["format_version"] = FORMAT_VERSION
    return data
