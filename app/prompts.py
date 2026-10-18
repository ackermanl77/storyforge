"""
Plantillas de prompts para el motor de generacion local.
Toda la salida narrativa se pide en ingles, con convenciones de formato claras
para pensamientos internos, dialogo y cambios de punto de vista.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from . import strings_es as S
from .project import Chapter, LoreEntry, Project


@dataclass
class ChatPrompt:
    """
    Un prompt en dos formas equivalentes (ver app/chat_format.py):

    - `system`/`user`/`prefill`: para modelos instruct, que se renderizan con
      la plantilla de chat del modelo (turno de sistema, turno de usuario y,
      opcionalmente, el comienzo de la respuesta del asistente -- `prefill`
      -- que el modelo simplemente continua).
    - `raw`: el prompt de completion cruda de siempre, para modelos base o
      cuando se elige "Sin plantilla" en la pestana Modelo.
    """
    system: str
    user: str
    prefill: str = ""
    raw: str = ""

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
    from .story_settings import build_story_settings_block

    settings = build_story_settings_block(project)
    instruction = WRITING_STYLE_INSTRUCTIONS.get(project.writing_style.strip())
    if not instruction:
        return settings
    return f"{settings}WRITING STYLE EMPHASIS: {instruction}\n\n"


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


_DEFAULT_POV_RULE = "- Third-person narration is the default body text: plain prose, past tense.\n"
_SECOND_PERSON_RULE = (
    "- If a character addresses the reader or another character directly in\n"
    "  second person (\"you\"), use it only inside dialogue, in quotation marks.\n"
)


def style_guide_for(project: Project) -> str:
    """STYLE_GUIDE, salvo que el proyecto elija un punto de vista: entonces la regla
    "tercera persona por defecto" (y, en segunda persona, la que limita el "you" al
    dialogo) cede ante el de STORY SETTINGS, en vez de contradecirlo."""
    from .story_settings import pov_short

    pov = pov_short(project)
    if not pov:
        return STYLE_GUIDE
    guide = STYLE_GUIDE.replace(
        _DEFAULT_POV_RULE, f"- Narration is in {pov}, as set in STORY SETTINGS: plain prose.\n")
    if pov.startswith("second person"):
        guide = guide.replace(_SECOND_PERSON_RULE, "")
    return guide


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


_NON_SPACE_RE = re.compile(r"\S+")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?\"”])\s+")


def tail_preserving_format(text: str, max_words: int) -> str:
    """
    Como _trim_words_tail, pero SIN reescribir los espacios: conserva los
    saltos de parrafo originales y no agrega "[...]". Es el texto con el que
    empieza la respuesta del asistente al continuar un capitulo (el modelo
    lo sigue escribiendo tal cual), asi que tiene que verse como prosa
    normal. Si puede, empieza en un limite de parrafo u oracion cercano en
    vez de a mitad de una frase.
    """
    text = (text or "").rstrip()
    if max_words <= 0:
        return ""
    matches = list(_NON_SPACE_RE.finditer(text))
    if len(matches) <= max_words:
        return text.lstrip()
    start = matches[-max_words].start()
    window = (len(text) - start) // 3
    para = text.find("\n\n", start)
    if para != -1 and para - start <= window:
        start = para
    else:
        sentence = _SENTENCE_BREAK_RE.search(text, start)
        if sentence and sentence.start() - start <= window:
            start = sentence.end()
    return text[start:].lstrip()


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


HANDOFF_MAX_WORDS = 150  # final literal del capitulo anterior incluido como "punto de relevo"
_MISSING_SUMMARY_EXCERPT_WORDS = 120


def _handoff_words(max_words: int) -> int:
    """Cuantas palabras del FINAL del capitulo anterior incluir, segun el
    presupuesto: ~1/4 del total, entre 40 y HANDOFF_MAX_WORDS."""
    return min(HANDOFF_MAX_WORDS, max(40, max_words // 4))


def build_previous_context(project: Project, upto_index: int, max_words: int = 500) -> str:
    """
    Contexto de continuidad con los capitulos anteriores a `upto_index`.

    Se arma del MAS RECIENTE hacia atras (antes se unian todos en orden y se
    recortaba conservando el principio, asi que desde el capitulo ~4 el
    capitulo inmediatamente anterior -- justo el que mas importa -- quedaba
    fuera en todos los niveles de presupuesto):

    1. Siempre: el resumen del capitulo N-1 y las ultimas palabras de su
       texto (el punto exacto donde retomar la historia).
    2. Con el presupuesto que quede: los resumenes de los capitulos
       anteriores, del mas nuevo al mas viejo.
    3. Lo que ya no entra se menciona solo por titulo, en una linea.

    Un capitulo sin resumen aporta el FINAL de su texto (no el principio).
    """
    upto_index = max(0, min(upto_index, len(project.chapters)))
    has_material = any(
        project.chapters[i].summary.strip() or project.chapters[i].content.strip()
        for i in range(upto_index)
    )
    if not has_material:
        return "This is the first chapter of the story."

    last_index = upto_index - 1
    last = project.chapters[last_index]
    handoff = ""
    if last.content.strip():
        handoff = tail_preserving_format(last.content, _handoff_words(max_words))
    remaining = max_words - len(handoff.split())

    def label(i: int) -> str:
        return f"Chapter {i + 1} ({project.chapters[i].title})"

    # (indice, linea) del mas reciente al mas viejo
    included: List[Tuple[int, str]] = []
    omitted: List[int] = []

    last_summary = last.summary.strip()
    if last_summary:
        text = _trim_words(last_summary, max(remaining, 40))
        included.append((last_index, f"{label(last_index)} summary: {text}"))
        remaining -= len(text.split())

    for i in range(last_index - 1, -1, -1):
        ch = project.chapters[i]
        body = ch.summary.strip() or _trim_words_tail(ch.content.strip(), _MISSING_SUMMARY_EXCERPT_WORDS)
        if not body:
            continue
        if omitted:
            omitted.append(i)
            continue
        line_words = len(body.split())
        if line_words <= remaining:
            included.append((i, f"{label(i)} summary: {body}"))
            remaining -= line_words
        elif remaining >= 30:
            included.append((i, f"{label(i)} summary: {_trim_words(body, remaining)}"))
            remaining = 0
        else:
            omitted.append(i)

    lines: List[str] = []
    if omitted:
        titles = ", ".join(label(i) for i in sorted(omitted))
        lines.append(f"Earlier chapters (not detailed here for space): {titles}.")
    lines.extend(line for _i, line in sorted(included))
    if handoff:
        lines.append(
            f"\nThe last lines of {label(last_index)} (the story continues right after this):\n{handoff}"
        )
    return "\n".join(lines).strip()


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


@dataclass
class LoreMatch:
    """Por que se incluyo una entrada del lorebook: `keyword` que coincidio
    (vacio si es una entrada "siempre incluida"), `position` del ultimo
    acierto en el texto escaneado (mas alto = mas reciente) y `via` = nombre
    de la entrada en cuyo texto aparecio la keyword (escaneo recursivo)."""
    entry: LoreEntry
    keyword: str = ""
    position: int = -1
    via: str = ""

    def reason_es(self) -> str:
        if self.entry.constant and not self.keyword:
            return S.LORE_MOTIVO_SIEMPRE
        if self.via:
            return S.LORE_MOTIVO_VIA.format(keyword=self.keyword, via=self.via)
        return S.LORE_MOTIVO_KEYWORD.format(keyword=self.keyword)


def _last_keyword_hit(entry: LoreEntry, text: str) -> Tuple[str, int]:
    """(keyword, posicion del ultimo acierto) de la keyword que aparece mas
    tarde en `text`; ("", -1) si ninguna aparece."""
    best = ("", -1)
    if not text:
        return best
    for keyword in entry.keyword_list():
        pattern = r"(?i)\b" + re.escape(keyword) + r"\b"
        last = -1
        for m in re.finditer(pattern, text):
            last = m.start()
        if last > best[1]:
            best = (keyword, last)
    return best


def match_lore_entries(entries: List[LoreEntry], scan_text: str, recursive: bool = True) -> List[LoreMatch]:
    """
    Lorebook / World Info: las entradas activas (`enabled`) cuyo keyword
    aparece como palabra/frase completa (sin distinguir mayusculas) en
    `scan_text` -- el texto NARRATIVAMENTE CERCANO a la generacion en curso
    (esquema del capitulo, resumenes previos y el final de lo ya escrito) --
    mas las entradas `constant` (siempre incluidas).

    Con `recursive`, un nivel de escaneo recursivo: una entrada mencionada
    solo en el TEXTO de otra entrada que si coincidio tambien se incluye
    (p.ej. la entrada de un personaje menciona su espada, que tiene su propia
    entrada).

    Orden: siempre-incluidas primero, despues por prioridad (mayor primero)
    y, a igual prioridad, por lo reciente del acierto en el texto escaneado.
    """
    active = [e for e in entries if e.enabled]
    matches: List[LoreMatch] = []
    seen = set()
    for entry in active:
        keyword, pos = _last_keyword_hit(entry, scan_text or "")
        if pos >= 0:
            matches.append(LoreMatch(entry, keyword, pos))
            seen.add(id(entry))
        elif entry.constant:
            matches.append(LoreMatch(entry))
            seen.add(id(entry))
    if recursive:
        for source in list(matches):
            for entry in active:
                if id(entry) in seen:
                    continue
                keyword, _pos = _last_keyword_hit(entry, source.entry.text)
                if keyword:
                    # Detras de las coincidencias directas de su prioridad.
                    matches.append(LoreMatch(entry, keyword, -1, via=source.entry.name.strip() or "(sin nombre)"))
                    seen.add(id(entry))
    order = {id(e): i for i, e in enumerate(entries)}
    matches.sort(key=lambda m: (
        0 if (m.entry.constant and not m.keyword) else 1,
        -m.entry.priority,
        -m.position,
        order.get(id(m.entry), 0),
    ))
    return matches


def find_relevant_lore_entries(entries: List[LoreEntry], scan_text: str) -> List[LoreEntry]:
    """
    Las entradas que coinciden directamente con `scan_text` (sin escaneo
    recursivo), en el orden del lorebook. Ver match_lore_entries().
    """
    if not scan_text or not scan_text.strip():
        return [e for e in entries if e.enabled and e.constant]
    matched = {id(m.entry) for m in match_lore_entries(entries, scan_text, recursive=False)}
    return [e for e in entries if id(e) in matched]


LORE_SCAN_RECENT_WORDS = 500


def build_lore_scan_text(chapter: Chapter, previous: str, recent_text: str = "") -> str:
    """Texto que se escanea en busca de keywords del lorebook: el esquema del
    capitulo, el contexto de capitulos previos y (al continuar) las ultimas
    ~500 palabras ya escritas del capitulo -- asi un personaje que aparece a
    mitad de capitulo recibe su entrada en la seccion siguiente."""
    recent = _trim_words_tail(recent_text.strip(), LORE_SCAN_RECENT_WORDS) if recent_text else ""
    return f"{chapter.outline}\n{previous}\n{recent}"


def build_lorebook_block(
    entries: List[LoreEntry], scan_text: str, max_entry_words: int = 200, max_entries: int = 8,
) -> str:
    """
    Bloque de contexto con SOLO las entradas del lorebook relevantes a
    `scan_text` (ver match_lore_entries) -- vacio si ninguna coincide, para
    no gastar contexto en absoluto cuando el lorebook no aplica a esta
    seccion. `max_entries` acota cuantas entradas como maximo se incluyen
    (las de mayor prioridad primero); cada una se recorta a
    `max_entry_words`, igual que el resto de los campos de este archivo.
    """
    matched = [m.entry for m in match_lore_entries(entries, scan_text)][:max_entries]
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
    bible, task, step_blocks = _chapter_prompt_parts(
        project, chapter_index, max_plot_words, max_characters_words, max_setting_words,
        max_previous_words, max_outline_words, max_lore_words,
    )
    step_context = _step_context_block(step_blocks)
    if step_context:
        return f"{bible}{step_context}\n\n{task}"
    return bible + task


def _chapter_prompt_parts(
    project: Project,
    chapter_index: int,
    max_plot_words: int = 1200,
    max_characters_words: int = 600,
    max_setting_words: int = 600,
    max_previous_words: int = 500,
    max_outline_words: int = 400,
    max_lore_words: int = 200,
    recent_text: str = "",
    max_recall_words: int = 400,
) -> Tuple[str, str, List[str]]:
    """
    (biblia, tarea): la "biblia" de la historia (contexto, capitulos
    previos, esquema, lorebook, reglas de estilo) va en el turno de sistema;
    la tarea ("Now write Chapter N...") en el turno de usuario. En modo
    completion cruda se concatenan, igual que siempre. `recent_text` (lo ya
    escrito del capitulo, al continuar) tambien se escanea para el lorebook.
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
    lore_scan_text = build_lore_scan_text(chapter, previous, recent_text)
    lore_block = build_lorebook_block(project.lore_entries, lore_scan_text, max_entry_words=max_lore_words)
    style_emphasis = build_writing_style_instruction(project)
    purpose_instruction = build_chapter_purpose_instruction(chapter)
    bible = (
        "You are a skilled fiction writer producing one chapter of a longer "
        "story for an adult creative-writing project. Stay fully consistent "
        "with the plot, characters and setting provided. Do not break "
        "character or add disclaimers.\n\n"
        f"{context}\n"
        f"{overview}\n"
        f"PROGRESS SO FAR:\n{previous}\n\n"
        f"{outline_block}"
        f"{purpose_instruction}"
        f"{style_emphasis}"
        f"{style_guide_for(project)}\n"
    )
    task = (
        f"Now write Chapter {chapter_index + 1}, titled \"{chapter.title}\". "
        f"Target length: approximately {chapter.target_words} words. "
    )
    directive = task_directive(project)
    if directive:
        task += f"{directive} "
    blocks = [lore_block.rstrip()] if lore_block else []
    if project.recall_passages:
        from .retrieval import build_recall_block

        recall = build_recall_block(project, chapter_index, recent_text, max_recall_words)
        if recall:
            blocks.append(recall)
    return bible, task, blocks


