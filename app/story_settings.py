"""Ajustes de la historia: género, tema, tono, punto de vista y equilibrio
entre narración y diálogo, más los presets que los guardan juntos.

Cada campo es texto libre (el usuario puede escribir lo que quiera), con
sugerencias en la interfaz. Como la prosa se pide en inglés (ver
prompts.STYLE_GUIDE), las sugerencias conocidas se traducen a una instrucción
precisa en inglés (`english_value`): "primera persona" no es solo una
etiqueta sino "first person ("I"), ..."; un texto propio va tal cual (el
modelo lo entiende igual). `build_story_settings_block()` arma el bloque
STORY SETTINGS del prompt -- vacío si no hay nada elegido, así un proyecto
viejo produce exactamente el mismo prompt que antes.

Presets: unos incorporados (`BUILTIN_PRESETS`) y los del usuario, guardados
en settings.json bajo "story_presets". Un preset guarda estos cinco campos
y el tipo de escritura (project.writing_style).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import strings_es as S

STORY_SETTING_FIELDS = ("genre", "theme", "tone", "point_of_view", "dialogue_balance")
PRESET_FIELDS = STORY_SETTING_FIELDS + ("writing_style",)
MAX_SETTING_CHARS = 200
MAX_PRESETS = 50

# Sugerencias (texto que ve el usuario) -> instrucción en inglés.
GENRE_SUGGESTIONS: Dict[str, str] = {
    "Fantasía": "fantasy", "Ciencia ficción": "science fiction", "Thriller": "thriller",
    "Misterio": "mystery", "Policial": "crime fiction", "Terror": "horror", "Romance": "romance",
    "Romance histórico": "historical romance", "Histórica": "historical fiction", "Aventura": "adventure",
    "Drama": "literary drama", "Comedia": "comedy", "Distopía": "dystopian fiction",
    "Cuento infantil": "children's story", "Juvenil": "young adult fiction",
}
THEME_SUGGESTIONS: Dict[str, str] = {
    "Redención": "redemption", "Venganza": "revenge", "Amor y sacrificio": "love and sacrifice",
    "Identidad": "identity", "Poder y corrupción": "power and corruption", "Familia": "family",
    "Supervivencia": "survival", "Pérdida y duelo": "loss and grief", "Libertad": "freedom",
    "El bien contra el mal": "good versus evil", "Crecer": "coming of age", "Amistad": "friendship",
}
TONE_SUGGESTIONS: Dict[str, str] = {
    "Oscuro y misterioso": "dark and mysterious", "Tenso y de suspenso": "tense and suspenseful",
    "Melancólico": "melancholic", "Épico": "epic and grand", "Romántico": "romantic and warm",
    "Ligero y humorístico": "light-hearted and humorous", "Íntimo": "intimate and introspective",
    "Inquietante": "eerie and unsettling", "Esperanzador": "hopeful", "Irónico": "ironic and witty",
}
POINT_OF_VIEW_SUGGESTIONS: Dict[str, str] = {
    "Primera persona": 'first person ("I"), told by the protagonist, past tense',
    "Primera persona, presente": 'first person ("I"), told by the protagonist, present tense',
    "Tercera persona limitada": "third person limited: stay inside one viewpoint character per scene, past tense",
    "Tercera persona omnisciente": "third person omniscient: the narrator may enter any character's thoughts, past tense",
    "Segunda persona": 'second person ("you"), present tense',
}
SUGGESTIONS = {
    "genre": GENRE_SUGGESTIONS, "theme": THEME_SUGGESTIONS, "tone": TONE_SUGGESTIONS,
    "point_of_view": POINT_OF_VIEW_SUGGESTIONS,
}

# Equilibrio narración / diálogo: claves guardadas (sin acentos, como las de
# WRITING_STYLES) -> instrucción. "" = sin instrucción.
DIALOGUE_BALANCES = ("mucha_narracion", "mas_narracion", "equilibrado", "mas_dialogo", "mucho_dialogo")
DIALOGUE_INSTRUCTIONS = {
    "mucha_narracion": "Mostly narration: use dialogue sparingly, only for key moments.",
    "mas_narracion": "More narration than dialogue.",
    "equilibrado": "Balance narration and dialogue roughly evenly.",
    "mas_dialogo": "More dialogue than narration: let scenes unfold through what characters say.",
    "mucho_dialogo": "Mostly dialogue: tell the story through conversation, with brief narration between lines.",
}

BUILTIN_PRESETS: Dict[str, Dict[str, str]] = {
    "Thriller": {"genre": "Thriller", "theme": "Poder y corrupción", "tone": "Tenso y de suspenso",
                 "point_of_view": "Tercera persona limitada", "dialogue_balance": "equilibrado",
                 "writing_style": "Accion rapida"},
    "Romance": {"genre": "Romance", "theme": "Amor y sacrificio", "tone": "Romántico",
                "point_of_view": "Primera persona", "dialogue_balance": "mas_dialogo", "writing_style": "Narrativa"},
    "Terror": {"genre": "Terror", "theme": "Supervivencia", "tone": "Inquietante",
               "point_of_view": "Primera persona", "dialogue_balance": "mas_narracion", "writing_style": "Descriptiva"},
    "Fantasía épica": {"genre": "Fantasía", "theme": "El bien contra el mal", "tone": "Épico",
                       "point_of_view": "Tercera persona omnisciente", "dialogue_balance": "equilibrado",
                       "writing_style": "Descriptiva"},
    "Misterio policial": {"genre": "Policial", "theme": "Identidad", "tone": "Oscuro y misterioso",
                          "point_of_view": "Primera persona", "dialogue_balance": "mas_dialogo",
                          "writing_style": "Narrativa"},
    "Ciencia ficción": {"genre": "Ciencia ficción", "theme": "Libertad", "tone": "Inquietante",
                        "point_of_view": "Tercera persona limitada", "dialogue_balance": "equilibrado",
                        "writing_style": "Creativa"},
    "Cuento infantil": {"genre": "Cuento infantil", "theme": "Amistad", "tone": "Ligero y humorístico",
                        "point_of_view": "Tercera persona omnisciente", "dialogue_balance": "mas_dialogo",
                        "writing_style": "Narrativa"},
}


def english_value(field: str, value: str) -> str:
    """La instrucción en inglés de una sugerencia conocida (sin distinguir
    mayúsculas), o el texto tal cual."""
    value = (value or "").strip()
    for label, english in SUGGESTIONS.get(field, {}).items():
        if label.lower() == value.lower():
            return english
    return value


def clean_settings(data: dict) -> Dict[str, str]:
    """Los campos de PRESET_FIELDS de `data`, como texto recortado (valores
    inválidos de dialogue_balance quedan en "")."""
    out: Dict[str, str] = {}
    for field in PRESET_FIELDS:
        value = data.get(field, "") if isinstance(data, dict) else ""
        value = value.strip()[:MAX_SETTING_CHARS] if isinstance(value, str) else ""
        if field == "dialogue_balance" and value not in DIALOGUE_BALANCES:
            value = ""
        out[field] = value
    return out


def build_story_settings_block(project) -> str:
    """El bloque STORY SETTINGS del prompt (vacío si no hay ningún ajuste)."""
    lines: List[str] = []
    for field, label in (("genre", "Genre"), ("theme", "Theme"), ("tone", "Tone")):
        value = english_value(field, getattr(project, field, ""))
        if value:
            lines.append(f"{label}: {value}")
    pov = english_value("point_of_view", getattr(project, "point_of_view", ""))
    if pov:
        lines.append(f"Point of view: {pov}. Keep this point of view consistently.")
    dialogue = DIALOGUE_INSTRUCTIONS.get(getattr(project, "dialogue_balance", ""), "")
    if dialogue:
        lines.append(f"Dialogue: {dialogue}")
    if not lines:
        return ""
    return "STORY SETTINGS (follow them throughout):\n" + "\n".join(lines) + "\n\n"


# ---------------- presets ----------------
def user_presets() -> Dict[str, Dict[str, str]]:
    from .settings import load_settings

    raw = load_settings().get("story_presets")
    if not isinstance(raw, dict):
        return {}
    return {str(name)[:80]: clean_settings(values) for name, values in raw.items() if isinstance(values, dict)}


def all_presets() -> Dict[str, Dict[str, str]]:
    """Los incorporados y después los del usuario (uno del usuario con el mismo
    nombre reemplaza al incorporado)."""
    presets = {name: clean_settings(values) for name, values in BUILTIN_PRESETS.items()}
    presets.update(user_presets())
    return presets


def save_user_preset(name: str, values: dict) -> str:
    """Guarda (o reemplaza) un preset del usuario; devuelve el nombre usado."""
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError(S.PRESET_SIN_NOMBRE)

    def mutate(data: dict) -> None:
        presets = data.get("story_presets") if isinstance(data.get("story_presets"), dict) else {}
        if name not in presets and len(presets) >= MAX_PRESETS:
            raise ValueError(S.DEMASIADOS_PRESETS.format(max=MAX_PRESETS))
        presets[name] = clean_settings(values)
        data["story_presets"] = presets

    _update_or_raise(mutate)
    return name


def delete_user_preset(name: str) -> bool:
    """Borra un preset del usuario; False si no existe (los incorporados no se borran)."""
    if name not in user_presets():
        return False

    def mutate(data: dict) -> None:
        presets = data.get("story_presets")
        if isinstance(presets, dict):
            presets.pop(name, None)

    _update_or_raise(mutate)
    return True


def _update_or_raise(mutator) -> None:
    from .settings import load_settings, save_settings

    data = load_settings()
    mutator(data)
    save_settings(data)


def apply_preset(project, values: dict) -> None:
    """Copia un preset al proyecto (writing_style solo si es un tipo conocido)."""
    from .project import WRITING_STYLES

    clean = clean_settings(values)
    for field in STORY_SETTING_FIELDS:
        setattr(project, field, clean[field])
    if clean["writing_style"] in WRITING_STYLES or clean["writing_style"] == "":
        project.writing_style = clean["writing_style"]


def preset_from_project(project) -> Dict[str, str]:
    return clean_settings({field: getattr(project, field, "") for field in PRESET_FIELDS})


def dialogue_label(key: Optional[str]) -> str:
    return S.DIALOGUE_LABELS.get(key or "", S.DIALOGUE_DEFAULT_LABEL)


def dialogue_key(label: str) -> str:
    return next((k for k, v in S.DIALOGUE_LABELS.items() if v == label), "")
