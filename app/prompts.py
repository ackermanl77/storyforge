"""
Plantillas de prompts para el motor de generacion local.
Toda la salida narrativa se pide en ingles, con convenciones de formato claras
para pensamientos internos, dialogo y cambios de punto de vista.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from .project import Project, Chapter, count_words

STYLE_GUIDE = """\
FORMATTING RULES (follow strictly):
- Third-person narration is the default body text: plain prose, past tense.
- A character's internal thoughts (direct interior monologue) must be wrapped
  in *asterisks*, written in first person, present tense, e.g. *I can't believe this is happening.*
- If a character addresses the reader or another character directly in
  second person ("you"), use it only inside dialogue, in quotation marks.
- Dialogue uses standard double quotes and a new paragraph per speaker.
- Do not repeat the same descriptive word or phrase more than twice in the
  same scene; vary sentence length and structure.
- Do not include any meta-commentary, author notes, or explanations outside
  the story text itself.
- Write only in English, regardless of the language of the notes you receive.
"""


def _trim_words(text: str, max_words: int) -> str:
    """Conserva el INICIO del texto (para plot/personajes/setting/resumenes:
    lo mas importante suele estar planteado al principio)."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [...]"


def _trim_words_tail(text: str, max_words: int) -> str:
    """Conserva el FINAL del texto. Para continuar un capitulo ya empezado
    necesitamos lo ultimo que se escribio, no el principio del capitulo."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return "[...] " + " ".join(words[-max_words:])


def build_context_block(project: Project, max_plot_words: int = 1200,
                         max_characters_words: int = 600,
                         max_setting_words: int = 600) -> str:
    """
    Condensa plot/personajes/setting a un tamano que quepa en el contexto de
    un modelo local (que suele ser mucho mas chico que el limite de entrada
    de la app). Si el usuario escribio menos que el limite, se usa completo.
    """
    plot = _trim_words(project.plot.strip(), max_plot_words)
    characters = _trim_words(project.characters.strip(), max_characters_words)
    setting = _trim_words(project.setting.strip(), max_setting_words)
    return (
        f"STORY PLOT / PREMISE:\n{plot}\n\n"
        f"CHARACTERS:\n{characters}\n\n"
        f"SETTING:\n{setting}\n"
    )


def build_previous_context(project: Project, upto_index: int, max_words: int = 500) -> str:
    """Resumen breve de los capitulos anteriores para dar continuidad."""
    parts = []
    for i in range(upto_index):
        ch = project.chapters[i]
        summary = ch.summary.strip() or _trim_words(ch.content.strip(), 200)
        if summary:
            parts.append(f"Chapter {i + 1} ({ch.title}) summary: {summary}")
    if not parts:
        return "This is the first chapter of the story."
    text = "\n".join(parts)
    return _trim_words(text, max_words)


def build_story_outline_overview(project: Project) -> str:
    """
    Lista compacta de titulos de todos los capitulos planeados, para que el
    modelo tenga conciencia del arco completo de la historia sin gastar
    mucho contexto (solo titulos, no los beats completos de cada uno).
    """
    titles = [ch.title.strip() for ch in project.chapters if ch.title.strip()]
    if not titles:
        return ""
    lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return f"STORY OUTLINE OVERVIEW (all planned chapters, for context only):\n{lines}\n"


def build_chapter_system_prompt(
    project: Project,
    chapter_index: int,
    max_plot_words: int = 1200,
    max_characters_words: int = 600,
    max_setting_words: int = 600,
    max_previous_words: int = 500,
) -> str:
    """
    Construye el prompt de sistema para un capitulo. Los parametros max_*
    controlan cuanto contexto se incluye; el motor de generacion los reduce
    progresivamente si el prompt no cabe en la ventana de contexto del
    modelo cargado (ver engine.CONTEXT_BUDGET_LEVELS).
    """
    context = build_context_block(project, max_plot_words, max_characters_words, max_setting_words)
    previous = build_previous_context(project, chapter_index, max_previous_words)
    chapter = project.chapters[chapter_index]
    overview = build_story_outline_overview(project)
    outline_block = ""
    if chapter.outline.strip():
        outline_block = (
            "THIS CHAPTER'S OUTLINE (follow these beats in order; you may add "
            "sensory detail, dialogue and internal thoughts, but do not skip or "
            f"reorder the events described):\n{chapter.outline.strip()}\n\n"
        )
    return (
        "You are a skilled fiction writer producing one chapter of a longer "
        "story for an adult creative-writing project. Stay fully consistent "
        "with the plot, characters and setting provided. Do not break "
        "character or add disclaimers.\n\n"
        f"{context}\n"
        f"{overview}\n"
        f"PROGRESS SO FAR:\n{previous}\n\n"
        f"{outline_block}"
        f"{STYLE_GUIDE}\n"
        f"Now write Chapter {chapter_index + 1}, titled \"{chapter.title}\". "
        f"Target length: approximately {chapter.target_words} words. "
    )


_CHAPTER_HEADER_RE = re.compile(r"(?im)^\s*chapter\s+(\d+)\s*[:.\-]\s*(.*)$")


def build_outline_prompt(
    project: Project,
    num_chapters: int,
    max_plot_words: int = 1200,
    max_characters_words: int = 600,
    max_setting_words: int = 600,
) -> str:
    """
    Prompt para generar un esquema (beat sheet) de toda la historia ANTES de
    escribir prosa. Genera esto primero mejora mucho la coherencia de una
    historia de varios capitulos frente a improvisar capitulo por capitulo.
    """
    context = build_context_block(project, max_plot_words, max_characters_words, max_setting_words)
    return (
        "You are a fiction editor planning a story before it is written. Based "
        "only on the material below, create a chapter-by-chapter outline for a "
        f"story with EXACTLY {num_chapters} chapters.\n\n"
        f"{context}\n"
        "For each chapter, output exactly this format (plain text, no markdown):\n\n"
        "Chapter 1: <short chapter title>\n"
        "<2 to 4 sentences describing the key events, turning points and "
        "emotional beats of this chapter>\n\n"
        "Chapter 2: <short chapter title>\n"
        "<...>\n\n"
        f"Continue this exact pattern for all {num_chapters} chapters, in order, "
        "covering a complete story arc with a clear beginning, rising action, "
        "climax and resolution across the available chapters. Do not write the "
        "chapters themselves, only the outline. Do not add any text before "
        "\"Chapter 1\" or after the last chapter's outline."
    )


def parse_outline_response(text: str, expected_chapters: int) -> List[Tuple[str, str]]:
    """
    Extrae pares (titulo, beats) de la respuesta del modelo a
    build_outline_prompt. Tolera variaciones menores de formato
    ("Chapter 1:", "Chapter 1.", etc.). Si el modelo no siguio el formato en
    absoluto, devuelve todo el texto como un unico capitulo (mejor que nada).
    """
    matches = list(_CHAPTER_HEADER_RE.finditer(text))
    results: List[Tuple[str, str]] = []
    for i, match in enumerate(matches):
        title = match.group(2).strip() or f"Chapter {match.group(1)}"
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        results.append((title, body))
    if not results:
        stripped = text.strip()
        return [("Chapter 1", stripped)] if stripped else []
    return results[:expected_chapters]


def build_continuation_prompt(already_written: str, remaining_words: int, tail_words: int = 400) -> str:
    """
    Prompt para pedir que el modelo continue un capitulo ya empezado. Usa el
    FINAL de lo ya escrito (no el inicio) para que el modelo sepa exactamente
    donde retomar la escena.
    """
    tail = _trim_words_tail(already_written, tail_words)
    return (
        "Continue the same chapter directly from where it left off. Do not "
        "repeat previous sentences, do not restart the scene, and do not "
        "summarize what already happened — just keep writing the story.\n\n"
        f"...(end of what has been written so far)\n{tail}\n\n"
        f"Continue for about {remaining_words} more words, keeping the same "
        f"tone, characters and formatting rules."
    )