def _outline_beats(outline: str) -> List[str]:
    """Parte el esquema de un capitulo en beats: una linea por beat si viene
    en lista/lineas, o una oracion por beat si es un parrafo."""
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln).strip() for ln in outline.splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) >= 2:
        return lines
    text = " ".join(lines)
    return [s.strip() for s in _SENTENCE_BREAK_RE.split(text) if s.strip()]


def build_beat_progress_hint(outline: str, written_words: int, target_words: int) -> str:
    """
    Pista de avance para una seccion de continuacion: que proporcion del
    capitulo ya esta escrita y por que beat del esquema deberia ir, estimado
    por palabras escritas / objetivo. Vacio si el esquema no tiene al menos
    dos beats.
    """
    beats = _outline_beats(outline or "")
    if len(beats) < 2 or target_words <= 0:
        return ""
    fraction = max(0.0, min(1.0, written_words / target_words))
    done = min(len(beats) - 1, int(math.floor(fraction * len(beats))))
    next_beat = _trim_words(beats[done], 40)
    return (
        f"PROGRESS: about {int(fraction * 100)}% of this chapter is written. The outline "
        f"beats before beat {done + 1} of {len(beats)} are probably covered; continue "
        f"with beat {done + 1}: \"{next_beat}\"."
    )


