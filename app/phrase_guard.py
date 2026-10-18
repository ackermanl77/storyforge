"""
Frases a evitar (B15): clichés que los modelos locales repiten ("her heart
skipped a beat", "...would change her life forever"), cortados mientras se
generan, como el phrase banning ("anti-slop") de KoboldCpp.

Cuando el texto generado completa una frase de la lista, el motor
(engine._complete_guarded) detiene la generación, retrocede hasta justo
antes de la frase y sigue desde ahí con la primera palabra de la frase
prohibida en esa posición, así el modelo elige otra forma de decirlo. Al
transmitir, se retienen los últimos caracteres (PhraseGuard.max_span) para
que una frase que se va a cortar nunca llegue a verse en pantalla.

Formato de una frase: palabras separadas por espacios, sin distinguir
mayúsculas; "*" es de 1 a 3 palabras cualquiera ("change * life forever"
cubre "change her whole life forever"). No puede empezar con "*".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

# Una lista corta y deliberadamente específica: cada frase es un cliché casi
# siempre evitable, no una construcción normal del idioma.
DEFAULT_BANNED_PHRASES = (
    # English
    "heart skipped a beat",
    "heart * skipped a beat",
    "sent shivers down * spine",
    "a shiver ran down * spine",
    "breath * didn't know * was holding",
    "change * life forever",
    "changed * life forever",
    "life would never be the same",
    "nothing would ever be the same",
    "would never be the same again",
    "little did * know",
    "a testament to",
    "barely above a whisper",
    "only time would tell",
    "the calm before the storm",
    "eyes sparkled with mischief",
    "palpable tension",
    "a tapestry of",
    "maybe, just maybe",
    # Español
    "el corazón le dio un vuelco",
    "un escalofrío le recorrió la espalda",
    "contuvo el aliento sin darse cuenta",
    "cambiaría su vida para siempre",
    "cambió su vida para siempre",
    "nada volvería a ser igual",
    "apenas un susurro",
    "solo el tiempo lo diría",
    "la calma antes de la tormenta",
)

MAX_PHRASES = 200
MAX_PHRASE_CHARS = 80
# Palabras que cubre un "*" como máximo, y su ancho máximo en caracteres.
WILDCARD_WORDS = 3
_WILDCARD_CHARS = 15 * WILDCARD_WORDS
# Retrocesos por llamada al modelo antes de aceptar el texto como quedó, y por
# posición (si el modelo insiste en la misma frase en el mismo lugar).
MAX_REWINDS = 12
MAX_REWINDS_AT_ONE_POINT = 3

_APOSTROPHES = "'’"


def clean_phrases(lines: Iterable[str]) -> List[str]:
    """Frases válidas y sin repetir, en orden: recortadas, sin "*" inicial ni
    final, con al menos una palabra real."""
    out: List[str] = []
    seen = set()
    for line in lines:
        phrase = " ".join(str(line).split())[:MAX_PHRASE_CHARS].strip(" *")
        key = phrase.lower()
        if not phrase or key in seen or not any(ch.isalnum() for ch in phrase):
            continue
        seen.add(key)
        out.append(phrase)
        if len(out) >= MAX_PHRASES:
            break
    return out


def _word_pattern(word: str) -> str:
    """Una palabra literal; cualquier apóstrofo (' o ’) acepta los dos."""
    return "".join(f"[{_APOSTROPHES}]" if ch in _APOSTROPHES else re.escape(ch) for ch in word)


def _compile(phrase: str) -> "re.Pattern[str]":
    parts = []
    for word in phrase.split():
        if word == "*":
            parts.append(rf"(?:[^\s]+\s+){{1,{WILDCARD_WORDS}}}")
        else:
            parts.append(_word_pattern(word) + r"\s+")
    body = "".join(parts)
    body = body[: -len(r"\s+")]  # sin espacio tras la última palabra
    lead = r"\b" if phrase[0].isalnum() else ""
    tail = r"\b" if phrase[-1].isalnum() else ""
    return re.compile(lead + body + tail, re.IGNORECASE)


@dataclass
class PhraseMatch:
    start: int
    end: int
    phrase: str

    @property
    def first_word(self) -> str:
        return self.phrase.split()[0]


@dataclass
class PhraseGuard:
    phrases: List[str]
    _patterns: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.phrases = clean_phrases(self.phrases)
        self._patterns = [(_compile(p), p) for p in self.phrases]

    @property
    def max_span(self) -> int:
        """Lo más largo que puede medir una coincidencia: lo que se retiene al transmitir."""
        longest = 0
        for phrase in self.phrases:
            words = phrase.split()
            longest = max(longest, len(phrase) + words.count("*") * _WILDCARD_CHARS + 2 * len(words))
        return longest + 2

    def search(self, text: str, start: int = 0) -> Optional[PhraseMatch]:
        """La coincidencia que empieza primero en `text[start:]` (la más larga si empatan)."""
        best: Optional[PhraseMatch] = None
        for pattern, phrase in self._patterns:
            m = pattern.search(text, max(0, start))
            if m and (best is None or m.start() < best.start or (m.start() == best.start and m.end() > best.end)):
                best = PhraseMatch(m.start(), m.end(), phrase)
        return best

    def __bool__(self) -> bool:
        return bool(self.phrases)

    @classmethod
    def for_project(cls, project) -> Optional["PhraseGuard"]:
        """La lista de un proyecto: las frases por defecto (si avoid_cliches) más
        las suyas. None si no queda ninguna."""
        phrases: List[str] = []
        if getattr(project, "avoid_cliches", True):
            phrases += list(DEFAULT_BANNED_PHRASES)
        phrases += list(getattr(project, "banned_phrases", []) or [])
        guard = cls(phrases)
        return guard or None


def word_variants(word: str) -> Sequence[str]:
    """Las formas en que la primera palabra de una frase puede empezar un token:
    con o sin espacio delante, en minúscula y con mayúscula inicial."""
    forms = {word.lower(), word[:1].upper() + word[1:].lower()}
    return sorted({prefix + form for form in forms for prefix in (" ", "")})
