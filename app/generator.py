"""Generador de historias: una página aparte (/generador, app/web/generador.*)
para escribir una historia de una vez a partir de un formulario, sin proyecto
ni capítulos.

El formulario (trama, personajes, ambientación, género, tema, punto de vista,
tono, contexto adicional, propósito, formato, largo y equilibrio de diálogo)
se convierte en UN prompt (`build_prompt`) que se genera con el mismo motor
que los capítulos (engine.generate_chapter sobre un proyecto temporal con un
capítulo de prompt propio): así hay secciones para los textos largos,
streaming, Detener y la limpieza de app/output_guard.py. La prosa se pide en
inglés, como en el resto de StoryForge.

Historial, guardados y presets propios viven en user_data_dir()/generador.json
(HISTORY_LIMIT entradas; las guardadas no se borran solas).

Segunda ronda (2026-10-18, comparado con el generador de toolsaday.com analizado con REA): campos
que dependen del propósito (trama del capítulo y resumen del anterior; resumen de la historia y
trama del clímax o del final), largo exacto en palabras (50-6000), varios capítulos para una
historia completa (uno por uno, cada uno con el resumen de los anteriores), idioma de salida,
pedir cambios sobre un resultado (una revisión que queda en el historial unida al original),
valorar resultados (me gusta / no me gusta) y convertir un resultado en un proyecto de StoryForge.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from . import story_settings
from .fileutil import atomic_write_text
from .paths import user_data_dir

# Límites de cada campo, como en el formulario original (caracteres).
FIELD_LIMITS = {
    "plot": 50_000, "characters": 50_000, "setting": 10_000, "genre": 1_000, "theme": 1_000,
    "point_of_view": 1_000, "tone": 255, "context": 50_000,
    # Solo para algunos propósitos (PURPOSE_FIELDS).
    "chapter_plot": 50_000, "previous_summary": 50_000, "main_summary": 50_000, "climax_plot": 50_000,
    "ending_plot": 50_000,
}

# Campos extra de cada propósito (los demás se vacían): el capítulo necesita su trama y qué pasó antes;
# el clímax, el final y el epílogo, el resumen de la historia y su propia trama.
PURPOSE_FIELDS = {
    "chapter": ("chapter_plot", "previous_summary"),
    "climax": ("main_summary", "climax_plot"),
    "ending": ("main_summary", "ending_plot"),
    "epilogue": ("main_summary",),
}
PURPOSE_FIELD_LABELS = {
    "chapter_plot": ("Trama del capítulo", "THIS CHAPTER'S PLOT"),
    "previous_summary": ("Resumen del capítulo anterior", "WHAT HAPPENED IN THE PREVIOUS CHAPTER"),
    "main_summary": ("Resumen de la historia", "SUMMARY OF THE STORY SO FAR"),
    "climax_plot": ("Trama del clímax", "WHAT HAPPENS IN THE CLIMAX"),
    "ending_plot": ("Trama del final", "HOW THE STORY ENDS"),
}
MIN_WORDS, MAX_WORDS = 50, 6000
MAX_CHAPTERS = 10
LANGUAGES = ("English", "Spanish", "French", "German", "Italian", "Portuguese")
LANGUAGE_LABELS = {"English": "Inglés", "Spanish": "Español", "French": "Francés", "German": "Alemán",
                   "Italian": "Italiano", "Portuguese": "Portugués"}
MAX_REVISION_REQUEST = 2_000

PURPOSES = {
    "complete": ("Historia completa", "a complete, self-contained story with a clear beginning, middle and a "
                                      "satisfying ending"),
    "opening": ("Comienzo de la historia", "the opening of the story: introduce the main characters, the setting "
                                           "and the central conflict, and end on a hook -- do not resolve the plot"),
    "chapter": ("Capítulo", "one chapter of the story that moves the plot forward without resolving it"),
    "climax": ("Escena climática", "the climax scene, where the central conflict comes to a head"),
    "ending": ("Final de la historia", "the ending of the story, resolving the central conflict and the "
                                       "characters' arcs"),
    "epilogue": ("Epílogo", "an epilogue set some time after the main events, showing where the characters "
                            "ended up"),
}

FORMATS = {
    "prose": ("Prosa", "prose fiction", [
        "Write flowing prose: narration in paragraphs, dialogue in double quotes with a new paragraph per "
        "speaker.",
    ]),
    "screenplay": ("Guion de cine", "a screenplay", [
        "Use screenplay format: scene headings in capitals (INT. or EXT., the location, then DAY or NIGHT), "
        "action lines in the present tense, and each character's name in capitals on its own line above "
        "their dialogue.",
        "Use parentheticals sparingly and only for how a line is delivered.",
    ]),
    "stage_play": ("Obra de teatro", "a stage play", [
        "Use stage play format: each line of dialogue starts with the character's name in capitals and a "
        "colon; stage directions in the present tense, in parentheses on their own lines.",
        "Begin with a short description of the stage set in parentheses.",
    ]),
    "poetry": ("Poesía", "a narrative poem", [
        "Write a narrative poem in stanzas, with deliberate line breaks, vivid imagery and rhythm; it may "
        "rhyme or be free verse, but it must tell the story.",
    ]),
}

LENGTHS = {
    "flash": ("Microrrelato (~300 palabras)", 300),
    "short": ("Corto (~800 palabras)", 800),
    "medium": ("Mediano (~1.500 palabras)", 1500),
    "long": ("Largo (~3.000 palabras)", 3000),
    "very_long": ("Muy largo (~6.000 palabras)", 6000),
}

# Equilibrio de diálogo del control deslizante (0 = todo narración, 100 = todo
# diálogo) -> las mismas instrucciones de story_settings.
def dialogue_key(value: Any) -> str:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return ""
    if level < 0:
        return ""
    for limit, key in ((15, "mucha_narracion"), (40, "mas_narracion"), (60, "equilibrado"), (85, "mas_dialogo")):
        if level < limit:
            return key
    return "mucho_dialogo"


class GeneratorError(ValueError):
    """Un formulario inválido (el mensaje es para el usuario)."""


def clean_form(data: Any) -> Dict[str, Any]:
    """El formulario validado: textos recortados a su límite y opciones conocidas."""
    if not isinstance(data, dict):
        raise GeneratorError("Solicitud inválida.")
    form: Dict[str, Any] = {}
    for field, limit in FIELD_LIMITS.items():
        value = data.get(field, "")
        if not isinstance(value, str):
            raise GeneratorError(f"Valor inválido en «{field}».")
        form[field] = value.strip()[:limit]
    for field, choices, default in (("purpose", PURPOSES, "complete"), ("format", FORMATS, "prose"),
                                    ("length", LENGTHS, "short")):
        value = data.get(field, default)
        if value not in choices:
            raise GeneratorError(f"Opción desconocida en «{field}».")
        form[field] = value
    dialogue = data.get("dialogue", -1)
    form["dialogue"] = dialogue if isinstance(dialogue, int) and not isinstance(dialogue, bool) and -1 <= dialogue <= 100 else -1
    for field in PURPOSE_FIELD_LABELS:  # solo los del propósito elegido
        if field not in PURPOSE_FIELDS.get(form["purpose"], ()):
            form[field] = ""
    words = data.get("words")
    if isinstance(words, int) and not isinstance(words, bool) and words > 0:
        form["words"] = max(MIN_WORDS, min(MAX_WORDS, words))
    else:
        form["words"] = LENGTHS[form["length"]][1]
    chapters = data.get("chapters", 1)
    form["chapters"] = (max(1, min(MAX_CHAPTERS, chapters))
                        if isinstance(chapters, int) and not isinstance(chapters, bool) and form["purpose"] == "complete"
                        else 1)
    language = data.get("language", "English")
    if language not in LANGUAGES:
        raise GeneratorError("Idioma desconocido.")
    form["language"] = language
    if not form["plot"] and not any(form[f] for f in PURPOSE_FIELDS.get(form["purpose"], ())):
        raise GeneratorError("Escribe al menos la trama de la historia.")
    return form


def target_words(form: Dict[str, Any]) -> int:
    """El largo pedido en palabras (el de toda la historia si tiene varios capítulos)."""
    words = form.get("words")
    return int(words) if isinstance(words, int) and words > 0 else LENGTHS[form.get("length", "short")][1]


def chapter_words(form: Dict[str, Any]) -> int:
    return max(MIN_WORDS, target_words(form) // max(1, int(form.get("chapters", 1) or 1)))


def build_prompt(form: Dict[str, Any], chapter: int = 0, story_so_far: str = "") -> str:
    """El prompt completo (en inglés) para el formulario. Con varios capítulos, `chapter` es el
    índice del que se escribe y `story_so_far` el resumen de los anteriores."""
    # Componentes de prompt (F20): {@nombre} en cualquier campo de texto.
    from .prompt_components import expand_components, load_components

    components = load_components()
    form = {key: expand_components(value, components) if isinstance(value, str) else value for key, value in form.items()}
    purpose = PURPOSES[form["purpose"]][1]
    fmt_name, fmt_rules = FORMATS[form["format"]][1], FORMATS[form["format"]][2]
    chapters = int(form.get("chapters", 1) or 1)
    language = form.get("language", "English")
    words = chapter_words(form)
    lines = ["You are a skilled fiction writer working on an adult creative-writing project."]
    if chapters > 1:
        last = chapter == chapters - 1
        lines.append(f"The story is {purpose}, told in {chapters} chapters. Write chapter {chapter + 1} of "
                     f"{chapters} now, as {fmt_name}, about {words} words long, in {language}.")
        lines.append("This is the final chapter: bring the story to its ending." if last else
                     "This is not the last chapter: move the story forward and end the chapter without "
                     "resolving the central conflict.")
    else:
        lines.append(f"Write {purpose}, as {fmt_name}, about {words} words long, in {language}.")
    lines.append("")
    settings = []
    for field, label in (("genre", "Genre"), ("theme", "Theme")):
        if form[field]:
            settings.append(f"{label}: {story_settings.english_value(field, form[field])}")
    if form["tone"]:
        settings.append(f"Tone: {story_settings.english_value('tone', form['tone'])} -- "
                        f"{story_settings.TONE_INSTRUCTION}.")
    if form["point_of_view"]:
        settings.append(f"Point of view: {story_settings.english_value('point_of_view', form['point_of_view'])}. "
                        "Keep it consistently.")
    dialogue = story_settings.DIALOGUE_INSTRUCTIONS.get(dialogue_key(form["dialogue"]), "")
    if dialogue:
        settings.append(f"Dialogue: {dialogue}")
    if settings:
        lines += ["STORY SETTINGS:", *settings, ""]
    if form["plot"]:
        lines += ["PLOT:", form["plot"], ""]
    for field in PURPOSE_FIELDS.get(form["purpose"], ()):
        if form.get(field):
            lines += [f"{PURPOSE_FIELD_LABELS[field][1]}:", form[field], ""]
    for field, label in (("characters", "CHARACTERS"), ("setting", "SETTING"), ("context", "ADDITIONAL CONTEXT")):
        if form[field]:
            lines += [f"{label}:", form[field], ""]
    if chapters > 1 and story_so_far.strip():
        lines += ["THE STORY SO FAR (previous chapters, summarized):", story_so_far.strip(), ""]
    lines += ["RULES:", *(f"- {rule}" for rule in fmt_rules),
              "- Do not repeat the same descriptive word or phrase more than twice in a scene.",
              f"- Write only in {language}, whatever the language of the notes above.",
              f"- Output only the {fmt_name.split()[-1]} itself: no title line, no notes, no commentary."]
    if form["purpose"] != "complete":
        lines.append("- Write only this part of the story; do not summarize the rest of it.")
    if chapters > 1:
        lines.append("- Continue from the story so far without retelling it; do not write a chapter heading.")
    return "\n".join(lines).strip()


def build_revision_prompt(form: Dict[str, Any], text: str, request: str) -> str:
    """El prompt para pedir cambios sobre un resultado: la historia completa y lo que se quiere."""
    fmt_name = FORMATS[form["format"]][1]
    language = form.get("language", "English")
    return "\n".join([
        "You are a skilled fiction editor and writer working on an adult creative-writing project.",
        f"Below is {fmt_name} written for the author, followed by the author's request. Rewrite it following "
        f"the request, keeping everything the request doesn't ask to change. If the request asks to continue "
        f"or extend it, write the whole text including the continuation. Write in {language}.",
        "",
        "THE TEXT:", text.strip(), "",
        "THE AUTHOR'S REQUEST:", request.strip(), "",
        "RULES:",
        f"- Output only the revised {fmt_name.split()[-1]}: no notes, no commentary, no explanation of the changes.",
    ]).strip()


def title_for(form: Dict[str, Any]) -> str:
    """Una etiqueta corta para el historial: propósito, género y el comienzo de la trama."""
    parts = [PURPOSES[form["purpose"]][0]]
    if form["genre"]:
        parts.append(form["genre"])
    plot = " ".join(form["plot"].split())
    return " · ".join(parts) + f" — {plot[:60]}{'…' if len(plot) > 60 else ''}"


# ---------------- presets incorporados (ejemplos completos) ----------------
BUILTIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "Ejemplo: misterio en el faro": {
        "plot": "A lighthouse keeper on a remote island finds a message in a bottle written in her own "
                "handwriting, dated ten years in the future.",
        "characters": "Mara: 40s, the lighthouse keeper, practical and solitary.\nJonah: the supply boat "
                      "captain, the only person who visits.",
        "setting": "A rocky island off the coast of Maine, late autumn, storms rolling in.",
        "genre": "Misterio", "theme": "Identidad", "point_of_view": "Primera persona",
        "tone": "Oscuro y misterioso", "context": "", "purpose": "complete", "format": "prose",
        "length": "short", "dialogue": 30,
    },
    "Ejemplo: comedia en la oficina": {
        "plot": "On the first day of a mandatory team-building retreat, the office's two worst enemies get "
                "locked together in the escape room.",
        "characters": "Priya: the over-prepared project manager.\nDev: the sarcastic senior engineer who "
                      "has never attended a meeting on time.",
        "setting": "A tacky escape room themed as a pirate ship, on the edge of town.",
        "genre": "Comedia", "theme": "Amistad", "point_of_view": "Tercera persona limitada",
        "tone": "Ligero y humorístico", "context": "", "purpose": "complete", "format": "screenplay",
        "length": "short", "dialogue": 80,
    },
    "Ejemplo: fábula para niños": {
        "plot": "A small fox who is afraid of the dark must cross the forest at night to bring medicine "
                "to her grandmother.",
        "characters": "Pip: a young fox, curious but timid.\nOld Owl: wise and a bit grumpy.",
        "setting": "An enchanted forest with glowing mushrooms.",
        "genre": "Cuento infantil", "theme": "Crecer", "point_of_view": "Tercera persona omnisciente",
        "tone": "Esperanzador", "context": "For readers aged 5 to 8: simple words, gentle suspense.",
        "purpose": "complete", "format": "prose", "length": "flash", "dialogue": 50,
    },
    "Ejemplo: escena final épica": {
        "plot": "After a ten-year war, the exiled queen returns to face her brother, who stole the throne.",
        "characters": "Queen Seraphine: exiled ruler, merciful but resolute.\nKing Aldric: her brother, "
                      "charming and ruthless.",
        "setting": "The burning throne room of the capital, during the final siege.",
        "genre": "Fantasía", "theme": "Poder y corrupción", "point_of_view": "Tercera persona limitada",
        "tone": "Épico", "context": "", "purpose": "climax", "format": "prose", "length": "medium",
        "dialogue": 55,
    },
}


# ---------------- almacenamiento: historial, guardados, presets ----------------
HISTORY_LIMIT = 200
_lock = threading.Lock()


def store_path() -> str:
    return os.path.join(user_data_dir(), "generador.json")


def _load() -> Dict[str, Any]:
    try:
        with open(store_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(store_path()), exist_ok=True)
    atomic_write_text(store_path(), json.dumps(data, ensure_ascii=False, indent=1))


def history() -> List[Dict[str, Any]]:
    """Las generaciones guardadas, más nuevas primero."""
    with _lock:
        items = _load().get("history", [])
    return [item for item in items if isinstance(item, dict)]


def add_to_history(form: Dict[str, Any], text: str, seconds: float, seed: Optional[int],
                   parent: Optional[str] = None, request: str = "") -> Dict[str, Any]:
    title = title_for(form)
    if request:
        title = f"↳ {request.strip()[:60]}{'…' if len(request.strip()) > 60 else ''}"
    entry = {
        "id": uuid.uuid4().hex[:12], "title": title, "created": time.time(), "form": form,
        "text": text, "words": len(text.split()), "seconds": round(seconds, 1), "seed": seed, "saved": False,
        "rating": "", "parent": parent or "", "request": request.strip(),
    }
    with _lock:
        data = _load()
        items = [item for item in data.get("history", []) if isinstance(item, dict)]
        items.insert(0, entry)
        unsaved = [i for i, item in enumerate(items) if not item.get("saved")]
        for i in reversed(unsaved[HISTORY_LIMIT:]):
            items.pop(i)
        data["history"] = items
        _save(data)
    return entry


def set_saved(entry_id: str, saved: bool) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _load()
        for item in data.get("history", []):
            if isinstance(item, dict) and item.get("id") == entry_id:
                item["saved"] = bool(saved)
                _save(data)
                return item
    return None


def get_entry(entry_id: str) -> Optional[Dict[str, Any]]:
    return next((item for item in history() if item.get("id") == entry_id), None)


def set_rating(entry_id: str, rating: str) -> Optional[Dict[str, Any]]:
    """"like", "dislike" o "" (sin valorar)."""
    if rating not in ("like", "dislike", ""):
        raise GeneratorError("Valoración desconocida.")
    with _lock:
        data = _load()
        for item in data.get("history", []):
            if isinstance(item, dict) and item.get("id") == entry_id:
                item["rating"] = rating
                _save(data)
                return item
    return None


def clean_request(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise GeneratorError("Escribe qué quieres cambiar.")
    return text.strip()[:MAX_REVISION_REQUEST]


def project_from_entry(entry: Dict[str, Any]):
    """Un proyecto de StoryForge con la historia: trama, personajes, ambientación y ajustes del
    formulario, y un capítulo por cada «Chapter N» del texto (o uno solo)."""
    import re

    from .project import Project

    form = entry.get("form") or {}
    name = (form.get("genre") or "Historia") + " — " + " ".join((form.get("plot") or entry.get("title", "")).split())[:40]
    project = Project(name=name.strip(" —") or "Historia", plot=form.get("plot", ""),
                      characters=form.get("characters", ""), setting=form.get("setting", ""))
    for field in ("genre", "theme", "tone", "point_of_view"):
        if form.get(field):
            setattr(project, field, form[field][:200])
    dialogue = dialogue_key(form.get("dialogue", -1))
    if dialogue:
        project.dialogue_balance = dialogue
    text = entry.get("text", "")
    parts = re.split(r"(?m)^\s*Chapter (\d+)\s*$", text)
    if len(parts) >= 3:  # [antes, "1", texto1, "2", texto2, ...]
        for index in range(1, len(parts), 2):
            body = parts[index + 1].strip()
            chapter = project.add_chapter(f"Capítulo {parts[index]}", target_words=max(MIN_WORDS, len(body.split())))
            chapter.content = body
    else:
        chapter = project.add_chapter("Capítulo 1", target_words=max(MIN_WORDS, len(text.split())))
        chapter.content = text.strip()
    return project


def delete_entry(entry_id: str) -> bool:
    with _lock:
        data = _load()
        items = data.get("history", [])
        kept = [item for item in items if not (isinstance(item, dict) and item.get("id") == entry_id)]
        if len(kept) == len(items):
            return False
        data["history"] = kept
        _save(data)
    return True


def presets() -> Dict[str, Dict[str, Any]]:
    """Los ejemplos incorporados y después los del usuario."""
    with _lock:
        user = _load().get("presets", {})
    out = {name: dict(values) for name, values in BUILTIN_PRESETS.items()}
    if isinstance(user, dict):
        out.update({str(name): values for name, values in user.items() if isinstance(values, dict)})
    return out


def save_preset(name: str, form: Dict[str, Any]) -> str:
    name = (name or "").strip()[:80]
    if not name:
        raise GeneratorError("El preset necesita un nombre.")
    if name in BUILTIN_PRESETS:
        raise GeneratorError("Ese nombre es de un ejemplo incorporado; elige otro.")
    with _lock:
        data = _load()
        stored = data.get("presets") if isinstance(data.get("presets"), dict) else {}
        stored[name] = form
        data["presets"] = stored
        _save(data)
    return name


def delete_preset(name: str) -> bool:
    with _lock:
        data = _load()
        stored = data.get("presets")
        if not isinstance(stored, dict) or name not in stored:
            return False
        del stored[name]
        _save(data)
    return True


def options() -> Dict[str, Any]:
    """Lo que la página necesita para dibujar el formulario."""
    return {
        "propositos": [{"valor": k, "etiqueta": v[0]} for k, v in PURPOSES.items()],
        "formatos": [{"valor": k, "etiqueta": v[0]} for k, v in FORMATS.items()],
        "largos": [{"valor": k, "etiqueta": v[0], "palabras": v[1]} for k, v in LENGTHS.items()],
        "palabras": {"min": MIN_WORDS, "max": MAX_WORDS},
        "capitulos_max": MAX_CHAPTERS,
        "idiomas": [{"valor": k, "etiqueta": LANGUAGE_LABELS[k]} for k in LANGUAGES],
        "campos_proposito": {purpose: [{"campo": f, "etiqueta": PURPOSE_FIELD_LABELS[f][0]} for f in fields]
                             for purpose, fields in PURPOSE_FIELDS.items()},
        "sugerencias": {field: list(story_settings.SUGGESTIONS[field])
                        for field in ("genre", "theme", "tone", "point_of_view")},
        "limites": FIELD_LIMITS,
        "presets": presets(),
    }