def build_section_scope_hint(outline: str, written_words: int, section_words: int, target_words: int) -> str:
    """
    Alcance de una seccion que NO es la ultima: que beats del esquema
    escribir ahora (los que le tocan por proporcion de palabras) y la orden de
    no terminar el capitulo. Sin esto, la primera seccion recibia el esquema
    entero y "unas {target} palabras", pero presupuesto para ~900: el modelo
    comprimia todos los beats en ~600 palabras y escribia un final, y las
    secciones siguientes solo podian agregar mas cierres.
    """
    if target_words <= 0:
        return ""
    start = max(0.0, min(1.0, written_words / target_words))
    end = max(start, min(1.0, (written_words + section_words) / target_words))
    beats = _outline_beats(outline or "")
    if len(beats) >= 2:
        # Rounded the same way at both ends, so consecutive parts split the
        # beats without overlapping (an overlap invited the model to retell one).
        first = min(len(beats) - 1, int(round(start * len(beats))))
        last = max(first, min(len(beats) - 1, int(round(end * len(beats))) - 1))
        if last >= len(beats) - 1 and first > 0:
            last = len(beats) - 2  # the last beat belongs to the final part
        last = max(first, last)
        if first == last:
            scope = f"beat {first + 1} of {len(beats)} (\"{_trim_words(beats[first], 40)}\")"
        else:
            scope = f"beats {first + 1} to {last + 1} of {len(beats)}"
            scope += " (" + "; ".join(f"\"{_trim_words(b, 25)}\"" for b in beats[first:last + 1]) + ")"
        return (
            f"SCOPE OF THIS PART: this part covers about {int(start * 100)}-{int(end * 100)}% of the chapter. "
            f"Write only {scope} now, as full scenes with dialogue, action, sensory detail and the characters' "
            "thoughts; take your time. Stop when this part is told: the later beats come in later parts. "
            "Do not end, conclude or sum up the chapter."
        )
    return (
        f"SCOPE OF THIS PART: this part is only about {int(start * 100)}-{int(end * 100)}% of the chapter. "
        "Develop the events slowly, as full scenes with dialogue, action, sensory detail and the characters' "
        "thoughts, and do not reach the chapter's ending yet. Do not end, conclude or sum up the chapter."
    )


# Palabras del final del capitulo que van pre-llenadas en la respuesta al
# continuar (ver build_chapter_continuation_chat).
CONTINUATION_PREFILL_WORDS = 60

NOT_OVER_NUDGE = (
    "The chapter is not finished yet: do not write an ending, a conclusion or a "
    "summary; keep developing the remaining events."
)
FINAL_SECTION_HINT = "This is the final part of the chapter: bring it to a natural close."


