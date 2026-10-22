"""
Escenas dentro de un capitulo y texto que nunca va al modelo (F23).

Todo vive en el propio texto del capitulo, con marcas simples que se ven y se
editan en el editor -- asi la generacion, el historial de versiones, las
alternativas y el guardado no cambian:

- Una escena empieza con una linea de encabezado::

      ### La huida [POV: Ana]
      ### El sotano [archivada]

  `[POV: nombre]` dice desde quien se narra; `[archivada]` aparta la escena:
  queda en el capitulo, pero no va al modelo ni a la exportacion.

- Un tramo privado (notas, un borrador, algo que el modelo no debe ver) va
  entre ``[[privado]]`` y ``[[/privado]]``. Nunca va al modelo; al exportar
  se conserva el texto y se quitan las marcas.

`ai_text()` es lo que ve el modelo (prompts, resumenes, recuperacion de
pasajes); `export_text()` lo que va al manuscrito exportado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

PRIVATE_OPEN = "[[privado]]"
PRIVATE_CLOSE = "[[/privado]]"
_PRIVATE_RE = re.compile(r"\[\[\s*privado\s*\]\].*?(?:\[\[\s*/\s*privado\s*\]\]|\Z)", re.IGNORECASE | re.DOTALL)
_MARKER_RE = re.compile(r"\[\[\s*/?\s*privado\s*\]\]", re.IGNORECASE)
_HEADER_RE = re.compile(r"^###[ \t]+(?P<body>.*?)[ \t]*$", re.MULTILINE)
_TAG_RE = re.compile(r"\[(?P<tag>[^\]]*)\]")
SCENE_BREAK = "* * *"


@dataclass
class Scene:
    label: str
    pov: str
    archived: bool
    start: int  # offset del encabezado (0 si el capitulo no empieza con uno)
    end: int
    has_header: bool

    def display(self, number: int) -> str:
        text = f"{number}. {self.label or 'Escena sin título'}"
        if self.pov:
            text += f" — POV: {self.pov}"
        if self.archived:
            text += " (archivada)"
        return text


def _parse_header(body: str):
    label, pov, archived = _TAG_RE.sub("", body).strip(), "", False
    for match in _TAG_RE.finditer(body):
        tag = match.group("tag").strip()
        key, _, value = tag.partition(":")
        if key.strip().lower() == "pov" and value.strip():
            pov = value.strip()
        elif tag.lower() in ("archivada", "archivado", "archived"):
            archived = True
    return label, pov, archived


def split_scenes(text: str) -> List[Scene]:
    """Las escenas del capitulo. Sin encabezados, todo el texto es una escena
    sin titulo; el texto antes del primer encabezado tambien es una."""
    headers = list(_HEADER_RE.finditer(text or ""))
    scenes: List[Scene] = []
    if not headers or headers[0].start() > 0 and (text[: headers[0].start()].strip()):
        end = headers[0].start() if headers else len(text or "")
        scenes.append(Scene("", "", False, 0, end, False))
    for i, match in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        label, pov, archived = _parse_header(match.group("body"))
        scenes.append(Scene(label, pov, archived, match.start(), end, True))
    return scenes


def scene_header(label: str, pov: str = "", archived: bool = False) -> str:
    header = f"### {label.strip() or 'Escena'}"
    if pov.strip():
        header += f" [POV: {pov.strip()}]"
    if archived:
        header += " [archivada]"
    return header


def has_private(text: str) -> bool:
    return bool(_MARKER_RE.search(text or ""))


def has_hidden(text: str) -> bool:
    """True si hay algo que el modelo no debe ver (un tramo privado o una escena archivada)."""
    return has_private(text) or any(scene.archived for scene in split_scenes(text))


def _without_archived(text: str) -> str:
    if not any(scene.archived for scene in split_scenes(text)):
        return text
    parts = []
    for scene in split_scenes(text):
        if not scene.archived:
            parts.append(text[scene.start:scene.end])
    return "".join(parts)


def ai_text(text: str) -> str:
    """Lo que el modelo puede ver: sin tramos privados ni escenas archivadas
    (los encabezados de escena quedan: dan estructura y POV)."""
    if not text or not has_hidden(text):
        return text or ""
    visible = _PRIVATE_RE.sub("", _without_archived(text))
    return re.sub(r"\n{3,}", "\n\n", visible)


def export_text(text: str) -> str:
    """El texto exportado: sin escenas archivadas, los tramos privados sin sus
    marcas y cada encabezado de escena como un separador (salvo al inicio)."""
    if not text or ("[[" not in text and "###" not in text):
        return text or ""
    kept = _MARKER_RE.sub("", _without_archived(text))
    lines, seen_content = [], False
    for line in kept.split("\n"):
        if _HEADER_RE.fullmatch(line):
            if seen_content:
                lines.extend(["", SCENE_BREAK, ""])
            continue
        if line.strip():
            seen_content = True
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


def scene_at(text: str, offset: int) -> Optional[int]:
    """Indice de la escena que contiene `offset` (None si no hay texto)."""
    scenes = split_scenes(text)
    for index, scene in enumerate(scenes):
        if scene.start <= offset < scene.end or (index == len(scenes) - 1 and offset >= scene.start):
            return index
    return None
