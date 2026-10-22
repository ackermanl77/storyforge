"""Pasajes anteriores relevantes (B16): para novelas largas cuyos detalles se pierden en los resumenes.

Con "Recordar pasajes anteriores" (Project.recall_passages), cada prompt de capitulo lleva unos
pocos parrafos de los capitulos ANTERIORES elegidos por su parecido con lo que se va a escribir: el
titulo, el esquema y la nota de autor del capitulo y lo ultimo escrito. Asi un nombre, una promesa
o un objeto mencionados veinte capitulos atras vuelven a estar a la vista del modelo aunque el
resumen los haya dejado afuera.

El ranking es BM25 (puro Python, sin descargas: funciona bien con nombres propios y palabras raras)
o, si se eligio un modelo GGUF de embeddings (Trama > Modelo de embeddings…, settings.json), la
similitud coseno de sus vectores, que tambien encuentra pasajes parecidos con otras palabras. Los
vectores se calculan una vez por parrafo (cache en memoria por contenido). El modelo de embeddings
se carga en la CPU, aparte del modelo de escritura.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from .scenes import ai_text

logger = logging.getLogger(__name__)

MIN_PASSAGE_WORDS = 30
MAX_PASSAGE_WORDS = 160
QUERY_TAIL_WORDS = 150
VECTOR_CACHE_SIZE = 20000
_WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)
_STOPWORDS = frozenset(
    "the a an and or but of to in on at for with as by from is was were be been are it its he she they his her "
    "their them him i you we our your my me that this these those there then than so not no into over out up down "
    "had has have did do does said would could should will can just what when where who which while about "
    "el la los las un una unos unas y o pero de del a al en con por para es era fue son se su sus lo le les que "
    "como mas más ya no sí si ni muy entre sobre sin hasta desde cuando donde quien".split()
)


@dataclass(frozen=True)
class Passage:
    chapter_index: int
    text: str


def _words(text: str) -> List[str]:
    return [w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text)) if w not in _STOPWORDS and len(w) > 1]


def split_passages(project, upto_index: int) -> List[Passage]:
    """Los parrafos de los capitulos anteriores a `upto_index`, unidos los cortos (minimo
    MIN_PASSAGE_WORDS) y partidos los largos (maximo MAX_PASSAGE_WORDS palabras)."""
    passages: List[Passage] = []
    for index, chapter in enumerate(project.chapters[:max(0, upto_index)]):
        buffer: List[str] = []
        for paragraph in re.split(r"\n\s*\n", ai_text(chapter.content or "")):
            words = paragraph.split()
            while len(words) > MAX_PASSAGE_WORDS:
                passages.append(Passage(index, " ".join(words[:MAX_PASSAGE_WORDS])))
                words = words[MAX_PASSAGE_WORDS:]
            buffer.extend(words)
            if len(buffer) >= MIN_PASSAGE_WORDS:
                passages.append(Passage(index, " ".join(buffer)))
                buffer = []
        if buffer:
            if passages and passages[-1].chapter_index == index and len(buffer) < MIN_PASSAGE_WORDS:
                last = passages.pop()
                passages.append(Passage(index, f"{last.text} {' '.join(buffer)}"))
            else:
                passages.append(Passage(index, " ".join(buffer)))
    return passages


def bm25_scores(query: str, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> List[float]:
    tokenized = [_words(d) for d in documents]
    terms = set(_words(query))
    if not tokenized or not terms:
        return [0.0] * len(documents)
    average = sum(len(t) for t in tokenized) / len(tokenized) or 1.0
    frequency = Counter(term for tokens in tokenized for term in set(tokens) if term in terms)
    n = len(tokenized)
    scores = []
    for tokens in tokenized:
        counts = Counter(tokens)
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(tokens) / average))
        scores.append(score)
    return scores


# ---- embeddings opcionales ----
#: Prefijos que cada familia de modelos de embeddings espera en consultas y documentos (por el nombre
#: del archivo). bge: instruccion solo en la consulta; nomic y e5: una marca en cada lado.
EMBEDDING_PREFIXES = (
    ("nomic", "search_query: ", "search_document: "),
    ("e5", "query: ", "passage: "),
    ("bge", "Represent this sentence for searching relevant passages: ", ""),
)


def embedding_prefixes(model_path: str):
    name = model_path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for family, query, document in EMBEDDING_PREFIXES:
        if family in name:
            return query, document
    return "", ""


class GGUFEmbedder:
    """Un modelo GGUF de embeddings (p. ej. bge-small, nomic-embed, all-MiniLM) en la CPU."""

    def __init__(self, model_path: str):
        from llama_cpp import Llama

        self.model_path = model_path
        self.query_prefix, self.document_prefix = embedding_prefixes(model_path)
        self._llm = Llama(model_path=model_path, embedding=True, n_ctx=512, n_gpu_layers=0, verbose=False)
        self._lock = threading.Lock()

    def __call__(self, texts: Sequence[str], query: bool = False) -> List[List[float]]:
        prefix = self.query_prefix if query else self.document_prefix
        with self._lock:
            out = []
            for text in (prefix + t for t in texts):
                vector = self._llm.embed(text, normalize=True, truncate=True)
                if vector and isinstance(vector[0], list):  # algunos modelos devuelven un vector por token
                    vector = [sum(column) / len(vector) for column in zip(*vector)]
                out.append(list(vector))
            return out


_embedder: Optional[Callable[[Sequence[str]], List[List[float]]]] = None
_vectors: "OrderedDict[str, List[float]]" = OrderedDict()


def set_embedder(embedder: Optional[Callable[[Sequence[str]], List[List[float]]]]) -> None:
    """El modelo de embeddings a usar (None = BM25). Cambiarlo vacia la cache de vectores."""
    global _embedder
    _embedder = embedder
    _vectors.clear()


def embedder_active() -> bool:
    return _embedder is not None


def _vectors_for(texts: Sequence[str], query: bool = False) -> List[List[float]]:
    keys = [hashlib.sha1(f"{query}:{t}".encode("utf-8")).hexdigest() for t in texts]
    missing = [(k, t) for k, t in zip(keys, texts) if k not in _vectors]
    if missing:
        batch = [t for _k, t in missing]
        try:
            vectors = _embedder(batch, query=query)
        except TypeError:  # un embedder sin distincion consulta/documento
            vectors = _embedder(batch)
        for (key, _text), vector in zip(missing, vectors):
            _vectors[key] = vector
        while len(_vectors) > VECTOR_CACHE_SIZE:
            _vectors.popitem(last=False)
    return [_vectors[k] for k in keys]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


#: Con un modelo de embeddings, cuanto pesa ademas BM25 (normalizado a 0..1): los nombres propios
#: compartidos siguen contando aunque el modelo (chico) no los distinga bien.
HYBRID_BM25_WEIGHT = 0.15


def rank_passages(query: str, passages: Sequence[Passage]) -> List[float]:
    """Una puntuacion por pasaje: coseno con el modelo de embeddings mas un poco de BM25, o BM25 solo
    sin modelo (o si falla)."""
    lexical = bm25_scores(query, [p.text for p in passages])
    if _embedder is not None and passages:
        try:
            query_vector = _vectors_for([query], query=True)[0]
            top = max(lexical) or 1.0
            return [_cosine(query_vector, v) + HYBRID_BM25_WEIGHT * score / top
                    for v, score in zip(_vectors_for([p.text for p in passages]), lexical)]
        except Exception:  # noqa: BLE001 - un modelo que falla no debe impedir escribir
            logger.exception("El modelo de embeddings fallo; se usa BM25")
    return lexical


def recall_query(chapter, recent_text: str = "") -> str:
    tail = " ".join((recent_text or "").split()[-QUERY_TAIL_WORDS:])
    return "\n".join(part for part in (chapter.title, chapter.outline, chapter.author_note, tail) if part and part.strip())


def recall_passages(project, chapter_index: int, recent_text: str, max_words: int) -> List[Passage]:
    """Los pasajes anteriores mas relevantes que entran en `max_words`, en el orden de la historia."""
    if max_words <= 0 or chapter_index <= 0:
        return []
    passages = split_passages(project, chapter_index)
    query = recall_query(project.chapters[chapter_index], recent_text)
    if not passages or not query.strip():
        return []
    scores = rank_passages(query, passages)
    chosen, used = [], 0
    for score, position in sorted(((s, i) for i, s in enumerate(scores)), reverse=True):
        if score <= 0:
            break
        words = len(passages[position].text.split())
        if used + words > max_words:
            continue
        chosen.append(position)
        used += words
    return [passages[i] for i in sorted(chosen)]


def build_recall_block(project, chapter_index: int, recent_text: str, max_words: int) -> str:
    passages = recall_passages(project, chapter_index, recent_text, max_words)
    if not passages:
        return ""
    lines = "\n".join(f"[Chapter {p.chapter_index + 1}] {p.text}" for p in passages)
    return ("RELEVANT EARLIER PASSAGES (details established earlier in the story; stay consistent with "
            f"them, do not repeat them):\n{lines}")