def build_author_note(project: Project, chapter: Chapter) -> str:
    """
    Nota del autor (de la historia y/o del capitulo): una instruccion corta
    que se inserta CERCA DEL FINAL del prompt, justo antes de la orden de
    escribir. En un prompt largo, lo que esta al principio (la biblia) pierde
    peso; esto es la forma barata de "dirigir" la seccion siguiente (como el
    Author's Note de NovelAI / KoboldCpp / SillyTavern). Vacio si no hay.
    """
    notes = [n.strip() for n in (project.author_note, chapter.author_note) if n and n.strip()]
    if not notes:
        return ""
    return "AUTHOR'S NOTE (apply this to the passage you write now): " + " ".join(notes)


from .story_settings import build_story_settings_reminder, task_directive  # noqa: E402

STEP_CONTEXT_HEADER = "STEP-SPECIFIC CONTEXT (closest to the passage you are writing now):"


def _step_context_block(blocks: List[str]) -> str:
    clean = [block.strip() for block in blocks if block and block.strip()]
    if not clean:
        return ""
    return f"{STEP_CONTEXT_HEADER}\n\n" + "\n\n".join(clean)


def build_chapter_start_chat(
    project: Project, chapter_index: int, budget: dict, hints: Optional[List[str]] = None,
) -> ChatPrompt:
    """Primera seccion de un capitulo (todavia no hay texto escrito). `hints`:
    lineas extra, como el alcance de la seccion (build_section_scope_hint)."""
    if project.chapters[chapter_index].custom_prompt.strip():
        return build_custom_chapter_chat(project, chapter_index, budget)
    bible, task, step_blocks = _chapter_prompt_parts(project, chapter_index, **_chapter_budget_kwargs(budget))
    step_blocks += [h for h in (hints or []) if h]
    reminder = build_story_settings_reminder(project)
    if reminder:
        step_blocks.append(reminder)
    note = build_author_note(project, project.chapters[chapter_index])
    if note:
        step_blocks.append(note)
    step_context = _step_context_block(step_blocks)
    user = (
        f"{task.strip()}\n\nBegin the chapter now. Output only the chapter's prose "
        "(no chapter heading, no notes)."
    )
    if step_context:
        user = f"{user}\n\n{step_context}"
    # Completado sin chat: termina con la indicacion de empezar, para que el
    # modelo arranque a escribir prosa justo despues.
    step_part = f"\n\n{step_context}" if step_context else ""
    raw = f"{bible}{task}{step_part}\n\nBegin the chapter now:\n"
    return ChatPrompt(
        system=bible.rstrip(),
        user=user,
        raw=raw,
    )


def build_chapter_continuation_chat(
    project: Project,
    chapter_index: int,
    budget: dict,
    already_written: str,
    remaining_words: int,
    tail_words: int,
    hints: Optional[List[str]] = None,
) -> ChatPrompt:
    """
    Seccion de continuacion. En modo chat, el final de lo ya escrito va como
    comienzo de la respuesta del asistente (`prefill`): el modelo sigue
    escribiendo la prosa desde ese punto exacto (incluso a mitad de una
    oracion) en vez de "contestar" una instruccion. `hints` son lineas extra
    (avance por beats, "todavia no termines", "esta es la ultima parte").
    """
    if project.chapters[chapter_index].custom_prompt.strip():
        return build_custom_chapter_chat(project, chapter_index, budget, already_written, tail_words)
    bible, task, step_blocks = _chapter_prompt_parts(
        project, chapter_index, recent_text=already_written, **_chapter_budget_kwargs(budget),
    )
    hints = [h for h in (hints or []) if h]
    note = build_author_note(project, project.chapters[chapter_index])
    # Orden de los bloques variables: lorebook, largo, pistas y al final la
    # nota del autor -- lo ultimo que lee el modelo antes de escribir.
    reminder = build_story_settings_reminder(project)
    tail_blocks = hints + ([reminder] if reminder else []) + ([note] if note else [])
    step_context = _step_context_block(step_blocks + [f"Write about {remaining_words} more words."] + tail_blocks)
    # Solo el ultimo parrafo (~CONTINUATION_PREFILL_WORDS) va pre-llenado en la
    # respuesta; el resto de la cola va en el mensaje como contexto. Con toda la
    # cola (cientos de palabras) en la respuesta, el modelo "ya llevaba" una
    # respuesta larga y queria cerrarla enseguida: secciones de 40-100 palabras
    # que solo agregaban finales.
    recent = tail_preserving_format(already_written, tail_words)
    prefill = tail_preserving_format(already_written, min(tail_words, CONTINUATION_PREFILL_WORDS))
    earlier = recent[: len(recent) - len(prefill)].rstrip() if recent.endswith(prefill) else ""
    so_far = f"The chapter written so far ends like this:\n\n{earlier}\n\n" if earlier else ""
    user = (
        f"{task.strip()}\n\nThe chapter is already in progress. {so_far}Your reply starts with the "
        "chapter's last lines, already written for you. Continue it seamlessly from the exact "
        "point where it stops. Do not repeat earlier sentences, do not restart the scene "
        "and do not summarize."
    )
    if step_context:
        user = f"{user}\n\n{step_context}"
    # build_continuation_prompt ya dice cuantas palabras faltan: no se repite aqui.
    cont = build_continuation_prompt(
        already_written, remaining_words, tail_words=tail_words, hints=step_blocks + tail_blocks
    )
    return ChatPrompt(
        system=bible.rstrip(),
        user=user,
        prefill=prefill,
        raw=f"{bible}{task}\n\n{cont}\n",
    )


# ---------------- prompt propio de un capitulo ----------------
# Marcadores que el usuario puede escribir en Chapter.custom_prompt; cada uno se
# reemplaza por el dato del proyecto (recortado al presupuesto de contexto, como
# en el prompt automatico). Un {texto} que no es un marcador queda tal cual.
# Se aceptan con y sin acento ({título} / {titulo}).
CUSTOM_PROMPT_PLACEHOLDERS = (
    "plot", "personajes", "setting", "esquema", "anterior", "título", "capítulo", "palabras", "nota_autor",
    "género", "tema", "tono", "punto_de_vista",
)
_PLACEHOLDER_ALIASES = {"titulo": "título", "capitulo": "capítulo", "genero": "género"}
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

