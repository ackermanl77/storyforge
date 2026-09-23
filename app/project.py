"""
Modelo de datos del proyecto de historia: plot, personajes, setting y capitulos.
Incluye conteo de palabras y validacion de limites.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# ---- Limites del proyecto (definidos por especificacion de la app) ----
MAX_PLOT_WORDS = 50_000
MAX_CHARACTERS_WORDS = 10_000
MAX_SETTING_WORDS = 10_000
MAX_CHAPTERS = 10
MAX_WORDS_PER_CHAPTER = 10_000
MAX_OUTLINE_WORDS_PER_CHAPTER = 800
# Cuantas versiones anteriores de chapter.content se conservan (la mas vieja
# se descarta al llegar al limite) cada vez que se regenera o refina un
# capitulo que ya tenia contenido -- ver Chapter.push_history().
MAX_CHAPTER_HISTORY = 5

# Limites del Lorebook / World Info: entradas de contexto que solo se
# inyectan en el prompt cuando alguna de sus keywords aparece en el texto
# cercano de la generacion en curso (ver prompts.find_relevant_lore_entries),
# a diferencia de plot/personajes/setting que siempre se incluyen completos.
# Esto es lo que permite mantener un elenco/mundo mucho mas grande del que
# cabria en el contexto de un modelo local si todo se incluyera siempre.
MAX_LORE_ENTRIES = 200
MAX_LORE_ENTRY_WORDS = 500

# Tipos de escritura seleccionables (aplican a toda la historia, no por
# capitulo). "" (sin seleccionar) significa usar solo el STYLE_GUIDE por
# defecto de prompts.py, sin enfasis adicional.
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
# instruccion adicional.
CHAPTER_PURPOSES = [
    "Apertura",
    "Escena climatica",
    "Final",
    "Epilogo",
]

_WORD_RE = re.compile(r"\b[\w'\-]+\b", re.UNICODE)


def count_words(text: str) -> int:
    """Cuenta palabras de forma consistente en toda la app."""
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


@dataclass
class Chapter:
    title: str = ""
    target_words: int = 2000
    content: str = ""
    # breve resumen (generado o manual) usado como contexto para el siguiente capitulo
    summary: str = ""
    # esquema/beat sheet de este capitulo (generado o manual), usado para guiar
    # la generacion de prosa antes de escribirla (workflow "outline-first")
    outline: str = ""
    # uno de CHAPTER_PURPOSES, o "" para un capitulo regular sin instruccion
    # narrativa adicional (ver prompts.build_chapter_purpose_instruction)
    purpose: str = ""
    # versiones anteriores de `content`, mas vieja primero, acotado a
    # MAX_CHAPTER_HISTORY (ver push_history()) -- permite recuperar el texto
    # de antes de un regenerar/refinar sin depender solo de la confirmacion
    # previa al sobrescribir
    history: List[str] = field(default_factory=list)

    def word_count(self) -> int:
        return count_words(self.content)

    def outline_words(self) -> int:
        return count_words(self.outline)

    def push_history(self) -> None:
        """
        Guarda el `content` actual en `history` antes de que algo lo
        sobrescriba (regenerar, refinar, o restaurar otra version). No hace
        nada si el contenido actual esta vacio -- no tiene sentido guardar
        "nada" como una version.
        """
        if not self.content.strip():
            return
        self.history.append(self.content)
        if len(self.history) > MAX_CHAPTER_HISTORY:
            self.history = self.history[-MAX_CHAPTER_HISTORY:]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Chapter":
        return Chapter(
            title=d.get("title", ""),
            target_words=int(d.get("target_words", 2000)),
            content=d.get("content", ""),
            summary=d.get("summary", ""),
            outline=d.get("outline", ""),
            purpose=d.get("purpose", ""),
            history=list(d.get("history", [])),
        )


@dataclass
class LoreEntry:
    """
    Una entrada del Lorebook / World Info: un personaje secundario, lugar,
    objeto u otro dato de mundo que no necesita repetirse en el bloque de
    contexto completo de cada capitulo. `keywords` es una lista separada por
    comas (texto libre, igual que el resto de los campos de este archivo);
    `prompts.find_relevant_lore_entries()` la parte y busca cada termino en
    el texto cercano de la generacion en curso para decidir si esta entrada
    es relevante ahora mismo.
    """
    name: str = ""
    keywords: str = ""
    text: str = ""

    def keyword_list(self) -> List[str]:
        return [k.strip() for k in self.keywords.split(",") if k.strip()]

    def word_count(self) -> int:
        return count_words(self.text)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "LoreEntry":
        return LoreEntry(
            name=d.get("name", ""),
            keywords=d.get("keywords", ""),
            text=d.get("text", ""),
        )


@dataclass
class Project:
    name: str = "Historia sin titulo"
    plot: str = ""
    characters: str = ""
    setting: str = ""
    chapters: List[Chapter] = field(default_factory=list)
    model_path: Optional[str] = None
    # Uno de WRITING_STYLES, o "" para no aplicar ningun enfasis adicional.
    writing_style: str = ""
    # Lorebook / World Info -- ver LoreEntry arriba.
    lore_entries: List[LoreEntry] = field(default_factory=list)

    # ---------------- validaciones ----------------
    def plot_words(self) -> int:
        return count_words(self.plot)

    def characters_words(self) -> int:
        return count_words(self.characters)

    def setting_words(self) -> int:
        return count_words(self.setting)

    def validate_inputs(self) -> List[str]:
        """Devuelve una lista de mensajes de error; vacia si todo es valido."""
        errors = []
        if self.plot_words() > MAX_PLOT_WORDS:
            errors.append(
                f"El plot tiene {self.plot_words():,} palabras (maximo {MAX_PLOT_WORDS:,})."
            )
        if self.characters_words() > MAX_CHARACTERS_WORDS:
            errors.append(
                f"Los personajes tienen {self.characters_words():,} palabras "
                f"(maximo {MAX_CHARACTERS_WORDS:,})."
            )
        if self.setting_words() > MAX_SETTING_WORDS:
            errors.append(
                f"El setting tiene {self.setting_words():,} palabras (maximo {MAX_SETTING_WORDS:,})."
            )
        if len(self.chapters) > MAX_CHAPTERS:
            errors.append(
                f"Hay {len(self.chapters)} capitulos (maximo {MAX_CHAPTERS})."
            )
        for i, ch in enumerate(self.chapters, start=1):
            if ch.target_words > MAX_WORDS_PER_CHAPTER:
                errors.append(
                    f"Capitulo {i}: objetivo de {ch.target_words:,} palabras "
                    f"excede el maximo ({MAX_WORDS_PER_CHAPTER:,})."
                )
            if ch.word_count() > MAX_WORDS_PER_CHAPTER:
                errors.append(
                    f"Capitulo {i}: el contenido generado tiene {ch.word_count():,} "
                    f"palabras y excede el maximo ({MAX_WORDS_PER_CHAPTER:,})."
                )
            if ch.outline_words() > MAX_OUTLINE_WORDS_PER_CHAPTER:
                errors.append(
                    f"Capitulo {i}: el esquema tiene {ch.outline_words():,} palabras "
                    f"(maximo {MAX_OUTLINE_WORDS_PER_CHAPTER:,})."
                )
        if len(self.lore_entries) > MAX_LORE_ENTRIES:
            errors.append(
                f"Hay {len(self.lore_entries)} entradas de lorebook (maximo {MAX_LORE_ENTRIES})."
            )
        for i, entry in enumerate(self.lore_entries, start=1):
            if entry.word_count() > MAX_LORE_ENTRY_WORDS:
                label = entry.name.strip() or f"entrada {i}"
                errors.append(
                    f"Lorebook '{label}': el texto tiene {entry.word_count():,} palabras "
                    f"(maximo {MAX_LORE_ENTRY_WORDS:,})."
                )
        return errors

    def can_add_chapter(self) -> bool:
        return len(self.chapters) < MAX_CHAPTERS

    def add_chapter(self, title: str = "", target_words: int = 2000, outline: str = "") -> Chapter:
        if not self.can_add_chapter():
            raise ValueError(f"No se pueden tener mas de {MAX_CHAPTERS} capitulos.")
        target_words = min(int(target_words), MAX_WORDS_PER_CHAPTER)
        chapter = Chapter(
            title=title or f"Capitulo {len(self.chapters) + 1}",
            target_words=target_words,
            outline=outline,
        )
        self.chapters.append(chapter)
        return chapter

    # ---------------- lorebook / world info ----------------
    def can_add_lore_entry(self) -> bool:
        return len(self.lore_entries) < MAX_LORE_ENTRIES

    def add_lore_entry(self, name: str = "", keywords: str = "", text: str = "") -> LoreEntry:
        if not self.can_add_lore_entry():
            raise ValueError(f"No se pueden tener mas de {MAX_LORE_ENTRIES} entradas de lorebook.")
        entry = LoreEntry(name=name, keywords=keywords, text=text)
        self.lore_entries.append(entry)
        return entry

    # ---------------- persistencia ----------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "plot": self.plot,
            "characters": self.characters,
            "setting": self.setting,
            "chapters": [c.to_dict() for c in self.chapters],
            "model_path": self.model_path,
            "writing_style": self.writing_style,
            "lore_entries": [e.to_dict() for e in self.lore_entries],
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "Project":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        proj = Project(
            name=data.get("name", "Historia sin titulo"),
            plot=data.get("plot", ""),
            characters=data.get("characters", ""),
            setting=data.get("setting", ""),
            model_path=data.get("model_path"),
            writing_style=data.get("writing_style", ""),
        )
        proj.chapters = [Chapter.from_dict(c) for c in data.get("chapters", [])]
        proj.lore_entries = [LoreEntry.from_dict(e) for e in data.get("lore_entries", [])]
        return proj
