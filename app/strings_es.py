"""
Textos de la interfaz en espanol que se comparten entre modulos, y las
etiquetas visibles de valores que se GUARDAN en los proyectos.

Los tipos de escritura y propositos de capitulo se guardan sin acentos
("Dialogo", "Escena climatica"...) desde las primeras versiones: esas claves
no cambian (los proyectos viejos tienen que seguir cargando y los prompts
las usan como clave), pero el usuario ve la version bien escrita.

Glosario elegido para la interfaz: se conservan "Plot", "Setting" y
"Lorebook" (son los nombres de pestana que ya usan la guia y el README, y
terminos habituales en herramientas de escritura con IA); el resto va en
espanol con acentos y tuteo ("puedes", nunca "podes").
"""
from __future__ import annotations

from typing import Dict

from .project import CHAPTER_PURPOSES, WRITING_STYLES

APP_NAME = "StoryForge Local"

STYLE_LABELS: Dict[str, str] = {
    "Narrativa": "Narrativa",
    "Descriptiva": "Descriptiva",
    "Creativa": "Creativa",
    "Dialogo": "Diálogo",
    "Poetica": "Poética",
    "Accion rapida": "Acción rápida",
}

PURPOSE_LABELS: Dict[str, str] = {
    "Apertura": "Apertura",
    "Escena climatica": "Escena climática",
    "Final": "Final",
    "Epilogo": "Epílogo",
}

WRITING_STYLE_DEFAULT_LABEL = "(Por defecto)"
CHAPTER_PURPOSE_DEFAULT_LABEL = "(Capítulo regular)"

CHAPTER_HEADING_LABELS: Dict[str, str] = {
    "Chapter": "Chapter N: título",
    "Capítulo": "Capítulo N: título",
    "": "Solo el título",
}

HISTORY_SOURCE_LABELS: Dict[str, str] = {
    "generate": "generar",
    "continue": "continuar",
    "refine": "refinar",
    "reduce": "reducir repetición",
    "restore": "restaurar versión",
    "rewrite": "reescribir selección",
    "replace": "reemplazar texto",
    "retry": "reintentar",
}

assert set(STYLE_LABELS) == set(WRITING_STYLES)
assert set(PURPOSE_LABELS) == set(CHAPTER_PURPOSES)


def style_label(key: str) -> str:
    return STYLE_LABELS.get(key, WRITING_STYLE_DEFAULT_LABEL) if key else WRITING_STYLE_DEFAULT_LABEL


def style_key(label: str) -> str:
    """Clave guardada para una etiqueta visible (acepta tambien la clave)."""
    if label in STYLE_LABELS:
        return label
    for key, value in STYLE_LABELS.items():
        if value == label:
            return key
    return ""


def purpose_label(key: str) -> str:
    return PURPOSE_LABELS.get(key, CHAPTER_PURPOSE_DEFAULT_LABEL) if key else CHAPTER_PURPOSE_DEFAULT_LABEL


def purpose_key(label: str) -> str:
    if label in PURPOSE_LABELS:
        return label
    for key, value in PURPOSE_LABELS.items():
        if value == label:
            return key
    return ""


def history_source_label(source: str) -> str:
    """"refine: hazlo mas oscuro" -> "refinar: hazlo mas oscuro"."""
    if not source:
        return ""
    kind, _, detail = source.partition(":")
    label = HISTORY_SOURCE_LABELS.get(kind.strip(), kind.strip())
    return f"{label}: {detail.strip()}" if detail.strip() else label


STYLE_OPTIONS = [WRITING_STYLE_DEFAULT_LABEL] + [STYLE_LABELS[k] for k in WRITING_STYLES]
PURPOSE_OPTIONS = [CHAPTER_PURPOSE_DEFAULT_LABEL] + [PURPOSE_LABELS[k] for k in CHAPTER_PURPOSES]

# Formas sin acento (o con voseo) que NO deben aparecer en textos visibles de
# la interfaz -- ver tests/test_strings_es.py.
UNACCENTED_FORMS = [
    r"\bcapitulos?\b", r"\bpestana\b", r"\bningun\b", r"\bproposito\b", r"\bnumero\b",
    r"\bversion\b", r"\breduccion\b", r"\brepeticion\b", r"\bgeneracion\b", r"\bseccion\b",
    r"\binstruccion\b", r"\btitulo\b", r"\bbusqueda\b", r"\bultim[ao]s?\b", r"\bdespues\b",
    r"\btambien\b", r"\baqui\b", r"\bpodes\b", r"\binvalido\b", r"\bmaximo\b", r"\bminimo\b",
    r"\bautomatico\b", r"\bresumenes\b", r"\btodavia\b", r"\bvacio\b", r"\bdialogo\b",
    r"\bepilogo\b", r"\bclimatica\b", r"\bpoetica\b", r"\baccion\b",
]