# Punto de partida que ofrece el boton "Insertar plantilla" (en ingles, como la
# prosa que se pide).
CUSTOM_PROMPT_TEMPLATE = (
    "Write chapter {capítulo} of a novel, titled \"{título}\". Write about {palabras} words of "
    "prose in English, in the third person and past tense.\n\n"
    "Story so far:\n{anterior}\n\n"
    "Characters:\n{personajes}\n\n"
    "Setting:\n{setting}\n\n"
    "What happens in this chapter:\n{esquema}\n\n"
    "Output only the chapter's prose, without a heading or notes."
)

CUSTOM_PROMPT_SO_FAR = "The chapter written so far ends like this (your reply continues it seamlessly):"


def render_custom_prompt(
    project: Project, chapter_index: int, max_plot_words: Optional[int] = None,
    max_characters_words: Optional[int] = None, max_setting_words: Optional[int] = None,
    max_previous_words: int = 500, max_outline_words: Optional[int] = None, **_unused,
) -> str:
    """El prompt propio del capitulo con sus marcadores reemplazados."""
    from .story_settings import english_value

    chapter = project.chapters[chapter_index]

    def trimmed(text: str, limit: Optional[int]) -> str:
        text = (text or "").strip()
        return _trim_words(text, limit) if limit else text

    values = {
        "plot": lambda: trimmed(project.plot, max_plot_words),
        "personajes": lambda: trimmed(project.characters, max_characters_words),
        "setting": lambda: trimmed(project.setting, max_setting_words),
        "esquema": lambda: trimmed(chapter.outline, max_outline_words),
        "anterior": lambda: build_previous_context(project, chapter_index, max_previous_words),
        "título": lambda: chapter.title.strip(),
        "capítulo": lambda: str(chapter_index + 1),
        "palabras": lambda: str(chapter.target_words),
        "nota_autor": lambda: chapter.author_note.strip(),
        "género": lambda: english_value("genre", project.genre),
        "tema": lambda: english_value("theme", project.theme),
        "tono": lambda: english_value("tone", project.tone),
        "punto_de_vista": lambda: english_value("point_of_view", project.point_of_view),
    }

    def substitute(match: "re.Match[str]") -> str:
        key = _PLACEHOLDER_ALIASES.get(match.group(1).lower(), match.group(1).lower())
        value = values.get(key)
        return value() if value else match.group(0)

    return _PLACEHOLDER_RE.sub(substitute, chapter.custom_prompt).strip()


def build_custom_chapter_chat(
    project: Project, chapter_index: int, budget: dict, already_written: str = "", tail_words: int = 0,
) -> ChatPrompt:
    """
    Prompt de un capitulo con prompt propio: el texto del usuario, sin turno de
    sistema ni nada que agregue la app. Un capitulo se escribe por secciones;
    en las siguientes, el final de lo ya escrito va pre-llenado en la respuesta
    (el modelo sigue escribiendo desde ahi) y lo anterior a eso, como unico
    agregado, al final del mensaje, para que sepa donde va.
    """
    user = render_custom_prompt(project, chapter_index, **_chapter_budget_kwargs(budget))
    if not already_written.strip():
        return ChatPrompt(system="", user=user, raw=f"{user}\n\n")
    recent = tail_preserving_format(already_written, tail_words)
    prefill = tail_preserving_format(already_written, min(tail_words, CONTINUATION_PREFILL_WORDS))
    earlier = recent[: len(recent) - len(prefill)].rstrip() if recent.endswith(prefill) else ""
    chat_user = f"{user}\n\n{CUSTOM_PROMPT_SO_FAR}\n\n{earlier}" if earlier else user
    return ChatPrompt(system="", user=chat_user, prefill=prefill, raw=f"{user}\n\n{recent}")


def _chapter_budget_kwargs(budget: dict) -> dict:
    keys = (
        "max_plot_words", "max_characters_words", "max_setting_words",
        "max_previous_words", "max_outline_words", "max_lore_words", "max_recall_words",
    )
    return {k: budget[k] for k in keys if k in budget}


# ---------------- esquema: parser tolerante ----------------
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
    "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10,
}
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}

# Una linea que empieza (tras markdown opcional: "#", ">", "**", "__", "*")
# con "Chapter"/"Capitulo" + numero (cifras, palabra o romano). El resto de
# la linea se valida en _parse_header_rest(): sin un separador (":", ".",
# "-", ...) o markdown, "Chapter 3 ends with a storm." es prosa, no un titulo.
_CHAPTER_HEADER_RE = re.compile(
    r"(?im)^[ \t]*(?P<prefix>(?:#{1,6}[ \t]*|>[ \t]*)?(?:\*\*|__|\*|_)?)[ \t]*"
    r"(?:chapter|cap[ií]tulo)[ \t]+(?P<num>\d{1,3}|[a-z]+)\b(?P<rest>[^\n]*)$"
)
_HEADER_SEPARATOR_RE = re.compile(r"^[*_]*[ \t]*[:.\-–—)][ \t]*")
_HORIZONTAL_RULE_RE = re.compile(r"(?m)^[ \t]*[-*_=]{3,}[ \t]*$")


def _roman_to_int(text: str) -> Optional[int]:
    text = text.lower()
    if not text or any(ch not in _ROMAN_VALUES for ch in text):
        return None
    total = 0
    for i, ch in enumerate(text):
        value = _ROMAN_VALUES[ch]
        if i + 1 < len(text) and _ROMAN_VALUES[text[i + 1]] > value:
            total -= value
        else:
            total += value
    return total if 0 < total <= 100 else None


def _chapter_number(token: str) -> Optional[int]:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token.lower()) or _roman_to_int(token)


def _clean_title(text: str) -> str:
    title = text.strip().strip("*_#").strip()
    if len(title) >= 2 and title[0] in "\"'“" and title[-1] in "\"'”":
        title = title[1:-1].strip()
    return title


def _parse_header_rest(prefix: str, rest: str) -> Optional[str]:
    """Titulo limpio si `rest` (lo que sigue al numero) es un encabezado
    valido; None si la linea parece prosa comun."""
    stripped = rest.strip()
    sep = _HEADER_SEPARATOR_RE.match(stripped)
    if sep:
        return _clean_title(stripped[sep.end():])
    if not stripped.strip("*_#"):
        return ""  # "Chapter 2" solo en su linea (o "**Chapter 2**")
    if prefix.strip():
        return _clean_title(stripped)  # "### Chapter 2 The Storm"
    return None


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


