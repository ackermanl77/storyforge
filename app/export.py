"""
Exportacion de la historia a .docx y .txt, respetando el marcado de
pensamientos internos (*texto*) como cursivas reales en Word.
"""
from __future__ import annotations

import re
from pathlib import Path

from .project import Project

_ITALIC_RE = re.compile(r"\*(.+?)\*")


def export_txt(project: Project, path: str | Path) -> None:
    path = Path(path)
    lines = [project.name, "=" * len(project.name), ""]
    for i, chapter in enumerate(project.chapters, start=1):
        lines.append(f"Chapter {i}: {chapter.title}")
        lines.append("-" * 40)
        lines.append(chapter.content)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def export_docx(project: Project, path: str | Path) -> None:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError(
            "El paquete 'python-docx' no esta instalado. "
            "Instala las dependencias con: pip install -r requirements.txt"
        ) from exc

    doc = Document()
    doc.add_heading(project.name, level=0)

    for i, chapter in enumerate(project.chapters, start=1):
        doc.add_heading(f"Chapter {i}: {chapter.title}", level=1)
        for paragraph_text in chapter.content.split("\n\n"):
            paragraph_text = paragraph_text.strip()
            if not paragraph_text:
                continue
            p = doc.add_paragraph()
            _add_runs_with_italics(p, paragraph_text)

    doc.save(str(path))


def _add_runs_with_italics(paragraph, text: str) -> None:
    """Divide el texto por *marcas de cursiva* y agrega runs con el formato correcto."""
    pos = 0
    for match in _ITALIC_RE.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos:match.start()])
        run = paragraph.add_run(match.group(1))
        run.italic = True
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])
