"""
Analisis y reduccion de repeticion de palabras. Usa datos de NLTK (stopwords y
WordNet) que se buscan localmente en nltk_data/ junto a la app y, si no estan,
se descargan una sola vez (requiere internet solo esa vez). Si no hay datos ni
internet, la deteccion de repeticion sigue funcionando con una lista de
stopwords minima incluida, solo se pierde la sustitucion por sinonimos.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from .paths import app_root

_TOKEN_RE = re.compile(r"[A-Za-z']+")

_FALLBACK_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in",
    "on", "at", "for", "with", "as", "by", "is", "was", "were",
    "are", "be", "been", "being", "it", "its", "this", "that", "these",
    "those", "he", "she", "they", "him", "her", "them", "his", "hers",
    "their", "theirs", "i", "you", "we", "not", "so", "then", "than",
    "too", "very", "there", "here", "what", "which", "who", "whom",
    "into", "onto", "from", "about", "over", "under", "again", "once",
    "such", "each", "just", "some", "more", "most", "other", "only",
    "own", "same", "will", "would", "could", "should", "can", "did",
    "does", "doing", "have", "has", "had", "having", "your", "yours",
    "our", "ours",
}

_STOPWORDS_CACHE: Optional[set] = None
_NLTK_READY: Optional[bool] = None  # None = not checked yet, True/False = checked


def _local_nltk_data_dir() -> str:
    # app_root() y no "dos carpetas arriba de __file__": en el .exe eso
    # apuntaria a _internal\ en vez de a la carpeta del ejecutable.
    return os.path.join(app_root(), "nltk_data")


def _ensure_nltk_data() -> bool:
    """
    Intenta dejar disponibles los corpus de NLTK (stopwords, wordnet).
    Busca primero datos locales empaquetados junto a la app; si no existen y
    hay conexion a internet, intenta descargarlos una sola vez (uso normal en
    la PC del usuario). Si nada de esto funciona, la app sigue funcionando
    sin sustitucion de sinonimos. El resultado se cachea para no repetir
    intentos de red en cada llamada.
    """
    global _NLTK_READY
    if _NLTK_READY is not None:
        return _NLTK_READY
    try:
        import nltk
    except ImportError:
        _NLTK_READY = False
        return False

    local_dir = _local_nltk_data_dir()
    if os.path.isdir(local_dir) and local_dir not in nltk.data.path:
        nltk.data.path.insert(0, local_dir)

    def _has(resource: str) -> bool:
        try:
            nltk.data.find(resource)
            return True
        except LookupError:
            return False

    ok = _has("corpora/stopwords") and _has("corpora/wordnet")
    if not ok:
        try:
            nltk.download("stopwords", quiet=True, raise_on_error=True)
            nltk.download("wordnet", quiet=True, raise_on_error=True)
            ok = _has("corpora/stopwords") and _has("corpora/wordnet")
        except Exception:
            ok = False

    _NLTK_READY = ok
    return ok


def _get_stopwords() -> set:
    global _STOPWORDS_CACHE
    if _STOPWORDS_CACHE is not None:
        return _STOPWORDS_CACHE
    if _ensure_nltk_data():
        from nltk.corpus import stopwords as nltk_stopwords
        try:
            _STOPWORDS_CACHE = set(nltk_stopwords.words("english"))
            return _STOPWORDS_CACHE
        except LookupError:
            pass
    _STOPWORDS_CACHE = set(_FALLBACK_STOPWORDS)
    return _STOPWORDS_CACHE


def word_frequencies(text: str, min_length: int = 4) -> Counter:
    """Frecuencia de palabras significativas (sin stopwords, minusculas)."""
    stop = _get_stopwords()
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if len(t) >= min_length and t not in stop]
    return Counter(tokens)


def overused_words(text: str, per_1000_threshold: float = 4.0, min_length: int = 4) -> List[Tuple[str, int]]:
    """
    Devuelve palabras que aparecen mas de `per_1000_threshold` veces por cada
    1000 palabras del texto, ordenadas de mayor a menor frecuencia.
    """
    total_words = max(len(_TOKEN_RE.findall(text)), 1)
    freqs = word_frequencies(text, min_length=min_length)
    scale = 1000.0 / total_words
    flagged = [(w, c) for w, c in freqs.items() if c * scale >= per_1000_threshold and c >= 3]
    flagged.sort(key=lambda x: -x[1])
    return flagged


def _best_synonym(word: str, used: set) -> Optional[str]:
    """Busca un sinonimo de una sola palabra, del mismo 'tipo' aproximado,
    que no se haya usado ya, usando WordNet (offline una vez descargado)."""
    if not _ensure_nltk_data():
        return None
    from nltk.corpus import wordnet as wn

    candidates: Dict[str, int] = {}
    try:
        synsets = wn.synsets(word)
    except LookupError:
        return None
    for syn in synsets[:5]:
        for lemma in syn.lemmas():
            name = lemma.name().replace("_", " ")
            if " " in name:
                continue  # evitamos frases multi-palabra para no romper la gramatica
            if name.lower() == word.lower():
                continue
            if name.lower() in used:
                continue
            candidates[name] = candidates.get(name, 0) + 1
    if not candidates:
        return None
    # el sinonimo mas "comun" (aparece en mas synsets) suele encajar mejor
    best = max(candidates.items(), key=lambda kv: kv[1])[0]
    return best


def _match_case(replacement: str, original: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def reduce_repetition(text: str, per_1000_threshold: float = 4.0, max_replacements_per_word: int = 6) -> str:
    """
    Reescribe el texto sustituyendo repeticiones excesivas de una misma
    palabra por sinonimos (a partir de la 2a aparicion en adelante), usando
    WordNet local. Es una pasada basada en reglas, no un rewrite con IA:
    conserva la estructura de la oracion y solo cambia la palabra puntual.
    """
    flagged = overused_words(text, per_1000_threshold=per_1000_threshold)
    if not flagged:
        return text

    flagged_words = {w for w, _ in flagged}
    used_synonyms: set = set(flagged_words)
    seen_count: Dict[str, int] = Counter()

    def _replace(match: re.Match) -> str:
        original = match.group(0)
        lower = original.lower()
        if lower not in flagged_words:
            return original
        seen_count[lower] += 1
        # dejamos la primera aparicion intacta para no perder la palabra "ancla"
        if seen_count[lower] == 1:
            return original
        if seen_count[lower] > max_replacements_per_word:
            return original
        synonym = _best_synonym(lower, used_synonyms)
        if not synonym:
            return original
        used_synonyms.add(synonym.lower())
        return _match_case(synonym, original)

    return _TOKEN_RE.sub(_replace, text)


def repetition_report(text: str) -> str:
    """Genera un reporte legible de palabras sobreusadas, para mostrar en la GUI."""
    flagged = overused_words(text)
    if not flagged:
        return "No se detectaron palabras con repeticion excesiva."
    lines = ["Palabras usadas con mayor frecuencia de la recomendada:"]
    for word, count in flagged[:15]:
        lines.append(f"  - '{word}': {count} veces")
    return "\n".join(lines)