class OutlineParseError(ValueError):
    """La respuesta del modelo no tiene ningun encabezado de capitulo
    reconocible. `raw_text` es la respuesta completa, para mostrarsela al
    usuario en vez de aplicarla a ciegas como un unico capitulo."""

    def __init__(self, message: str, raw_text: str = ""):
        super().__init__(message)
        self.raw_text = raw_text


def parse_outline_response(text: str, expected_chapters: int) -> List[Tuple[str, str]]:
    """
    Extrae pares (titulo, beats) de la respuesta del modelo a
    build_outline_prompt. Tolera el markdown que los modelos suelen agregar
    aunque se les pida texto plano: "**Chapter 1: The Call**",
    "### Chapter 1 - The Call", "Chapter One: ...", "Chapter IV. ...",
    "**Chapter 1:** ..." (ver _CHAPTER_HEADER_RE). Devuelve [] si `text`
    esta vacio.

    Si hay texto pero ningun encabezado reconocible, lanza OutlineParseError
    en vez de devolver todo como un unico "capitulo 1": eso escribia un
    bloque enorme en el esquema del capitulo 1 que, si pasaba de
    MAX_OUTLINE_WORDS_PER_CHAPTER, bloqueaba despues toda generacion.
    """
    matches = []
    for match in _CHAPTER_HEADER_RE.finditer(text):
        number = _chapter_number(match.group("num"))
        if number is None:
            continue
        title = _parse_header_rest(match.group("prefix"), match.group("rest"))
        if title is None:
            continue
        matches.append((match, number, title))

    results: List[Tuple[str, str]] = []
    for i, (match, number, title) in enumerate(matches):
        start = match.end()
        end = matches[i + 1][0].start() if i + 1 < len(matches) else len(text)
        body = _HORIZONTAL_RULE_RE.sub("", text[start:end]).strip()
        results.append((title or f"Chapter {number}", body))
    if not results:
        if not text.strip():
            return []
        raise OutlineParseError(
            S.ESQUEMA_FORMATO_INESPERADO,
            raw_text=text,
        )
    return results[:expected_chapters]


def build_continuation_prompt(
    already_written: str, remaining_words: int, tail_words: int = 400,
    hints: Optional[List[str]] = None,
) -> str:
    """
    Prompt (modo completion cruda) para pedir que el modelo continue un
    capitulo ya empezado. Usa el FINAL de lo ya escrito (no el inicio) para
    que el modelo sepa exactamente donde retomar la escena. `hints` son
    lineas extra opcionales (ver build_chapter_continuation_chat).
    """
    tail = _trim_words_tail(already_written, tail_words)
    step_context = _step_context_block(list(hints or []))
    step_suffix = f"\n\n{step_context}" if step_context else ""
    return (
        "Continue the same chapter directly from where it left off. Do not "
        "repeat previous sentences, do not restart the scene, and do not "
        "summarize what already happened — just keep writing the story.\n\n"
        f"Continue for about {remaining_words} more words, keeping the same "
        f"tone, characters and formatting rules.{step_suffix}\n\n"
        f"...(end of what has been written so far)\n{tail}"
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
    content: Optional[str] = None,
    part: int = 1,
    total_parts: int = 1,
) -> str:
    """
    Prompt para revisar un capitulo YA generado segun una instruccion del
    usuario (p.ej. "hazlo mas oscuro", "acorta la escena del mercado"), en
    vez de generar texto nuevo desde cero. Mantiene el STYLE_GUIDE y el
    enfasis de writing_style del proyecto (las reglas de formato siguen
    aplicando a la version revisada).

    `content` es el texto a revisar (por defecto, el capitulo completo). A
    diferencia del resto de los campos de este archivo, NUNCA se recorta
    aqui: la respuesta reemplaza el capitulo entero, asi que recortar perdia
    en silencio lo que quedaba fuera. Si no cabe, engine.refine_chapter()
    lo divide en partes y llama a esta funcion una vez por parte, con
    `part`/`total_parts` para que el modelo sepa que revisa solo un tramo.
    """
    chapter = project.chapters[chapter_index]
    if content is None:
        content = chapter.content
    content = content.strip()
    style_emphasis = build_writing_style_instruction(project)
    part_note = ""
    if total_parts > 1:
        part_note = (
            f"NOTE: this is part {part} of {total_parts} of the chapter, which is being "
            "revised in consecutive parts. Rewrite ONLY this part, applying the "
            "instruction where it is relevant to this part; do not add a chapter "
            "heading, a recap of earlier parts, or an ending that is not in this part.\n\n"
        )
    return (
        "You are editing an already-written chapter of a longer story, per "
        "the author's instruction below. Rewrite the chapter applying that "
        "instruction, keeping the plot events, characters, and overall "
        "length roughly the same unless the instruction says otherwise. "
        "Output only the revised chapter text, nothing else — no notes, no "
        "commentary, no explanation of what you changed.\n\n"
        f"EDITING INSTRUCTION: {instruction.strip()}\n\n"
        f"{part_note}"
        f"{style_emphasis}"
        f"{style_guide_for(project)}\n"
        f"CURRENT CHAPTER TEXT:\n{content}\n\n"
        "Revised chapter:"
    )


# ---------------- variantes chat (ver ChatPrompt) ----------------
# Cada una conserva en `raw` exactamente el prompt de completion cruda de
# siempre; `system`/`user` son el mismo pedido partido en turnos de chat.

def build_outline_chat(project: Project, num_chapters: int, **budget) -> ChatPrompt:
    raw = build_outline_prompt(project, num_chapters, **budget)
    return ChatPrompt(
        system=(
            "You are a fiction editor planning a story before it is written. Follow the "
            "requested output format exactly: plain text, one \"Chapter N: <title>\" line per "
            "chapter followed by its events, no markdown."
        ),
        user=raw,
        raw=raw,
    )


