"""
Matriz de la historia (F18): una fila por capitulo y una columna por
personaje o hilo, con cuantas veces aparece cada uno en el texto del capitulo
-- para ver de un vistazo quien desaparece durante cinco capitulos o que hilo
quedo sin cerrar.

Columnas:
- los personajes de la pestana Personajes: las lineas que empiezan con un
  nombre seguido de ":" , " - " o " — " (tambien "- Nombre:" y "**Nombre**"),
  buscados por su nombre completo y por su primer nombre;
- las entradas activas del lorebook, buscadas por su nombre y sus palabras
  clave (un hilo de la trama puede ser una entrada con sus palabras clave).

Cada celda cuenta las menciones en el texto del capitulo. Si el capitulo
todavia no tiene texto, cuenta las de su esquema y su resumen, y la celda se
marca como planeada (para distinguir lo escrito de lo previsto).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List

from .project import Project

_CHARACTER_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*|__)?([A-ZÁÉÍÓÚÑÜ][\w'’.-]*(?:\s+[A-ZÁÉÍÓÚÑÜ][\w'’.-]*){0,3})(?:\*\*|__)?\s*(?::|\s[-–—]\s|,)",
    re.MULTILINE,
)
MAX_COLUMNS = 40


@dataclass
class Column:
    label: str
    terms: List[str]
    kind: str  # "character" | "lore"


@dataclass
class Row:
    title: str
    counts: List[int]
    planned: bool = False  # sin texto todavia: se contaron el esquema y el resumen


@dataclass
class StoryMatrix:
    columns: List[Column] = field(default_factory=list)
    rows: List[Row] = field(default_factory=list)

    def to_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Capítulo", *[c.label for c in self.columns]])
        for row in self.rows:
            writer.writerow([row.title + (" (esquema)" if row.planned else ""), *row.counts])
        return buffer.getvalue()

    def gaps(self, minimum_chapters: int = 3) -> Dict[str, int]:
        """Columnas ausentes en `minimum_chapters` o mas capitulos seguidos tras aparecer: {etiqueta: racha}."""
        out = {}
        for index, column in enumerate(self.columns):
            seen, streak, longest = False, 0, 0
            for row in self.rows:
                if row.counts[index]:
                    seen, streak = True, 0
                elif seen:
                    streak += 1
                    longest = max(longest, streak)
            if longest >= minimum_chapters:
                out[column.label] = longest
        return out


def character_names(characters_text: str) -> List[str]:
    names = []
    for match in _CHARACTER_LINE.finditer(characters_text or ""):
        name = match.group(1).strip(" .")
        if len(name) >= 2 and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    return names


def _columns(project: Project) -> List[Column]:
    columns: List[Column] = []
    seen = set()
    for name in character_names(project.characters):
        terms = [name]
        first = name.split()[0]
        if first != name and len(first) >= 3:
            terms.append(first)
        columns.append(Column(name, terms, "character"))
        seen.add(name.lower())
    for entry in project.all_lore_entries():
        label = entry.name.strip()
        if not entry.enabled or not label or label.lower() in seen:
            continue
        terms = list(dict.fromkeys([label, *entry.keyword_list()]))
        columns.append(Column(label, terms, "lore"))
        seen.add(label.lower())
    return columns[:MAX_COLUMNS]


def _count(text: str, terms: List[str]) -> int:
    if not text:
        return 0
    spans = set()
    for term in sorted(terms, key=len, reverse=True):
        for match in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
            if not any(start <= match.start() < end for start, end in spans):
                spans.add((match.start(), match.end()))
    return len(spans)


def build_story_matrix(project: Project) -> StoryMatrix:
    columns = _columns(project)
    rows = []
    for index, chapter in enumerate(project.chapters, start=1):
        text, planned = chapter.content, False
        if not text.strip():
            text, planned = f"{chapter.outline}\n{chapter.summary}", True
        title = chapter.title.strip() or f"Capítulo {index}"
        rows.append(Row(f"{index}. {title}", [_count(text, column.terms) for column in columns], planned))
    return StoryMatrix(columns, rows)
