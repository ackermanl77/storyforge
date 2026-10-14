"""Limpieza de lo que devuelve el modelo antes de agregarlo al capítulo.

Con un formato de chat que no coincide con el del modelo (p. ej. un GGUF sin
plantilla propia, donde "Auto" tiene que adivinar), algunos modelos no
continúan la prosa sino que "contestan" el mensaje: envuelven el texto en
bloques de código (```python), repiten las instrucciones de StoryForge ("The
chapter is already in progress...") o vuelven a escribir el final ya escrito
que se les mostró como contexto. Visto en un proyecto real con
NemoReRemix-12B (2026-10-14). `clean_section()` quita eso de cada sección:

- las líneas que son solo una cerca de código (``` o ```lenguaje);
- todo lo que viene desde la primera frase de las instrucciones de la app
  (si el modelo empezó a repetir el prompt, lo que sigue también es eco);
- al principio de la sección, las oraciones que ya están en el texto previo
  (el modelo "reinicia" repitiendo el final que ya estaba escrito).

Devuelve el texto limpio y qué se quitó, para registrarlo.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Frases de los prompts de app/prompts.py que nunca forman parte de la prosa.
PROMPT_MARKERS = (
    "The chapter is already in progress.",
    "The chapter written so far ends like this",
    "Your reply starts with the chapter's last lines",
    "Your reply starts from the exact point",
    "Continue it seamlessly from the exact point",
    "Continue seamlessly from the exact point",
    "[CHAPTER CONTINUED",
    "PROGRESS: about",
    "The chapter is not finished yet: do not write",
    "STEP-SPECIFIC CONTEXT",
    "STORY SETTINGS REMINDER",
    "AUTHOR'S NOTE (apply this",
    "Begin the chapter now",
    "Output only the chapter's prose",
    "THIS CHAPTER'S OUTLINE",
    "PROGRESS SO FAR:",
    "FORMATTING RULES (follow strictly)",
)
_FENCE_LINE = re.compile(r"^\s*```[\w+-]*\s*$", re.M)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]+[\"”’')\]]*|[^.!?\n]+$")
MIN_ECHO_WORDS = 6  # una oración tan corta puede repetirse a propósito ("No.")


ECHO_TAIL_WORDS = 600


def _is_echo_candidate(sentence: str) -> bool:
    """A complete sentence (ends in . ! ?, maybe then a quote) long enough to be a copy, not a phrase."""
    return len(sentence.split()) >= MIN_ECHO_WORDS and bool(re.search(r"[.!?][\"”’')\]]*\s*$", sentence))


def _normalize(sentence: str) -> str:
    return " ".join(sentence.lower().split())


def clean_section(piece: str, previous_text: str = "") -> Tuple[str, List[str]]:
    """(texto limpio, lista de lo que se quitó) -- ver el docstring del módulo."""
    removed: List[str] = []
    text = piece
    if _FENCE_LINE.search(text):
        text = _FENCE_LINE.sub("", text)
        removed.append("code fences")
    cut = min((i for i in (text.find(m) for m in PROMPT_MARKERS) if i >= 0), default=-1)
    if cut >= 0:
        line_start = text.rfind("\n", 0, cut) + 1
        text = text[:line_start] if text[line_start:cut].strip() == "" else text[:cut]
        removed.append("echoed instructions")
    if previous_text.strip():
        # Only complete sentences from the end the model was shown (the prompt's tail).
        tail = " ".join(previous_text.split()[-ECHO_TAIL_WORDS:])
        known = {_normalize(s) for s in _SENTENCE.findall(tail) if _is_echo_candidate(s)}
        position, dropped = 0, 0
        stripped = text.lstrip()
        offset = len(text) - len(stripped)
        for match in _SENTENCE.finditer(stripped):
            sentence = match.group(0)
            if not sentence.strip():
                continue
            if _is_echo_candidate(sentence) and _normalize(sentence) in known:
                position = match.end()
                dropped += 1
                continue
            break
        if dropped:
            text = text[: offset] + stripped[position:]
            removed.append(f"{dropped} repeated sentence(s)")
    if not removed:
        return piece, removed
    # A continued section is glued to the text before it as is: keep its leading space.
    lead = piece[: len(piece) - len(piece.lstrip())] if text.strip() else ""
    return lead + re.sub(r"\n{3,}", "\n\n", text).strip(), removed