# ---- conversacion lateral: lluvia de ideas y entrevista a un personaje (F14) ----
_SPANISH_WORDS = frozenset("que qué el la los las de del por para y es tu tú su como cómo cuando dónde donde porque "
                           "pero con una un se le lo me mi ella él hay".split())


def looks_spanish(text: str) -> bool:
    """Heuristica barata: signos de apertura, eñe/tildes o varias palabras funcionales del espanol."""
    if any(ch in text for ch in "¿¡ñÑáéíóúÁÉÍÓÚ"):
        return True
    words = re.findall(r"[a-záéíóúñü]+", text.lower())
    return len(words) >= 3 and sum(word in _SPANISH_WORDS for word in words) / len(words) >= 0.25
SIDE_CHAT_BRAINSTORM = "brainstorm"
SIDE_CHAT_CHARACTER = "character"


def build_side_chat(project: Project, chapter_index: Optional[int], history: Sequence[Tuple[str, str]],
                    message: str, mode: str, character: str = "", budget: Optional[dict] = None,
                    chapter_tail_words: int = 600) -> ChatPrompt:
    """El prompt de un turno de la conversacion lateral. Ve la biblia de la historia (premisa,
    personajes, ambientacion), el resumen del esquema, los capitulos anteriores resumidos y el final
    del capitulo actual; `history` son los turnos previos ("user"/"assistant"), contados dentro del
    turno de usuario para que funcione con cualquier plantilla de chat. Responde en el idioma del
    usuario. Nada de esto se escribe en el capitulo."""
    budget = budget or {}
    context = build_context_block(project, budget.get("max_plot_words", 1200),
                                  budget.get("max_characters_words", 600), budget.get("max_setting_words", 600))
    parts = [context]
    overview = build_story_outline_overview(project)
    if overview.strip():
        parts.append("CHAPTER OUTLINE:\n" + _trim_words(overview, budget.get("max_outline_words", 400)))
    if chapter_index is not None and 0 <= chapter_index < len(project.chapters):
        previous = build_previous_context(project, chapter_index, budget.get("max_previous_words", 500))
        if previous.strip():
            parts.append(previous)
        chapter = project.chapters[chapter_index]
        tail = " ".join(chapter.content.split()[-chapter_tail_words:]) if chapter_tail_words > 0 else ""
        if tail:
            parts.append(f"CURRENT CHAPTER ({chapter.title or chapter_index + 1}), LATEST TEXT:\n{tail}")
    bible = "\n\n".join(p.strip() for p in parts if p.strip())
    if mode == SIDE_CHAT_CHARACTER:
        name = character.strip() or "the main character"
        system = (
            f"You are {name}, a character in the story described below. Stay in character: answer in the "
            f"first person, with {name}'s voice, knowledge, opinions and secrets as the story establishes "
            "them, and only what they could know at this point. Invent details that fit when asked about "
            "something the story doesn't say. Never mention being an AI or a story. Answer in the same "
            "language the writer uses."
        )
    else:
        system = (
            "You are a creative writing partner helping an author develop the story described below. "
            "Brainstorm freely: offer concrete, varied ideas (numbered when listing several), point out "
            "consequences and contradictions, and ask a question back when it helps. Keep to the story's "
            "established facts unless asked to change them. Do not write the chapter itself unless asked. "
            "Answer in the same language the writer uses."
        )
    transcript = "\n".join(
        f"{'Writer' if role == 'user' else (character.strip() or 'Character') if mode == SIDE_CHAT_CHARACTER else 'You'}: {text.strip()}"
        for role, text in history if text.strip()
    )
    user = f"STORY BIBLE:\n{bible}\n\n"
    if transcript:
        user += f"CONVERSATION SO FAR:\n{transcript}\n\n"
    user += f"THE WRITER NOW SAYS:\n{message.strip()}"
    if looks_spanish(message):
        # La biblia suele estar en ingles: sin esto el modelo contesta en ingles a una pregunta en espanol.
        user += "\n\n(Answer in Spanish.)"
    raw = f"{system}\n\n{user}\n\nAnswer:\n"
    return ChatPrompt(system=system, user=user, raw=raw)


def build_summary_chat(text: str, max_words: int) -> ChatPrompt:
    instructions = summary_instructions(max_words)
    return ChatPrompt(
        system=(
            "You write concise, factual plot summaries of fiction chapters, used as memory "
            "for writing the next chapter. Output only the summary."
        ),
        user=f"{instructions}{text}",
        raw=f"{instructions}{text}{SUMMARY_SUFFIX}",
    )


SUMMARY_SUFFIX = "\n\nSummary:"


def summary_instructions(max_words: int) -> str:
    return (
        "Summarize the following story chapter in at most "
        f"{max_words} words, focusing on plot-relevant events only "
        "(no stylistic commentary):\n\n"
    )


def build_partial_summary_chat(text: str, max_words: int, part: int, total_parts: int) -> ChatPrompt:
    """Resumen de UNA parte de un capitulo demasiado largo para resumirse de
    una vez (ver engine.summarize): despues se resumen los resumenes."""
    instructions = (
        f"The following is part {part} of {total_parts} of a story chapter. Summarize this "
        f"part in at most {max_words} words, focusing on plot-relevant events only "
        "(no stylistic commentary):\n\n"
    )
    return ChatPrompt(
        system=(
            "You write concise, factual plot summaries of fiction chapters, used as memory "
            "for writing the next chapter. Output only the summary."
        ),
        user=f"{instructions}{text}",
        raw=f"{instructions}{text}{SUMMARY_SUFFIX}",
    )


def build_combine_summaries_chat(part_summaries: List[str], max_words: int) -> ChatPrompt:
    joined = "\n\n".join(f"Part {i}: {s.strip()}" for i, s in enumerate(part_summaries, start=1))
    instructions = (
        "Below are summaries of consecutive parts of one story chapter, in order. Combine "
        f"them into a single summary of the whole chapter in at most {max_words} words, "
        "keeping the plot-relevant events in order:\n\n"
    )
    return ChatPrompt(
        system=(
            "You write concise, factual plot summaries of fiction chapters, used as memory "
            "for writing the next chapter. Output only the summary."
        ),
        user=f"{instructions}{joined}",
        raw=f"{instructions}{joined}{SUMMARY_SUFFIX}",
    )


