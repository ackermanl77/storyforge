"""
Herramientas del lorebook y de revision, sin modelo ni interfaz:

- Deteccion de personajes (F22): nombres propios que se repiten en un
  capitulo y que ninguna entrada del lorebook reconoce todavia.
- Relaciones y alias (F24): "familia: Ana" una por linea; los alias son
  claves de busqueda mas (LoreEntry.keyword_list).
- Menciones (F24): en que capitulos aparece cada entrada.
- Comentarios del editor (F21): la respuesta del modelo convertida en notas
  con el pasaje al que se refieren.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .scenes import ai_text

# Palabras con mayuscula que no son nombres (inicio de oracion, dias, titulos...),
# en espanol e ingles. Comparadas en minusculas.
_NOT_NAMES = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "pero", "si", "no", "que", "qué", "como",
    "cómo", "cuando", "cuándo", "donde", "dónde", "quien", "quién", "por", "para", "con", "sin", "de", "del",
    "al", "en", "a", "mi", "tu", "su", "sus", "mis", "tus", "nuestro", "nuestra", "este", "esta", "estos",
    "estas", "ese", "esa", "eso", "esto", "aquel", "aquella", "ya", "luego", "entonces", "después", "antes",
    "así", "aquí", "allí", "ahí", "también", "tampoco", "nunca", "siempre", "todo", "toda", "todos", "todas",
    "nada", "algo", "alguien", "nadie", "cada", "otro", "otra", "otros", "otras", "yo", "él", "ella", "ellos",
    "ellas", "nosotros", "vosotros", "usted", "ustedes", "le", "les", "lo", "me", "te", "se", "nos", "os",
    "sí", "bueno", "claro", "vale", "hola", "adiós", "gracias", "señor", "señora", "señorita", "don", "doña",
    "capítulo", "escena", "fin", "dios", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado",
    "domingo", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre", "the", "a", "an", "and", "or", "but", "if", "then", "when", "where",
    "what", "who", "why", "how", "he", "she", "it", "they", "we", "you", "i", "his", "her", "their", "our",
    "my", "your", "this", "that", "these", "those", "there", "here", "not", "no", "yes", "oh", "well", "chapter",
    "mr", "mrs", "ms", "dr", "sir", "lady", "lord", "god", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}
_CONNECTORS = {"de", "del", "la", "las", "los", "van", "von", "da", "di", "le", "of", "the", "y"}
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’\-]*")
_SENTENCE_END = re.compile(r"[.!?¡¿…:;\"«»—–\n]\s*$")


@dataclass
class NameCandidate:
    name: str
    count: int
    example: str  # una oracion donde aparece


def _known_terms(entries) -> List[str]:
    terms = []
    for entry in entries:
        terms.append(entry.name)
        terms.extend(entry.keyword_list())
    return [t.lower() for t in terms if t.strip()]


def detect_new_names(text: str, entries=(), min_count: int = 2, limit: int = 20) -> List[NameCandidate]:
    """Nombres propios (palabras -- o grupos como "Ana de la Torre" -- con
    mayuscula que no estan al inicio de una oracion) que aparecen al menos
    `min_count` veces en `text` y que no reconoce ninguna entrada (nombre,
    palabra clave o alias). Ordenados por frecuencia."""
    text = ai_text(text or "")
    known = _known_terms(entries)
    counts: Counter = Counter()
    examples: Dict[str, str] = {}
    for sentence in re.split(r"(?<=[.!?…])\s+|\n+", text):
        words = list(_WORD_RE.finditer(sentence))
        i = 0
        while i < len(words):
            word = words[i].group()
            prefix = sentence[: words[i].start()]
            sentence_start = not prefix.strip() or bool(_SENTENCE_END.search(prefix))
            if word[0].isupper() and word.lower() not in _NOT_NAMES and not sentence_start:
                parts, j = [word], i + 1
                while j < len(words):
                    nxt = words[j].group()
                    gap = sentence[words[j - 1].end(): words[j].start()]
                    if gap.strip():
                        break
                    if nxt[0].isupper() and nxt.lower() not in _NOT_NAMES:
                        parts.append(nxt)
                        j += 1
                    elif nxt.lower() in _CONNECTORS and j + 1 < len(words) and words[j + 1].group()[0].isupper():
                        parts.append(nxt)
                        j += 1
                    else:
                        break
                while parts and parts[-1].lower() in _CONNECTORS:
                    parts.pop()
                name = " ".join(parts)
                counts[name] += 1
                examples.setdefault(name, sentence.strip())
                i = j
            else:
                i += 1
    candidates = []
    for name, count in counts.most_common():
        lower = name.lower()
        if count < min_count or len(name) < 2:
            continue
        if any(term == lower or term in lower.split() or lower in term.split() for term in known):
            continue
        candidates.append(NameCandidate(name, count, examples[name][:200]))
        if len(candidates) >= limit:
            break
    return candidates


# ---------------- relaciones y menciones (F24) ----------------

def parse_relations(text: str) -> List[Dict[str, str]]:
    """'familia: Ana' / 'facción -> Los Lobos' por linea -> [{"type", "target"}]."""
    relations = []
    for line in (text or "").splitlines():
        line = line.strip(" -•\t")
        if not line:
            continue
        match = re.match(r"^(?P<type>[^:>]+?)\s*(?::|->|→)\s*(?P<target>.+)$", line)
        if match:
            relations.append({"type": match.group("type").strip()[:40], "target": match.group("target").strip()[:80]})
        else:
            relations.append({"type": "relacionado con", "target": line[:80]})
    return relations[:30]


def format_relations(relations) -> str:
    return "\n".join(f"{r['type']}: {r['target']}" for r in relations or [])


def clean_relations(value) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    clean = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("target"), str) and item["target"].strip():
            clean.append({"type": str(item.get("type") or "relacionado con")[:40], "target": item["target"].strip()[:80]})
    return clean[:30]


def mention_counts(chapters, entry) -> List[Tuple[int, int]]:
    """[(numero de capitulo, menciones)] de los capitulos donde aparece alguna
    clave de `entry` (nombre, palabras clave, alias), palabra completa."""
    terms = [t for t in {entry.name.strip(), *entry.keyword_list()} if t]
    if not terms:
        return []
    pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")(?!\w)",
                         re.IGNORECASE)
    result = []
    for number, chapter in enumerate(chapters, start=1):
        count = len(pattern.findall(chapter.content or ""))
        if count:
            result.append((number, count))
    return result


# ---------------- comentarios del editor (F21) ----------------

FEEDBACK_AREAS = ("ritmo", "claridad", "diálogo", "voz", "continuidad", "descripción", "estructura")


@dataclass
class FeedbackNote:
    area: str
    quote: str  # un fragmento literal del capitulo ("" si el modelo no cito)
    note: str


_FEEDBACK_LINE = re.compile(
    r"^\s*(?:[-*•]|\d+[.)])?\s*\[(?P<area>[^\]]+)\]\s*(?:[«\"“](?P<quote>[^»\"”]+)[»\"”])?\s*[—–:-]*\s*(?P<note>.+)$"
)


def parse_feedback(text: str) -> List[FeedbackNote]:
    """Las notas de la respuesta del modelo (una por linea: `[area] «cita» — nota`).
    Las lineas que no siguen el formato se agregan a la nota anterior."""
    notes: List[FeedbackNote] = []
    for line in (text or "").splitlines():
        match = _FEEDBACK_LINE.match(line)
        if match:
            notes.append(FeedbackNote(match.group("area").strip().lower(), (match.group("quote") or "").strip(),
                                      match.group("note").strip()))
        elif line.strip() and notes:
            notes[-1].note += " " + line.strip()
    return notes


def locate_quote(content: str, quote: str) -> Optional[Tuple[int, int]]:
    """(inicio, fin) del fragmento citado en el capitulo, sin distinguir
    mayusculas ni espacios; None si el modelo no cito literalmente."""
    if not quote.strip():
        return None
    words = [re.escape(w) for w in quote.split()]
    if not words:
        return None
    match = re.search(r"\s+".join(words), content or "", re.IGNORECASE)
    if match is None and len(words) > 6:
        match = re.search(r"\s+".join(words[:6]), content or "", re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def notes_summary(notes: Sequence[FeedbackNote]) -> str:
    return "\n".join(f"[{n.area}] {('«' + n.quote + '» ') if n.quote else ''}{n.note}" for n in notes)
