"""
Importar un manuscrito (F16): un .docx, .md o .txt se parte en capitulos por
sus encabezados y se convierte en un proyecto nuevo de StoryForge.

Como se encuentran los capitulos:

- .docx: los parrafos con estilo de titulo ("Heading 1", "Heading 2"... o
  "Título 1" en un Word en espanol). Si el documento no usa estilos de
  titulo, se buscan lineas que parezcan encabezados (abajo).
- .md: los encabezados "#", "##"...
- .txt (y cualquier documento sin estilos): las lineas que parecen un
  encabezado de capitulo -- "Chapter 1", "CAPÍTULO IV", "Capítulo tres: El
  faro", "Prólogo", "Epilogue", "Parte 2"...

Con varios niveles de titulo se elige el que parte el texto en capitulos: el
nivel mas alto que aparece mas de una vez (un unico "# Titulo del libro"
arriba de varios "## Capitulo" pasa a ser el nombre del proyecto). Los
niveles mas bajos quedan como lineas dentro del capitulo.

El texto antes del primer encabezado se descarta si es corto (portada,
titulo) y se conserva como un capitulo "Inicio" si no. La cursiva y la
negrita de Word se guardan como *texto* y **texto**, la marca que el resto de
la app (y la exportacion) ya entiende.

Un proyecto tiene como mucho MAX_CHAPTERS capitulos: si el manuscrito tiene
mas, las secciones sobrantes se agregan al ultimo capitulo (con su
encabezado como linea), de modo que no se pierde texto, y se avisa.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .project import MAX_CHAPTERS, MAX_WORDS_PER_CHAPTER, Chapter, Project, count_words

SUPPORTED_SUFFIXES = (".docx", ".md", ".markdown", ".txt")
MAX_MANUSCRIPT_BYTES = 30 * 1024 * 1024
# Texto antes del primer encabezado mas corto que esto: portada / titulo, se descarta.
FRONT_MATTER_WORDS = 40
DEFAULT_TARGET_WORDS = 2000

_NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|"
    r"trece|catorce|quince|dieciséis|dieciseis|diecisiete|dieciocho|diecinueve|veinte|primero|segundo|tercero"
)
_HEADING_LINE = re.compile(
    rf"^\s*(?:(?:chapter|cap[ií]tulo|part|parte|book|libro)\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b[\s.:\-–—]*.{{0,80}}"
    rf"|(?:prologue|pr[oó]logo|epilogue|ep[ií]logo|interlude|interludio)\b[\s.:\-–—]*.{{0,80}})\s*$",
    re.IGNORECASE,
)
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass
class Section:
    title: str
    lines: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


@dataclass
class Manuscript:
    title: str
    sections: List[Section]
    merged: int = 0  # secciones agregadas al ultimo capitulo por el limite de capitulos

    def to_project(self) -> Project:
        return manuscript_to_project(self)


# ---------------- lectura por formato ----------------

def _docx_paragraphs(content: bytes) -> List[Tuple[Optional[int], str]]:
    """(nivel de titulo o None, texto con *cursiva*/**negrita**) por parrafo de un .docx."""
    from docx import Document

    document = Document(io.BytesIO(content))
    out = []
    for paragraph in document.paragraphs:
        style = (paragraph.style.name if paragraph.style is not None else "") or ""
        level = None
        match = re.match(r"^(?:heading|t[ií]tulo)\s*(\d)$", style.strip(), re.IGNORECASE)
        if match:
            level = int(match.group(1))
        elif style.strip().lower() in ("title", "título", "titulo"):
            level = 0
        if level is not None:
            out.append((level, paragraph.text.strip()))
            continue
        # Consecutive runs with the same formatting are joined first, so "*a**b*" can't appear.
        groups: List[List] = []
        for run in paragraph.runs:
            if not run.text:
                continue
            key = (bool(run.bold), bool(run.italic))
            if groups and groups[-1][0] == key:
                groups[-1][1] += run.text
            else:
                groups.append([key, run.text])
        parts = []
        for (bold, italic), text in groups:
            marker = "***" if bold and italic else "**" if bold else "*" if italic else ""
            stripped = text.strip()
            if marker and stripped:
                lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
                text = f"{lead}{marker}{stripped}{marker}{trail}"
            parts.append(text)
        out.append((None, "".join(parts)))
    return out


def _markdown_lines(text: str) -> List[Tuple[Optional[int], str]]:
    out = []
    for line in text.splitlines():
        match = _MD_HEADING.match(line)
        out.append((len(match.group(1)), match.group(2).strip()) if match else (None, line.rstrip()))
    return out


def _plain_lines(text: str) -> List[Tuple[Optional[int], str]]:
    return [(1 if _HEADING_LINE.match(line) else None, line.rstrip() if not _HEADING_LINE.match(line) else line.strip())
            for line in text.splitlines()]


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", "replace")


# ---------------- partir en capitulos ----------------

def _chapter_level(lines: List[Tuple[Optional[int], str]]) -> Optional[int]:
    levels = [level for level, text in lines if level is not None and text]
    if not levels:
        return None
    for level in sorted(set(levels)):
        if levels.count(level) > 1:
            return level
    return max(levels)  # un solo encabezado por nivel: el mas bajo parte el texto


def split_lines(lines: List[Tuple[Optional[int], str]], fallback_title: str) -> Tuple[str, List[Section]]:
    """(titulo del libro, secciones) a partir de (nivel, texto) por linea."""
    level = _chapter_level(lines)
    if level is None and any(_HEADING_LINE.match(text or "") for _lvl, text in lines):
        lines = [(1 if _HEADING_LINE.match(text or "") else None, text) for _lvl, text in lines]
        level = 1
    title = fallback_title
    sections: List[Section] = []
    lead: List[str] = []
    for line_level, text in lines:
        if line_level is not None and line_level < (level if level is not None else 0) and text:
            if not sections and title == fallback_title:
                title = text  # un titulo por encima de los capitulos: el nombre del libro
            else:
                (sections[-1].lines if sections else lead).append(text)
            continue
        if level is not None and line_level == level and text:
            sections.append(Section(text))
            continue
        if line_level is not None and text:  # un subtitulo dentro de un capitulo
            text = text.strip()
        (sections[-1].lines if sections else lead).append(text)
    lead_text = "\n".join(lead).strip()
    if not sections:
        return title, [Section(title, lead)] if lead_text else []
    if count_words(lead_text) > FRONT_MATTER_WORDS:
        sections.insert(0, Section("Inicio", lead))
    elif lead_text and title == fallback_title:
        first_line = next((line.strip() for line in lead if line.strip()), "")
        if 0 < len(first_line) <= 120:
            title = first_line
    return title, sections


def read_manuscript(content: bytes, filename: str) -> Manuscript:
    """Lee un manuscrito (.docx/.md/.txt) y lo parte en capitulos. ValueError si no se puede."""
    from . import strings_es as S

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(S.MANUSCRITO_FORMATO_NO_SOPORTADO)
    if len(content) > MAX_MANUSCRIPT_BYTES:
        raise ValueError(S.MANUSCRITO_DEMASIADO_GRANDE)
    stem = Path(filename).stem.replace("_", " ").strip() or "Manuscrito"
    if suffix == ".docx":
        try:
            lines = _docx_paragraphs(content)
        except Exception as exc:  # noqa: BLE001 - python-docx: zip/XML errors of every kind
            raise ValueError(S.MANUSCRITO_DOCX_ILEGIBLE.format(exc=exc)) from exc
    elif suffix in (".md", ".markdown"):
        lines = _markdown_lines(_decode_text(content))
    else:
        lines = _plain_lines(_decode_text(content))
    title, sections = split_lines(lines, stem)
    sections = [section for section in sections if section.text or section.title]
    if not any(section.text for section in sections):
        raise ValueError(S.MANUSCRITO_VACIO)
    merged = 0
    if len(sections) > MAX_CHAPTERS:
        last = sections[MAX_CHAPTERS - 1]
        for extra in sections[MAX_CHAPTERS:]:
            last.lines += ["", extra.title, ""] + extra.lines
            merged += 1
        sections = sections[:MAX_CHAPTERS]
    return Manuscript(title=title[:120], sections=sections, merged=merged)


def _clean_content(text: str) -> str:
    # Parrafos separados por una linea en blanco, como escribe la app; sin mas de una linea vacia seguida.
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()


def manuscript_to_project(manuscript: Manuscript) -> Project:
    project = Project(name=manuscript.title or "Manuscrito")
    for section in manuscript.sections:
        content = _clean_content(section.text)
        words = count_words(content)
        target = min(MAX_WORDS_PER_CHAPTER, max(DEFAULT_TARGET_WORDS, (words + 99) // 100 * 100))
        project.chapters.append(Chapter(title=section.title[:200] or f"Capítulo {len(project.chapters) + 1}",
                                        target_words=target, content=content))
    return project


def import_manuscript(path: str | Path) -> Manuscript:
    path = Path(path)
    return read_manuscript(path.read_bytes(), path.name)