def build_expand_field_chat(field_key: str, text: str, max_words: int) -> ChatPrompt:
    raw = build_expand_field_prompt(field_key, text, max_words)
    label = EXPAND_FIELD_LABELS.get(field_key, field_key)
    user = raw[: -len("Expanded notes:")].rstrip() if raw.endswith("Expanded notes:") else raw
    return ChatPrompt(
        system=(
            f"You are a fiction editor helping an author flesh out their {label} notes. "
            "Output only the expanded notes, with no preamble or commentary."
        ),
        user=user,
        raw=raw,
    )


def build_refine_chapter_chat(
    project: Project,
    chapter_index: int,
    instruction: str,
    content: Optional[str] = None,
    part: int = 1,
    total_parts: int = 1,
) -> ChatPrompt:
    raw = build_refine_chapter_prompt(project, chapter_index, instruction, content, part, total_parts)
    marker = "EDITING INSTRUCTION:"
    cut = raw.find(marker)
    system = raw[:cut].rstrip() if cut > 0 else "You are editing an already-written chapter of a longer story."
    style = f"{build_writing_style_instruction(project)}{style_guide_for(project)}".rstrip()
    user = raw[cut:] if cut > 0 else raw
    # En chat las reglas de estilo van en el turno de sistema, no en medio
    # del pedido del usuario.
    user = user.replace(f"{build_writing_style_instruction(project)}{style_guide_for(project)}\n", "")
    if user.endswith("Revised chapter:"):
        user = user[: -len("Revised chapter:")].rstrip()
    return ChatPrompt(system=f"{system}\n\n{style}", user=user, raw=raw)


# ---------------- completar un esquema incompleto ----------------
def build_outline_completion_chat(
    project: Project, num_chapters: int, existing: List[Tuple[str, str]], **budget,
) -> ChatPrompt:
    """
    Pide SOLO los capitulos que faltan de un esquema que salio incompleto
    (respuesta cortada por largo, o el modelo escribio menos capitulos de los
    pedidos): los ya planeados van como contexto y el modelo sigue desde
    "Chapter k+1". Ver engine.complete_outline().
    """
    context = build_context_block(project, **budget)
    style_emphasis = build_writing_style_instruction(project)
    start = len(existing) + 1
    planned = "\n\n".join(
        f"Chapter {i}: {title}\n{beats.strip()}" for i, (title, beats) in enumerate(existing, start=1)
    )
    raw = (
        "You are a fiction editor planning a story before it is written. The outline below "
        f"for a story with EXACTLY {num_chapters} chapters is unfinished: only chapters 1 to "
        f"{start - 1} have been planned.\n\n"
        f"{context}\n"
        f"{style_emphasis}"
        f"OUTLINE SO FAR:\n{planned}\n\n"
        f"Write ONLY the missing chapters, from Chapter {start} to Chapter {num_chapters}, "
        "continuing the same story arc so that it reaches a clear climax and resolution by "
        f"Chapter {num_chapters}. Use exactly this format (plain text, no markdown):\n\n"
        f"Chapter {start}: <short chapter title>\n"
        "<2 to 4 sentences describing the key events of this chapter>\n\n"
        "Do not repeat the chapters that are already planned."
    )
    return ChatPrompt(
        system=(
            "You are a fiction editor planning a story before it is written. Follow the "
            "requested output format exactly: plain text, one \"Chapter N: <title>\" line per "
            "chapter followed by its events, no markdown."
        ),
        user=raw,
        raw=raw,
    )


# ---------------- acciones sobre una seleccion ----------------
REWRITE_MODES = {
    "rewrite": "Rewrite the PASSAGE with fresher, stronger prose, keeping the same events and meaning.",
    "expand": "Expand the PASSAGE to roughly twice its length with more detail, action and interiority, keeping the same events.",
    "describe": "Rewrite the PASSAGE adding vivid sensory description (sight, sound, smell, touch) of the scene, keeping the same events.",
    "shorten": "Condense the PASSAGE to roughly half its length, keeping every plot-relevant event.",
}
REWRITE_MODE_LABELS = {
    "rewrite": "Reescribir",
    "expand": "Expandir",
    "describe": "Describir",
    "shorten": "Acortar",
}
REWRITE_CONTEXT_WORDS = 300


def build_rewrite_span_chat(
    project: Project, chapter_index: int, before: str, selection: str, after: str,
    mode: str = "rewrite", instruction: str = "",
) -> ChatPrompt:
    """
    Reescribe SOLO un fragmento seleccionado del capitulo (Reescribir /
    Expandir / Describir / Acortar, como en Sudowrite), con ~300 palabras de
    contexto antes y despues para que encaje. La respuesta reemplaza solo la
    seleccion (ver engine.rewrite_span()).
    """
    task = REWRITE_MODES.get(mode, REWRITE_MODES["rewrite"])
    if instruction.strip():
        task += f" Additional instruction from the author: {instruction.strip()}"
    style_emphasis = build_writing_style_instruction(project)
    chapter = project.chapters[chapter_index]
    before_ctx = _trim_words_tail(before.strip(), REWRITE_CONTEXT_WORDS)
    after_ctx = _trim_words(after.strip(), REWRITE_CONTEXT_WORDS)
    system = (
        "You are editing one passage of an already-written chapter of a longer story. "
        "Output only the replacement passage -- no notes, no quotes around it, no "
        "commentary, and no text from before or after the passage.\n\n"
        f"{style_emphasis}{style_guide_for(project)}".rstrip()
    )
    user = (
        f"Chapter {chapter_index + 1}: \"{chapter.title}\".\n\n"
        f"TEXT BEFORE THE PASSAGE (context only, do not rewrite):\n{before_ctx or '(start of chapter)'}\n\n"
        f"PASSAGE:\n{selection.strip()}\n\n"
        f"TEXT AFTER THE PASSAGE (context only, do not rewrite):\n{after_ctx or '(end of chapter)'}\n\n"
        f"TASK: {task}"
    )
    raw = f"{system}\n\n{user}\n\nReplacement passage:\n"
    return ChatPrompt(system=system, user=user, raw=raw)
