"""Tipos, errores y constantes del motor de generacion (R6: separados de engine.py, que los
reexporta con los mismos nombres; las pruebas que cambian p.ej. engine.SECTION_TARGET_WORDS
siguen cambiando lo que leen las operaciones de engine.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Union

from .prompts import (
    ChatPrompt,
)
from .sampling import (
    TASK_EXPAND,
    TASK_PROSE,
    TASK_REFINE,
)

PromptLike = Union[str, ChatPrompt]

# Tareas de prosa donde se cortan las frases a evitar (B15): escribir y
# continuar capitulos, expandir, refinar y reescribir; no esquemas ni resumenes.
PHRASE_GUARD_TASKS = (TASK_PROSE, TASK_EXPAND, TASK_REFINE)

# Valores de type_k/type_v de llama.cpp (enum ggml_type) para la cache KV.
GGML_KV_TYPES = {"f16": 1, "q8_0": 8, "q4_0": 2}
DEFAULT_N_BATCH = 512




class OperationCancelled(RuntimeError):
    """El usuario detuvo la operacion (boton Detener / Cancelar / Esc). La
    operacion no modifico nada: el llamador conserva el texto original."""


@dataclass
class GenerationStats:
    """
    Estadisticas de la operacion en curso (o la ultima), para la barra de
    estado: tokens/s, ETA, uso de la ventana de contexto y el prompt exacto
    enviado ("Ver prompt"). El motor las actualiza desde el hilo de trabajo;
    la interfaz las lee cada ~250 ms desde el hilo principal (solo lectura de
    atributos simples, seguro con el GIL).
    """
    operation: str = ""
    started_at: float = 0.0
    finished: bool = False
    calls: int = 0
    prompt_tokens: int = 0
    max_tokens: int = 0
    n_ctx: int = 0
    budget_level: int = 1  # nivel de CONTEXT_BUDGET_LEVELS usado (1 = el mas completo)
    prompt_text: str = ""
    generated_tokens: int = 0
    prompt_eval_seconds: float = 0.0  # de la ultima llamada (hasta el primer token)
    decode_seconds: float = 0.0  # acumulado, todas las llamadas
    phrase_rewinds: int = 0  # frases a evitar cortadas y reescritas (B15)
    seed: Optional[int] = None
    sampling: Dict[str, float] = field(default_factory=dict)
    words_written: int = 0
    target_words: int = 0
    part: int = 0
    total_parts: int = 0

    @property
    def tokens_per_second(self) -> Optional[float]:
        if self.decode_seconds <= 0 or self.generated_tokens <= 1:
            return None
        return self.generated_tokens / self.decode_seconds

    @property
    def context_fraction(self) -> Optional[float]:
        if not self.n_ctx:
            return None
        return min(1.0, (self.prompt_tokens + self.max_tokens) / self.n_ctx)

    @property
    def progress_fraction(self) -> Optional[float]:
        if self.target_words > 0:
            return min(1.0, self.words_written / self.target_words)
        if self.total_parts > 0:
            return min(1.0, max(0, self.part - 1) / self.total_parts)
        return None

    def eta_seconds(self) -> Optional[float]:
        """Segundos restantes estimados (solo capitulos: palabras que faltan x
        1.35 tokens/palabra / tokens por segundo)."""
        tps = self.tokens_per_second
        if not tps or self.target_words <= 0:
            return None
        remaining = max(0, self.target_words - self.words_written)
        return remaining * 1.35 / tps


@dataclass
class CompletionResult:
    """Texto generado (SIN recortar espacios) y por que termino: "stop"
    (fin natural o secuencia de corte), "length" (se agoto max_tokens),
    "cancelled", o None si el backend no lo informa (dobles de prueba)."""
    text: str
    finish_reason: Optional[str] = None

# Palabras por "seccion" que le pedimos al modelo en cada llamada. Pedir de
# mas puede degradar coherencia o exceder limites de generacion del modelo,
# asi que un capitulo largo se construye en varias pasadas.
SECTION_TARGET_WORDS = 900
MAX_SECTIONS_PER_CHAPTER = 14  # 14 * 900 ~= 12,600 palabras de margen
TOKENS_PER_WORD_ESTIMATE = 1.4
SAFETY_MARGIN_TOKENS = 64  # colchon para no rozar el limite exacto del modelo
OUTLINE_WORDS_PER_CHAPTER = 100  # presupuesto de salida por capitulo al generar el esquema
# Margen de salida al refinar: la version revisada puede salir algo mas larga
# que el original ("agrega mas dialogo"), asi que se reserva un 30% extra.
REFINE_OUTPUT_HEADROOM = 1.3
# Si el modelo termina una seccion por su cuenta (finish_reason "stop") y ya
# hay al menos esta fraccion del objetivo escrita, el capitulo se da por
# terminado en vez de pedir otra seccion (que tendia a escribir un segundo
# "final"). Por debajo, se pide seguir con un aviso de que no termine aun.
NATURAL_END_FRACTION = 0.8
# Una seccion que vuelve vacia (el modelo cerro su turno enseguida) se
# reintenta con otra semilla hasta estas veces por capitulo antes de rendirse;
# antes, la primera respuesta vacia terminaba el capitulo muy por debajo del
# objetivo (p.ej. 546 de 3000 palabras con Llama 3 8B).
MAX_EMPTY_SECTION_RETRIES = 3
NEW_PARAGRAPH = "\n\n"
# Largo minimo de una seccion que no es la ultima, como fraccion de su
# max_tokens: hasta ahi se bloquean los tokens de fin de turno del modelo.
# Muchos modelos instruct (p.ej. Llama 3 8B) cierran su respuesta a las ~500
# palabras pase lo que pase; sin esto, un capitulo de 3000 palabras terminaba
# con ~550 o se completaba con parrafos de cierre repetidos.
MIN_SECTION_FRACTION = 0.6
# Al cortar un texto por max_tokens se descarta la oracion incompleta del
# final solo si es corta (esta fraccion del texto como maximo): sin un
# limite de oracion cerca, se conserva todo.
MAX_DANGLING_FRACTION = 0.4
# Cuantos conteos de tokens (texto -> tokens) se recuerdan (P4).
TOKEN_CACHE_SIZE = 64

# Secuencias de corte por defecto de _complete() (prosa de un capitulo: que el
# modelo no empiece por su cuenta el capitulo siguiente). NO sirven para el
# esquema (cuyo formato es justamente "...\n\nChapter 2: ..." -- con estas se
# cortaba despues del capitulo 1), ni para refinar/expandir, donde un parrafo
# que empieza con "Chapter" es texto legitimo. Esas llamadas usan
# ONLY_END_MARKER_STOP.
DEFAULT_PROSE_STOP = [
    "\n\nCHAPTER", "\n\nChapter", "[END]",
    # El modelo saliendose de la historia para "despedirse" (visto con Llama 3 8B
    # cuando no lo dejaban terminar el turno): se corta ahi.
    "(To be continued", "(End of", "[Your Name]",
    # ...o para comentar el esquema ("(Note: this part continues with beat 4...").
    "(Note:",
    # ...o para hablarle al usuario (visto con daredevil-8b al cerrar una escena
    # sin poder terminar su turno). Al principio de parrafo, para no cortar dialogo.
    "\n\nPlease let me know", "\n\nLet me know if", "(Please note", "\n\nNext part:",
    "Thank you for the prompt", "\n\nI hope this meets", "\n\nI hope you enjoy",
    "Stay tuned for", "(still to come)", "\n\n**Note", "Note from the author",
]
ONLY_END_MARKER_STOP = ["[END]"]

# Niveles de presupuesto de contexto (en palabras) para plot/personajes/
# setting/resumen previo/esquema del capitulo/cola del capitulo en curso. Si
# el prompt no cabe en la ventana de contexto del modelo con el primer nivel,
# se reintenta con el siguiente (mas chico) antes de rendirse con un error
# claro. max_outline_words cubre chapter.outline: a diferencia de plot/
# personajes/setting, ese campo no tiene un limite propio en project.py (es
# texto libre editable en la pestana Esquema), asi que sin este recorte un
# esquema de capitulo inusualmente largo podia hacer que ni el nivel mas
# chico de presupuesto cupiera, con un error que sugeria enganosamente que
# "ya se redujo al minimo" cuando el esquema nunca se toco.
# refine_chapter() no usa estos niveles: nunca recorta el capitulo a revisar
# (antes lo hacia, y la version revisada reemplazaba el capitulo completo,
# perdiendo en silencio el final) -- si no cabe entero, lo revisa por partes.
# max_lore_words cubre el bloque de Lorebook / World Info (prompts.
# build_lorebook_block): igual que max_outline_words, se reduce junto con
# todo lo demas en cada nivel para que las entradas que coincidan (ver
# prompts.find_relevant_lore_entries) no sean, por si solas, lo que hace que
# ni el presupuesto mas chico quepa en la ventana de contexto del modelo.
CONTEXT_BUDGET_LEVELS = [
    dict(max_plot_words=1200, max_characters_words=600, max_setting_words=600, max_previous_words=500, max_outline_words=400, tail_words=400, max_lore_words=200, max_recall_words=400),
    dict(max_plot_words=700, max_characters_words=400, max_setting_words=400, max_previous_words=300, max_outline_words=250, tail_words=250, max_lore_words=120, max_recall_words=250),
    dict(max_plot_words=350, max_characters_words=200, max_setting_words=200, max_previous_words=150, max_outline_words=120, tail_words=150, max_lore_words=60, max_recall_words=120),
]


class ModelNotLoadedError(RuntimeError):
    pass


@dataclass(frozen=True)
class WordAlternative:
    """Una alternativa en una palabra del capitulo (F15): la palabra completa que el modelo
    escribiria ahi, la probabilidad de su primer token y ese token tal cual."""
    word: str
    probability: float
    token: str


#: Cuantas alternativas se piden y cuantos tokens se usan para completar cada una a palabra.
WORD_ALTERNATIVES = 8
WORD_COMPLETION_TOKENS = 6


class ContextOverflowError(RuntimeError):
    """El prompt necesario no cabe en la ventana de contexto del modelo cargado."""
