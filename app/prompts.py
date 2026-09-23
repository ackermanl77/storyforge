"""
Plantillas de prompts para el motor de generacion local.
Toda la salida narrativa se pide en ingles, con convenciones de formato claras
para pensamientos internos, dialogo y cambios de punto de vista.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from .project import Chapter, LoreEntry, Project

# Instruccion en ingles (la salida siempre se pide en ingles, ver STYLE_GUIDE
# abajo) para cada valor posible de project.writing_style (project.WRITING_
# STYLES). Se agrega como enfasis adicional encima del STYLE_GUIDE por
# defecto, no lo reemplaza -- las reglas de formato (cursivas, dialogo, etc.)
# siguen aplicando sin importar el tipo de escritura elegido.
WRITING_STYLE_INSTRUCTIONS = {
    "Narrativa": (
        "Favor a strong narrative drive: keep the plot moving with clear "
        "cause-and-effect between events and a forward-moving pace."
    ),
    "Descriptiva": (
        "Favor rich, sensory description: spend more time on setting, "
        "atmosphere and physical detail, even where it slows the pace."
    ),
    "Creativa": (
        "Favor inventive, literary prose: unusual imagery, fresh metaphor, "
        "and stylistic risk-taking over conventional phrasing."
    ),
    "Dialogo": (
        "Favor dialogue-driven scenes: let characters reveal plot and "
        "personality mainly through spoken exchanges, with minimal narration "
        "between lines."
    ),
    "Poetica": (
        "Favor lyrical, rhythmic prose: pay attention to the music of the "
        "language, figurative imagery, and evocative word choice."
    ),
    "Accion rapida": (
        "Favor fast pacing: short, punchy sentences, minimal introspection, "
        "and high momentum, especially during action."
    ),
}


def build_writing_style_instruction(project: Project) -> str:
    """
    Linea de enfasis de estilo adicional segun project.writing_style. Vacio
    si no se selecciono ninguno (o el valor guardado no coincide con ningun
    tipo conocido, p.ej. un proyecto viejo) -- en ese caso solo aplica el
    STYLE_GUIDE por defecto, sin enfasis extra.
    """
    instruction = WRITING_STYLE_INSTRUCTIONS.get(project.writing_style.strip())
    if not instruction:
        return ""
    return f"WRITING STYLE EMPHASIS: {instruction}\n\n"


# Instruccion en ingles para cada valor posible de chapter.purpose (project.
# CHAPTER_PURPOSES). A diferencia de WRITING_STYLE_INSTRUCTIONS (aplica a
# toda la historia), esto es especifico de UN capitulo: le dice al modelo
# que rol narrativo cumple este capitulo dentro del arco completo.
CHAPTER_PURPOSE_INSTRUCTIONS = {
    "Apertura": (
        "This is the OPENING chapter of the story. Establish the setting, "
        "introduce the protagonist and the normal world before it's "
        "disrupted, and end with (or lead directly into) the inciting "
        "incident that sets the story in motion. Do not resolve anything yet."
    ),
    "Escena climatica": (
        "This is the story's CLIMAX. Build steadily toward the central "
        "conflict's decisive confrontation or turning point, raise the "
        "stakes and tension throughout, and deliver a genuine, consequential "
        "turning point by the end of the chapter -- not a minor skirmish."
    ),
    "Final": (
        "This is the story's FINAL chapter. Resolve the central conflict, "
        "show the direct consequences of the climax, and give the main "
        "character arc(s) a clear, earned conclusion. Do not introduce new "
        "unresolved plot threads."
    ),
    "Epilogo": (
        "This is an EPILOGUE. It takes place after the main story's events "
        "are already resolved -- skip ahead in time if appropriate. Show the "
        "lasting aftermath and where the characters end up, in a shorter, "
        "more reflective register than a regular chapter. Do not introduce "
        "new conflict."
    ),
}


def build_chapter_purpose_instruction(chapter: Chapter) -> str:
    """
    Linea de instruccion adicional segun chapter.purpose. Vacio si el
    capitulo no tiene uno asignado (o el valor guardado no coincide con
    ningun proposito conocido) -- en ese caso se trata como un capitulo
    regular, sin instruccion de rol narrativo.
    """
    instruction = CHAPTER_PURPOSE_INSTRUCTIONS.get(chapter.purpose.strip())
    if not instruction:
        return ""
    return f"CHAPTER PURPOSE: {instruction}\n\n"


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


def find_relevant_lore_entries(entries: List[LoreEntry], scan_text: str) -> List[LoreEntry]:
    """
    Lorebook / World Info matcher: devuelve las entradas cuyo keyword (al
    menos uno de LoreEntry.keyword_list()) aparece como palabra/frase
    completa (sin distinguir mayusculas/minusculas) en `scan_text` -- el
    texto NARRATIVAMENTE CERCANO a la generacion en curso (p.ej. el esquema
    del capitulo y el resumen de los capitulos anteriores), no el plot
    completo. A diferencia de plot/personajes/setting (siempre incluidos
    enteros via build_context_block), esto deja mantener un elenco o mundo
    mucho mas grande del que cabria en el contexto de un modelo local si
    cada entrada se incluyera siempre, incluso cuando no es relevante ahora.
    Conserva el orden de `entries` (orden de aparicion en el lorebook).
    """
    if not scan_text or not scan_text.strip():
        return []
    matches: List[LoreEntry] = []
    for entry in entries:
        for keyword in entry.keyword_list():
            pattern = r"(?i)\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, scan_text):
                matches.append(entry)
                break
    return matches


def build_lorebook_block(
    entries: List[LoreEntry], scan_text: str, max_entry_words: int = 200, max_entries: int = 8,
) -> str:
    """
    Bloque de contexto con SOLO las entradas del lorebook relevantes a
    `scan_text` (ver find_relevant_lore_entries) -- vacio si ninguna
    coincide, para no gastar contexto en absoluto cuando el lorebook no
    aplica a esta seccion. `max_entries` acota cuantas entradas coincidentes
    como maximo se incluyen (por si muchas coinciden a la vez); cada una se
    recorta a `max_entry_words`, igual que el resto de los campos de este
    archivo.
    """
    matched = find_relevant_lore_entries(entries, scan_text)[:max_entries]
    if not matched:
        return ""
    lines = []
    for entry in matched:
        name = entry.name.strip() or "(sin nombre)"
        text = _trim_words(entry.text.strip(), max_entry_words)
        lines.append(f"{name}: {text}")
    return "RELEVANT WORLD INFO (only what applies to this part of the story):\n" + "\n".join(lines) + "\n\n"


def build_chapter_system_prompt(
    project: Project,
    chapter_index: int,
    max_plot_words: int = 1200,
    max_characters_words: int = 600,
    max_setting_words: int = 600,
    max_previous_words: int = 500,
    max_outline_words: int = 400,
    max_lore_words: int = 200,
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
        # chapter.outline no tiene un limite propio en project.py (es texto
        # libre editable en la pestana Esquema): a diferencia de plot/
        # personajes/setting, sin este recorte un esquema inusualmente largo
        # quedaria fuera del mecanismo de reduccion de contexto por completo.
        outline_text = _trim_words(chapter.outline.strip(), max_outline_words)
        outline_block = (
            "THIS CHAPTER'S OUTLINE (follow these beats in order; you may add "
            "sensory detail, dialogue and internal thoughts, but do not skip or "
            f"reorder the events described):\n{outline_text}\n\n"
        )
    # Lorebook: se escanean el esquema de ESTE capitulo y el resumen de los
    # capitulos anteriores -- el texto narrativamente mas cercano a lo que se
    # esta por escribir -- en busca de las keywords de cada entrada, en vez
    # de incluir el lorebook completo (que podria no caber en absoluto en el
    # contexto de un modelo local con un elenco/mundo grande).
    lore_scan_text = f"{chapter.outline}\n{previous}"
    lore_block = build_lorebook_block(project.lore_entries, lore_scan_text, max_entry_words=max_lore_words)
    style_emphasis = build_writing_style_instruction(project)
    purpose_instruction = build_chapter_purpose_instruction(chapter)
    return (
        "You are a skilled fiction writer producing one chapter of a longer "
        "story for an adult creative-writing project. Stay fully consistent "
        "with the plot, characters and setting provided. Do not break "
        "character or add disclaimers.\n\n"
        f"{context}\n"
        f"{overview}\n"
        f"PROGRESS SO FAR:\n{previous}\n\n"
        f"{outline_block}"
        f"{lore_block}"
        f"{purpose_instruction}"
        f"{style_emphasis}"
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
    style_emphasis = build_writing_style_instruction(project)
    return (
        "You are a fiction editor planning a story before it is written. Based "
        "only on the material below, create a chapter-by-chapter outline for a "
        f"story with EXACTLY {num_chapters} chapters.\n\n"
        f"{context}\n"
        f"{style_emphasis}"
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


# Etiquetas en ingles para cada campo que puede expandirse con IA (ver
# build_expand_field_prompt / engine.LocalStoryEngine.expand_field). Las
# claves coinciden con las que usa app/gui.py al llamar a esa funcion.
EXPAND_FIELD_LABELS = {
    "plot": "story plot / premise",
    "characters": "cast of characters",
    "setting": "setting",
}


def build_expand_field_prompt(field_key: str, text: str, max_words: int) -> str:
    """
    Prompt para que el modelo tome una nota corta (p.ej. una idea de plot en
    una linea) y la desarrolle en un texto mas completo, sin inventar una
    historia distinta a la que el usuario ya planteo. `field_key` es una
    clave de EXPAND_FIELD_LABELS ("plot"/"characters"/"setting").
    """
    label = EXPAND_FIELD_LABELS.get(field_key, field_key)
    return (
        f"You are a fiction editor helping an author flesh out their {label} "
        "notes for a story they are planning. Expand the notes below into a "
        "fuller, well-organized version in the same spirit — do not change "
        "the core ideas, characters, or setting already implied, only "
        "develop and clarify them with more detail. Do not start writing the "
        "story itself, only the notes. Do not add meta-commentary or "
        f"explanations outside the notes themselves. Keep it under {max_words} words.\n\n"
        f"CURRENT {label.upper()} NOTES:\n{text.strip()}\n\n"
        "Expanded notes:"
    )


def build_refine_chapter_prompt(
    project: Project,
    chapter_index: int,
    instruction: str,
    max_content_words: int = 3000,
) -> str:
    """
    Prompt para revisar un capitulo YA generado segun una instruccion del
    usuario (p.ej. "hazlo mas oscuro", "acorta la escena del mercado"), en
    vez de generar texto nuevo desde cero. Mantiene el STYLE_GUIDE y el
    enfasis de writing_style del proyecto (las reglas de formato siguen
    aplicando a la version revisada).
    """
    chapter = project.chapters[chapter_index]
    # A diferencia de build_continuation_prompt (que solo necesita el FINAL
    # de lo escrito para saber donde retomar), una revision idealmente
    # necesita el capitulo COMPLETO -- por eso se conserva el inicio
    # (_trim_words) en vez de la cola si no cabe entero, como el resto de
    # los campos de contexto de este archivo.
    content = _trim_words(chapter.content.strip(), max_content_words)
    style_emphasis = build_writing_style_instruction(project)
    return (
        "You are editing an already-written chapter of a longer story, per "
        "the author's instruction below. Rewrite the chapter applying that "
        "instruction, keeping the plot events, characters, and overall "
        "length roughly the same unless the instruction says otherwise. "
        "Output only the revised chapter text, nothing else — no notes, no "
        "commentary, no explanation of what you changed.\n\n"
        f"EDITING INSTRUCTION: {instruction.strip()}\n\n"
        f"{style_emphasis}"
        f"{STYLE_GUIDE}\n"
        f"CURRENT CHAPTER TEXT:\n{content}\n\n"
        "Revised chapter:"
    )
