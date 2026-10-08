"""
Motor de generacion local, usando llama-cpp-python sobre un modelo GGUF que el
usuario descarga por separado y coloca en la carpeta models/. No requiere
internet en tiempo de generacion.
"""
from __future__ import annotations

import gc
import glob
import os
import random
import re
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

from . import strings_es as S
from .chat_format import (
    CHAT_FORMAT_AUTO,
    ChatFormatter,
    RawFormatter,
    detect_formatter,
    preset_formatter,
)
from .gguf import KV_CACHE_TYPES, friendly_load_error, list_model_entries, missing_shards, model_info
from .project import MAX_CHAPTERS, MAX_WORDS_PER_CHAPTER, Project, count_words
from .prompts import (
    FINAL_SECTION_HINT,
    NOT_OVER_NUDGE,
    ChatPrompt,
    build_beat_progress_hint,
    build_chapter_continuation_chat,
    build_chapter_start_chat,
    build_combine_summaries_chat,
    build_expand_field_chat,
    build_outline_chat,
    build_outline_completion_chat,
    build_partial_summary_chat,
    build_refine_chapter_chat,
    build_rewrite_span_chat,
    build_summary_chat,
    parse_outline_response,
)
from .sampling import (
    MAX_SEED,
    TASK_EXPAND,
    TASK_OUTLINE,
    TASK_PROSE,
    TASK_REFINE,
    TASK_SUMMARY,
    SamplingConfig,
)

PromptLike = Union[str, ChatPrompt]

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
DEFAULT_PROSE_STOP = ["\n\nCHAPTER", "\n\nChapter", "[END]"]
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
    dict(max_plot_words=1200, max_characters_words=600, max_setting_words=600, max_previous_words=500, max_outline_words=400, tail_words=400, max_lore_words=200),
    dict(max_plot_words=700, max_characters_words=400, max_setting_words=400, max_previous_words=300, max_outline_words=250, tail_words=250, max_lore_words=120),
    dict(max_plot_words=350, max_characters_words=200, max_setting_words=200, max_previous_words=150, max_outline_words=120, tail_words=150, max_lore_words=60),
]


class ModelNotLoadedError(RuntimeError):
    pass


class ContextOverflowError(RuntimeError):
    """El prompt necesario no cabe en la ventana de contexto del modelo cargado."""


_cuda_dlls_prepared = False


def _ensure_cuda_dlls_discoverable() -> None:
    """A CUDA-enabled llama-cpp-python wheel (see README's "Rendimiento / GPU"
    section) bundles ggml-cuda.dll, which needs the CUDA runtime DLLs
    (cudart64_*.dll/cublas64_*.dll/cublasLt64_*.dll) at import time -- not
    just when a model is actually offloaded to GPU. Those DLLs aren't bundled
    in the wheel itself; the standalone `nvidia-cuda-runtime`/`nvidia-cublas`
    pip packages provide them instead (no full CUDA Toolkit install needed).

    llama_cpp's own loader (_ctypes_extensions.py) calls
    `ctypes.CDLL(..., winmode=ctypes.RTLD_GLOBAL)` -- on Windows RTLD_GLOBAL
    is 0, and passing winmode=0 makes ctypes use the legacy DLL search order,
    which ignores directories registered via `os.add_dll_directory()` (that
    only applies under the "safe search mode" flags). The legacy search order
    does still consult PATH, so prepending the DLL directory there (in
    addition to add_dll_directory, for forward compatibility if that bug gets
    fixed upstream) is what actually makes the import succeed -- confirmed by
    reproducing llama_cpp's exact load call directly.

    A CPU-only environment (no `nvidia-*` packages installed, or the default
    PyPI CPU-only wheel) hits none of this: the glob below just finds nothing
    and the import proceeds exactly as it always did.

    Two package layouts exist: the CUDA 13 packages nest the DLLs one level
    deeper (nvidia/cu13/bin/x86_64/*.dll), while the CUDA 12 ones
    (nvidia-cublas-cu12 etc.) put them directly in nvidia/<pkg>/bin/*.dll --
    both are checked (see find_nvidia_dll_dirs()).
    """
    global _cuda_dlls_prepared
    if _cuda_dlls_prepared or sys.platform != "win32":
        return
    _cuda_dlls_prepared = True

    for site_packages in (p for p in sys.path if p.endswith("site-packages")):
        for dll_dir in find_nvidia_dll_dirs(site_packages):
            try:
                os.add_dll_directory(dll_dir)
            except OSError:
                pass
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")


def find_nvidia_dll_dirs(site_packages: str) -> List[str]:
    """Carpetas bajo site-packages/nvidia que contienen DLLs, en cualquiera de
    los dos layouts conocidos: nvidia/<pkg>/bin/*.dll (CUDA 12) o
    nvidia/<pkg>/bin/<arch>/*.dll (CUDA 13)."""
    found: List[str] = []
    patterns = (
        os.path.join(site_packages, "nvidia", "*", "bin"),
        os.path.join(site_packages, "nvidia", "*", "bin", "*"),
    )
    for pattern in patterns:
        for dll_dir in sorted(glob.glob(pattern)):
            if os.path.isdir(dll_dir) and glob.glob(os.path.join(dll_dir, "*.dll")):
                found.append(dll_dir)
    return found


def supports_gpu_offload() -> bool:
    """Whether the installed llama-cpp-python build can actually offload
    layers to a GPU -- used by the GUI to pick a sensible default for
    n_gpu_layers instead of always defaulting to CPU-only (0)."""
    _ensure_cuda_dlls_discoverable()
    try:
        from llama_cpp import llama_cpp as _llama_cpp_lib
    except Exception:
        # Not just ImportError: when a CUDA build's DLLs can't be resolved, llama_cpp raises
        # RuntimeError("Failed to load shared library ...") from its import. This runs while the
        # GUI is being built, so it must degrade to "no GPU" rather than crash the app at startup.
        return False
    try:
        return bool(_llama_cpp_lib.llama_supports_gpu_offload())
    except Exception:
        return False


def find_local_models(models_dir: str) -> List[str]:
    """Rutas cargables de models_dir: una por modelo (la primera parte de un
    modelo partido en varios archivos); los modelos partidos incompletos no
    se incluyen (ver gguf.list_model_entries para la lista completa con
    etiquetas)."""
    return [e.path for e in list_model_entries(models_dir) if e.complete]


class LocalStoryEngine:
    """Envuelve un modelo GGUF cargado con llama-cpp-python."""

    def __init__(self) -> None:
        self._llm = None
        self._model_path: Optional[str] = None
        self._n_ctx: int = 8192  # valor por defecto hasta que se cargue un modelo
        # Formato de chat elegido (ver app/chat_format.py) y el formateador
        # resuelto para el modelo actual. Se resuelve de forma diferida, la
        # primera vez que hace falta, para el _llm que este cargado en ese
        # momento (las pruebas inyectan _llm directamente, sin load()).
        self._chat_format_choice: str = CHAT_FORMAT_AUTO
        self._formatter: Optional[ChatFormatter] = None
        self._formatter_llm = None
        # finish_reason de la ultima llamada al modelo (ver CompletionResult).
        self.last_finish_reason: Optional[str] = None
        # Muestreo por tarea + semilla (ver app/sampling.py). La interfaz lo
        # reemplaza con el del proyecto abierto.
        self.sampling = SamplingConfig()
        # Semilla usada por la ultima operacion (la elegida o la aleatoria).
        self.last_seed: Optional[int] = None
        self._op_seed: Optional[int] = None
        # "Detener" global: cualquier llamada en curso lo revisa en cada token.
        self._stop_event = threading.Event()
        self.stats = GenerationStats()
        self.load_options: Dict[str, object] = {}
        self.model_info = None
        # Cache de conteo de tokens (P4): los bloques fijos de un prompt se
        # vuelven a medir en cada seccion y en cada intento de presupuesto.
        self._token_cache: "OrderedDict[str, int]" = OrderedDict()
        self._token_cache_llm = None
        self._prompt_cache = None
        self._prompt_cache_llm = None

    # ---------------- detener / estadisticas ----------------
    def request_stop(self) -> None:
        """Pide detener la operacion en curso (se nota en el proximo token)."""
        self._stop_event.set()

    def clear_stop(self) -> None:
        self._stop_event.clear()

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def begin_operation(self, name: str, target_words: int = 0) -> GenerationStats:
        """Reinicia las estadisticas y elige la semilla de esta operacion:
        la fija del proyecto, o una aleatoria (que queda en last_seed para
        poder repetir el resultado)."""
        seed = self.sampling.seed
        if seed is None:
            seed = random.randint(0, MAX_SEED)
        self._op_seed = seed
        self.last_seed = seed
        self.stats = GenerationStats(
            operation=name, started_at=time.monotonic(), n_ctx=self._n_ctx, seed=seed,
            target_words=target_words,
        )
        return self.stats

    def _end_operation(self) -> None:
        self.stats.finished = True

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    @property
    def model_path(self) -> Optional[str]:
        return self._model_path

    @property
    def n_ctx(self) -> int:
        return self._n_ctx

    def load(self, model_path: str, n_ctx: int = 8192, n_threads: Optional[int] = None,
              n_gpu_layers: int = 0, chat_format: Optional[str] = None,
              flash_attn: Optional[bool] = None, n_batch: Optional[int] = None,
              n_ubatch: Optional[int] = None, kv_cache_type: str = "f16") -> None:
        """
        Carga un GGUF. `n_ctx=0` usa el contexto con el que se entreno el
        modelo (leido de la cabecera). Opciones de rendimiento (pestana
        Modelo > Avanzado): `flash_attn` (por defecto: activado si hay
        offload a GPU), `n_batch`/`n_ubatch` (tamano de lote al procesar el
        prompt) y `kv_cache_type` ("f16", "q8_0" o "q4_0"; las cuantizadas
        requieren flash attention, porque llama.cpp no admite una cache V
        cuantizada sin ella).
        """
        if kv_cache_type not in KV_CACHE_TYPES:
            raise ValueError(S.CACHE_KV_DESCONOCIDA.format(kv_cache_type=kv_cache_type))
        if flash_attn is None:
            flash_attn = n_gpu_layers != 0
        if kv_cache_type != "f16" and not flash_attn:
            raise ValueError(
                S.CACHE_KV_REQUIERE_FLASH_ATTENTION.format(kv_cache_type=kv_cache_type)
            )
        for name, value in (("n_batch", n_batch), ("n_ubatch", n_ubatch)):
            if value is not None and value <= 0:
                raise ValueError(S.DEBE_SER_ENTERO_POSITIVO.format(name=name))
        if n_ctx < 0:
            raise ValueError(S.N_CTX_NEGATIVO)
        if chat_format is not None:
            self.set_chat_format(chat_format)
        try:
            _ensure_cuda_dlls_discoverable()
            from llama_cpp import Llama
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                S.FALTA_LLAMA_CPP
            ) from exc
        except Exception as exc:
            # Un build de llama-cpp-python con CUDA cuyas DLLs de runtime
            # (cudart/cublas) no se encuentran NO lanza ImportError, sino
            # RuntimeError("Failed to load shared library ...") u OSError
            # desde el propio import -- antes eso llegaba al usuario como un
            # mensaje crudo en ingles sin pista de como resolverlo.
            raise RuntimeError(
                S.LLAMA_CPP_SIN_LIBRERIA.format(exc=exc)
            ) from exc

        if not os.path.isfile(model_path):
            raise FileNotFoundError(S.MODELO_NO_ENCONTRADO.format(model_path=model_path))
        missing = missing_shards(model_path)
        if missing:
            raise RuntimeError(
                S.MODELO_FALTAN_PARTES.format(parts=', '.join(map(str, missing)))
            )
        info = model_info(model_path)
        if n_ctx == 0 and not info.trained_context:
            n_ctx = 8192

        # Soltamos el modelo anterior (si habia uno) antes de reservar memoria
        # para el nuevo: construir el Llama nuevo antes de liberar el viejo
        # tendria ambos modelos completos en RAM/VRAM a la vez, lo cual para
        # modelos de varios GB puede agotar la memoria disponible.
        self.unload()

        kwargs = dict(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        # Solo se pasan si difieren de los valores por defecto de llama.cpp,
        # asi un doble de prueba (o una version vieja) sin esos argumentos
        # sigue funcionando.
        if flash_attn:
            kwargs["flash_attn"] = True
        if n_batch:
            kwargs["n_batch"] = n_batch
        if n_ubatch:
            kwargs["n_ubatch"] = n_ubatch
        if kv_cache_type != "f16":
            kwargs["type_k"] = GGML_KV_TYPES[kv_cache_type]
            kwargs["type_v"] = GGML_KV_TYPES[kv_cache_type]
        try:
            self._llm = Llama(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(friendly_load_error(exc, model_path)) from exc
        self._model_path = model_path
        # El contexto REAL (con n_ctx=0, llama.cpp usa el del entrenamiento).
        actual = None
        n_ctx_getter = getattr(self._llm, "n_ctx", None)
        if callable(n_ctx_getter):
            try:
                actual = int(n_ctx_getter())
            except Exception:  # noqa: BLE001
                actual = None
        self._n_ctx = actual if actual and actual > 0 else (n_ctx or info.trained_context or 8192)
        self.model_info = info
        self.load_options = dict(
            n_ctx=self._n_ctx, n_threads=n_threads, n_gpu_layers=n_gpu_layers,
            flash_attn=bool(flash_attn), n_batch=n_batch, n_ubatch=n_ubatch, kv_cache_type=kv_cache_type,
        )
        self._ensure_prompt_cache()

    def unload(self) -> None:
        llm = self._llm
        self._llm = None
        self._model_path = None
        self._formatter = None
        self._formatter_llm = None
        self.model_info = None
        self._token_cache.clear()
        self._prompt_cache = None
        self._prompt_cache_llm = None
        # Llama.close() (llama-cpp-python >= 0.2.8x) libera la VRAM/RAM del
        # modelo en el momento, en vez de depender de cuando pase el
        # recolector de basura -- load() llama a unload() justamente para no
        # tener dos modelos residentes a la vez.
        close = getattr(llm, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
        if llm is not None:
            del llm
            gc.collect()

    # ---------------- formato de chat ----------------
    @property
    def chat_format_choice(self) -> str:
        return self._chat_format_choice

    def set_chat_format(self, choice: str) -> None:
        """Elige el formato de chat ("auto", "llama3", "raw", ... -- ver
        app/chat_format.py). Se aplica en la proxima llamada al modelo."""
        self._chat_format_choice = choice or CHAT_FORMAT_AUTO
        self._formatter = None
        self._formatter_llm = None

    def _has_special_token(self, text: str) -> bool:
        """True si `text` es UN solo token especial del vocabulario del
        modelo cargado (p.ej. "<|start_header_id|>" en Llama 3)."""
        try:
            tokens = self._llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)
        except Exception:  # noqa: BLE001 - dobles de prueba sin tokenize()
            return False
        return len(tokens) == 1

    def _special_token_text(self, token_id_getter: str) -> str:
        try:
            token_id = getattr(self._llm, token_id_getter)()
            if token_id is None or token_id < 0:
                return ""
            return self._llm.detokenize([token_id], special=True).decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return ""

    @property
    def formatter(self) -> ChatFormatter:
        """Formateador de chat para el modelo cargado ahora (resuelto una vez
        por modelo). Sin modelo, o con un doble de prueba sin metadatos ni
        tokenizador, "auto" resuelve a completion cruda."""
        if self._formatter is not None and self._formatter_llm is self._llm:
            return self._formatter
        if self._llm is None:
            return RawFormatter()
        if self._chat_format_choice == CHAT_FORMAT_AUTO:
            metadata = getattr(self._llm, "metadata", None)
            formatter = detect_formatter(
                metadata if isinstance(metadata, dict) else {},
                self._has_special_token,
                bos_token=self._special_token_text("token_bos"),
                eos_token=self._special_token_text("token_eos"),
            )
        else:
            formatter = preset_formatter(self._chat_format_choice)
        self._formatter = formatter
        self._formatter_llm = self._llm
        return formatter

    def render_prompt(self, prompt: PromptLike) -> str:
        """El texto exacto que se enviaria al modelo para `prompt`."""
        if isinstance(prompt, str):
            return prompt
        return self.formatter.render(prompt)

    def _ensure_prompt_cache(self) -> None:
        """
        Habilita la cache de estados de llama-cpp-python cuando existe.

        La misma instancia de `Llama` ya reutiliza el prefijo comun de dos
        llamadas consecutivas; esta cache amplifica ese beneficio cuando se
        intercalan otras llamadas (por ejemplo resumenes) y luego se vuelve a
        un prompt que comparte gran parte de su prefijo.
        """
        if self._llm is None or self._prompt_cache_llm is self._llm:
            return
        self._prompt_cache = None
        set_cache = getattr(self._llm, "set_cache", None)
        if callable(set_cache):
            try:
                from llama_cpp import LlamaRAMCache
                self._prompt_cache = LlamaRAMCache()
                set_cache(self._prompt_cache)
            except Exception:  # noqa: BLE001
                self._prompt_cache = None
        self._prompt_cache_llm = self._llm

    # ---------------- manejo de contexto / tokens ----------------
    def _count_tokens(self, text: str) -> int:
        """
        Cuenta tokens usando el tokenizador real del modelo cuando esta
        disponible; si no (modelo no soporta tokenize, o esta simulado en
        pruebas), cae a una estimacion por palabras.
        """
        if self._llm is not None:
            if self._token_cache_llm is not self._llm:
                self._token_cache.clear()
                self._token_cache_llm = self._llm
            cached = self._token_cache.get(text)
            if cached is not None:
                self._token_cache.move_to_end(text)
                return cached
            try:
                count = len(self._llm.tokenize(text.encode("utf-8", errors="ignore")))
            except Exception:
                count = None
            if count is not None:
                self._token_cache[text] = count
                while len(self._token_cache) > TOKEN_CACHE_SIZE:
                    self._token_cache.popitem(last=False)
                return count
        return int(len(text.split()) * TOKENS_PER_WORD_ESTIMATE)

    def _available_context(self, reserved_for_output: int) -> int:
        """Tokens que quedan libres para el prompt de entrada."""
        return self._n_ctx - reserved_for_output - SAFETY_MARGIN_TOKENS

    def _fit_text_to_token_budget(self, text: str, available_tokens: int) -> str:
        """
        Recorta `text` para que quepa en `available_tokens`, conservando el
        inicio (planteamiento) y el final (lo mas reciente/desenlace) en vez
        de cortar a ciegas por un solo extremo.
        """
        if available_tokens <= 0:
            return ""
        if self._count_tokens(text) <= available_tokens:
            return text
        words = text.split()
        approx_words = max(int(available_tokens / TOKENS_PER_WORD_ESTIMATE), 40)
        if len(words) <= approx_words:
            return text
        trimmed = self._head_tail_join(words, approx_words)
        # Si el tokenizador real cuenta mas tokens por palabra que la
        # estimacion, hay que achicar el TOTAL de palabras conservadas en cada
        # pasada (antes solo se movian palabras de la cabeza a la cola, con el
        # total constante, asi que el bucle nunca lograba que cupiera).
        while self._count_tokens(trimmed) > available_tokens and approx_words > 1:
            approx_words = int(approx_words * 0.8)
            trimmed = self._head_tail_join(words, approx_words)
        return trimmed

    @staticmethod
    def _head_tail_join(words: List[str], keep_words: int) -> str:
        head = keep_words // 2
        tail = keep_words - head
        # words[-0:] devolveria la lista COMPLETA, no una vacia.
        tail_words = words[-tail:] if tail > 0 else []
        return " ".join(words[:head]) + " [...] " + " ".join(tail_words)

    def _complete(
        self,
        prompt: PromptLike,
        max_tokens: int,
        stop: Optional[List[str]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        task: str = TASK_PROSE,
    ) -> str:
        """Igual que _complete_ex(), pero devuelve solo el texto, recortado.
        Si el usuario detuvo la operacion, lanza OperationCancelled (el texto
        parcial de un resumen/refinado/esquema no sirve)."""
        result = self._complete_ex(prompt, max_tokens, stop, on_token, cancel_check, task=task)
        if result.finish_reason == "cancelled":
            raise OperationCancelled(S.OPERACION_DETENIDA_POR_EL_USUARIO)
        return result.text.strip()

    def _is_cancelled(self, cancel_check: Optional[Callable[[], bool]]) -> bool:
        return self._stop_event.is_set() or bool(cancel_check and cancel_check())

    def _sampling_kwargs(self, task: str) -> dict:
        kwargs = self.sampling.for_task(task).to_kwargs()
        seed = self._op_seed if self._op_seed is not None else self.sampling.seed
        if seed is not None:
            kwargs["seed"] = seed
        return kwargs

    def _complete_ex(
        self,
        prompt: PromptLike,
        max_tokens: int,
        stop: Optional[List[str]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        task: str = TASK_PROSE,
    ) -> CompletionResult:
        """
        Una llamada al modelo. `prompt` puede ser texto ya armado o un
        ChatPrompt, que se renderiza con el formato de chat del modelo (ver
        render_prompt). Devuelve el texto SIN recortar (al continuar desde un
        texto pre-llenado, el espacio inicial es parte de la continuacion) y
        el finish_reason que informa llama.cpp ("cancelled" si se detuvo).

        Usa el muestreo de `task` (app/sampling.py) y la semilla de la
        operacion (begin_operation). Se pide streaming si hay alguien
        escuchando tokens o alguien que pueda cancelar (cancel_check), asi
        "Detener" corta a mitad de la respuesta.
        """
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)
        self._ensure_prompt_cache()

        text_prompt = self.render_prompt(prompt)
        prompt_tokens = self._count_tokens(text_prompt)
        available = self._available_context(max_tokens)
        if prompt_tokens > available:
            raise ContextOverflowError(
                S.CONTEXTO_NO_CABE.format(prompt_tokens=prompt_tokens, n_ctx=self._n_ctx, max_tokens=max_tokens)
            )
        if self._is_cancelled(cancel_check):
            self.last_finish_reason = "cancelled"
            return CompletionResult("", "cancelled")

        stops = list(stop or DEFAULT_PROSE_STOP)
        if not isinstance(prompt, str):
            stops += [s for s in self.formatter.stop if s and s not in stops]
        call_kwargs = dict(max_tokens=max_tokens, stop=stops)
        call_kwargs.update(self._sampling_kwargs(task))
        # Solo pedimos streaming token a token (llama_cpp.Llama.__call__(...,
        # stream=True), que devuelve un generador en vez de un dict) cuando
        # hay alguien escuchando o alguien que puede cancelar.
        if on_token is not None or cancel_check is not None:
            call_kwargs["stream"] = True

        stats = self.stats
        stats.calls += 1
        stats.prompt_tokens = prompt_tokens
        stats.max_tokens = max_tokens
        stats.n_ctx = self._n_ctx
        stats.prompt_text = text_prompt
        stats.seed = call_kwargs.get("seed")
        stats.sampling = {k: v for k, v in call_kwargs.items() if k not in ("stop", "stream", "max_tokens", "seed")}
        call_start = time.monotonic()

        response = self._llm(text_prompt, **call_kwargs)

        if isinstance(response, dict):
            # Respuesta no incremental: ya sea porque no se pidio streaming,
            # o porque _llm (p.ej. un doble de prueba) devolvio el resultado
            # completo de una. Si hay on_token, se le entrega el texto
            # completo de una sola vez.
            choice = response["choices"][0]
            text = choice.get("text", "")
            elapsed = time.monotonic() - call_start
            usage = response.get("usage") or {}
            stats.generated_tokens += int(usage.get("completion_tokens") or (self._count_tokens(text) if text else 0))
            stats.decode_seconds += elapsed
            if on_token is not None and text:
                on_token(text)
            self.last_finish_reason = choice.get("finish_reason")
            return CompletionResult(text, self.last_finish_reason)

        # Streaming real: `response` es un generador de fragmentos, cada uno
        # con un delta incremental de texto (NO acumulado; ~1 token cada
        # uno). El ultimo trae finish_reason. La cancelacion se revisa en
        # cada fragmento, asi que Cancelar/Detener corta a mitad de una seccion.
        pieces: List[str] = []
        finish_reason: Optional[str] = None
        first_token_at: Optional[float] = None
        try:
            for chunk in response:
                if self._is_cancelled(cancel_check):
                    finish_reason = "cancelled"
                    break
                now = time.monotonic()
                if first_token_at is None:
                    first_token_at = now
                    stats.prompt_eval_seconds = now - call_start
                    decode_base = stats.decode_seconds
                stats.generated_tokens += 1
                stats.decode_seconds = decode_base + (now - first_token_at)
                choice = chunk["choices"][0]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                delta = choice.get("text", "")
                if not delta:
                    continue
                pieces.append(delta)
                if on_token is not None:
                    on_token(delta)
        finally:
            # Cortar el generador de llama-cpp-python lo cierra limpiamente.
            close = getattr(response, "close", None)
            if finish_reason == "cancelled" and callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
        self.last_finish_reason = finish_reason
        return CompletionResult("".join(pieces), finish_reason)

    def _complete_with_shrinking_budget(
        self,
        prompt_for_budget: Callable[[dict], PromptLike],
        max_tokens: int,
        on_token: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        stop: Optional[List[str]] = None,
        task: str = TASK_PROSE,
    ) -> str:
        result = self._complete_with_shrinking_budget_ex(
            prompt_for_budget, max_tokens, on_token, cancel_check, stop, task=task,
        )
        if result.finish_reason == "cancelled":
            raise OperationCancelled(S.OPERACION_DETENIDA_POR_EL_USUARIO)
        return result.text.strip()

    def _complete_with_shrinking_budget_ex(
        self,
        prompt_for_budget: Callable[[dict], PromptLike],
        max_tokens: int,
        on_token: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        stop: Optional[List[str]] = None,
        task: str = TASK_PROSE,
    ) -> CompletionResult:
        """
        Intenta completar con cada nivel de CONTEXT_BUDGET_LEVELS (de mayor a
        menor contexto incluido) hasta que uno quepa en la ventana de
        contexto del modelo. `prompt_for_budget` recibe un dict de budget y
        devuelve el prompt completo a intentar con ese nivel.
        """
        last_error: Optional[Exception] = None
        for level, budget in enumerate(CONTEXT_BUDGET_LEVELS, start=1):
            self.stats.budget_level = level
            try:
                return self._complete_ex(
                    prompt_for_budget(budget), max_tokens=max_tokens, stop=stop,
                    on_token=on_token, cancel_check=cancel_check, task=task,
                )
            except ContextOverflowError as exc:
                last_error = exc
                continue
        raise ContextOverflowError(
            S.CONTEXTO_NO_CABE_NI_REDUCIDO
        ) from last_error

    def generate_outline(
        self, project: Project, num_chapters: int,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> List[Tuple[str, str]]:
        """
        Genera un esquema (beat sheet) de toda la historia antes de escribir
        prosa: una lista de (titulo, beats) por capitulo. Lanza
        prompts.OutlineParseError si la respuesta no tiene ningun encabezado
        de capitulo reconocible, y OperationCancelled si se detuvo. Despues
        de llamar, `last_finish_reason == "length"` indica que la respuesta
        se corto por max_tokens (el esquema puede tener menos capitulos de
        los pedidos; ver complete_outline()).
        """
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)

        self.begin_operation("Esquema")
        num_chapters = max(1, min(int(num_chapters), MAX_CHAPTERS))
        max_tokens = int(num_chapters * OUTLINE_WORDS_PER_CHAPTER * TOKENS_PER_WORD_ESTIMATE) + 60

        def prompt_for_budget(budget: dict) -> ChatPrompt:
            return build_outline_chat(
                project, num_chapters,
                max_plot_words=budget["max_plot_words"],
                max_characters_words=budget["max_characters_words"],
                max_setting_words=budget["max_setting_words"],
            )

        # stop explicito: con el corte por defecto ("\n\nChapter") el modelo
        # se detenia justo al empezar "Chapter 2:" y el esquema salia con un
        # solo capitulo.
        try:
            raw = self._complete_with_shrinking_budget(
                prompt_for_budget, max_tokens, on_token=on_token, cancel_check=cancel_check,
                stop=ONLY_END_MARKER_STOP, task=TASK_OUTLINE,
            )
        finally:
            self._end_operation()
        return parse_outline_response(raw, num_chapters)

    def complete_outline(
        self, project: Project, num_chapters: int, existing: List[Tuple[str, str]],
        cancel_check: Optional[Callable[[], bool]] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> List[Tuple[str, str]]:
        """
        "Completar capitulos faltantes": cuando el esquema salio con menos
        capitulos de los pedidos (respuesta cortada), pide solo los que
        faltan, con los ya planeados como contexto. Devuelve SOLO los
        capitulos nuevos (a lo sumo num_chapters - len(existing)).
        """
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)
        num_chapters = max(1, min(int(num_chapters), MAX_CHAPTERS))
        missing = num_chapters - len(existing)
        if missing <= 0:
            return []
        self.begin_operation("Completar esquema")
        max_tokens = int(missing * OUTLINE_WORDS_PER_CHAPTER * TOKENS_PER_WORD_ESTIMATE) + 60

        def prompt_for_budget(budget: dict) -> ChatPrompt:
            return build_outline_completion_chat(
                project, num_chapters, existing,
                max_plot_words=budget["max_plot_words"],
                max_characters_words=budget["max_characters_words"],
                max_setting_words=budget["max_setting_words"],
            )

        try:
            raw = self._complete_with_shrinking_budget(
                prompt_for_budget, max_tokens, on_token=on_token, cancel_check=cancel_check,
                stop=ONLY_END_MARKER_STOP, task=TASK_OUTLINE,
            )
        finally:
            self._end_operation()
        items = parse_outline_response(raw, MAX_CHAPTERS)
        # Si el modelo repitio capitulos ya planeados al principio, se
        # descartan los que coinciden por titulo.
        known = {title.strip().lower() for title, _ in existing}
        items = [item for item in items if item[0].strip().lower() not in known]
        return items[:missing]

    # ---------------- capitulos ----------------
    def _dynamic_tail_words(
        self, build: Callable[[int], ChatPrompt], full_text: str, min_tail: int, max_tokens: int,
    ) -> int:
        """
        Cuantas palabras del capitulo en curso caben en el prompt de
        continuacion: despues de medir los bloques fijos (biblia, esquema,
        instrucciones), se llena el espacio libre de la ventana de contexto
        con todo lo que quepa del texto ya escrito, medido en tokens reales.
        Nunca menos que `min_tail` (el tamano fijo del nivel de presupuesto):
        si ni eso cabe, el nivel de presupuesto siguiente se encarga.
        """
        total_words = len(full_text.split())
        if total_words <= min_tail:
            return min_tail
        limit = self._available_context(max_tokens)
        fixed = self._count_tokens(self.render_prompt(build(0)))
        free = limit - fixed
        words = min(total_words, MAX_WORDS_PER_CHAPTER, int(free / TOKENS_PER_WORD_ESTIMATE))
        if words <= min_tail:
            return min_tail
        while words > min_tail and self._count_tokens(self.render_prompt(build(words))) > limit:
            words = int(words * 0.85)
        return max(words, min_tail)

    @staticmethod
    def _trim_dangling_sentence(text: str) -> Tuple[str, bool]:
        """
        Si `text` termina a mitad de una oracion (cortado por max_tokens),
        descarta ese fragmento final siempre que haya un fin de oracion
        cerca (ver MAX_DANGLING_FRACTION). Devuelve (texto, se_recorto).
        """
        stripped = text.rstrip()
        if not stripped or stripped[-1] in ".!?\"”*)":
            return stripped, False
        last_end = max(stripped.rfind(p) for p in (". ", "! ", "? ", ".\"", "!\"", "?\"",
                                                    ".”", "!”", "?”", ".\n", "!\n", "?\n"))
        if last_end < 0:
            return stripped, False
        cut = last_end + 2 if stripped[last_end + 1] in "\"”" else last_end + 1
        if len(stripped) - cut > len(stripped) * MAX_DANGLING_FRACTION:
            return stripped, False
        return stripped[:cut].rstrip(), True

    def generate_chapter(
        self,
        project: Project,
        chapter_index: int,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        resume_from: Optional[str] = None,
    ) -> str:
        """
        Genera un capitulo por secciones (~SECTION_TARGET_WORDS cada una)
        hasta acercarse al objetivo de palabras (o MAX_SECTIONS_PER_CHAPTER).

        - `resume_from`: texto ya escrito del capitulo desde el cual
          CONTINUAR (boton "Continuar" / "Continuar desde el cursor") en vez
          de empezar de cero. Si ya alcanza el objetivo, se agrega una
          seccion mas.
        - Cada seccion se transmite token a token a `progress_callback(texto
          acumulado, palabras, objetivo)` cuando se pasa, y `cancel_check` se
          revisa en cada fragmento.
        - finish_reason: si una seccion se corta por max_tokens, la
          siguiente continua la misma oracion/parrafo (en modo chat, el final
          del texto va pre-llenado en la respuesta del modelo; en modo crudo
          se descarta la oracion incompleta y se une con un espacio, no con
          un salto de parrafo). Si el modelo termina solo y ya hay
          NATURAL_END_FRACTION del objetivo, el capitulo se da por
          terminado; si no, la siguiente seccion le pide no cerrar todavia.
        - Si el prompt de una seccion no cabe en la ventana de contexto, se
          reintenta con un contexto mas chico (CONTEXT_BUDGET_LEVELS).
        """
        chapter = project.chapters[chapter_index]
        target = chapter.target_words

        full_text = (resume_from or "").rstrip()
        if full_text and count_words(full_text) >= target:
            target = min(count_words(full_text) + SECTION_TARGET_WORDS, MAX_WORDS_PER_CHAPTER)
        stats = self.begin_operation(f"Capítulo {chapter_index + 1}", target_words=target)
        stats.words_written = count_words(full_text)
        try:
            return self._generate_chapter_sections(
                project, chapter_index, chapter, target, full_text, progress_callback, cancel_check,
            )
        finally:
            self._end_operation()

    @staticmethod
    def _is_word_char(ch: str) -> bool:
        return ch.isalnum() or ch in "_'-"

    def _generate_chapter_sections(
        self, project: Project, chapter_index: int, chapter, target: int, full_text: str,
        progress_callback: Optional[Callable[[str, int, int], None]],
        cancel_check: Optional[Callable[[], bool]],
    ) -> str:

        # Como se une la proxima seccion en modo crudo: salto de parrafo
        # salvo que la anterior se haya cortado a mitad de parrafo.
        raw_joiner = "\n\n"
        nudge = False
        last_finish: Optional[str] = None
        section = 0
        while count_words(full_text) < target and section < MAX_SECTIONS_PER_CHAPTER:
            if self._is_cancelled(cancel_check):
                break
            written = count_words(full_text)
            remaining = max(target - written, 200)
            section_words = min(SECTION_TARGET_WORDS, remaining + 150)
            # La ultima seccion no debe empujar el capitulo por encima de
            # MAX_WORDS_PER_CHAPTER.
            section_words = min(section_words, MAX_WORDS_PER_CHAPTER - written)
            if section_words <= 0:
                break
            max_tokens = int(section_words * TOKENS_PER_WORD_ESTIMATE)

            hints: List[str] = []
            if full_text:
                hints.append(build_beat_progress_hint(chapter.outline, written, target))
                if nudge:
                    hints.append(NOT_OVER_NUDGE)
                elif target - written <= section_words:
                    hints.append(FINAL_SECTION_HINT)

            def prompt_for_budget(budget: dict, _text=full_text, _remaining=remaining, _hints=hints) -> ChatPrompt:
                if not _text:
                    return build_chapter_start_chat(project, chapter_index, budget)

                def build(tail_words: int) -> ChatPrompt:
                    return build_chapter_continuation_chat(
                        project, chapter_index, budget, _text, _remaining, tail_words, hints=_hints,
                    )

                tail = self._dynamic_tail_words(build, _text, budget["tail_words"], max_tokens)
                return build(tail)

            # En modo chat, al continuar, el final del capitulo va pre-llenado
            # en la respuesta: el modelo sigue escribiendo desde ahi mismo,
            # asi que su salida se pega tal cual (con su espacio inicial).
            prefilled = bool(full_text) and self.formatter.is_chat
            base_text = full_text
            joiner = "" if prefilled or not base_text else raw_joiner
            # B13: el conteo de palabras se mantiene INCREMENTAL (solo se
            # cuentan las palabras del fragmento nuevo, corrigiendo la palabra
            # que queda partida entre fragmentos) en vez de recontar todo el
            # capitulo en cada token: eso era O(n) por token y, con un
            # capitulo de 10k palabras, ~0.7 ms por token con el GIL tomado.
            base_words = count_words(base_text)
            section_piece = {"parts": [], "words": 0, "last_char": ""}
            if base_text and prefilled:
                section_piece["last_char"] = base_text[-1]

            def on_token(delta: str, _base=base_text, _joiner=joiner, _piece=section_piece,
                         _prefilled=prefilled, _base_words=base_words) -> None:
                if not _piece["parts"] and not _prefilled:
                    delta = delta.lstrip()
                    if not delta:
                        return
                _piece["parts"].append(delta)
                words = count_words(delta)
                if (words and _piece["last_char"] and self._is_word_char(_piece["last_char"])
                        and self._is_word_char(delta[0])):
                    words -= 1  # la misma palabra continua desde el fragmento anterior
                _piece["words"] += words
                _piece["last_char"] = delta[-1]
                self.stats.words_written = _base_words + _piece["words"]
                if progress_callback:
                    piece_so_far = "".join(_piece["parts"])
                    combined = f"{_base}{_joiner}{piece_so_far}" if _base else piece_so_far
                    progress_callback(combined, self.stats.words_written, target)

            try:
                result = self._complete_with_shrinking_budget_ex(
                    prompt_for_budget, max_tokens,
                    on_token=on_token if progress_callback else None,
                    cancel_check=cancel_check,
                )
            except ContextOverflowError as exc:
                raise ContextOverflowError(
                    S.NO_SE_PUDO_GENERAR_SECCION.format(exc=exc)
                ) from exc

            last_finish = result.finish_reason
            piece = result.text.rstrip() if prefilled else result.text.strip()
            if not piece.strip():
                break
            if last_finish == "length" and not prefilled and not self.formatter.is_chat:
                # Modo crudo: la proxima seccion empieza texto nuevo, asi que
                # la oracion cortada se descarta y se sigue en el mismo parrafo.
                piece, _trimmed = self._trim_dangling_sentence(piece)
                raw_joiner = " "
            elif last_finish == "length":
                raw_joiner = " "
            else:
                raw_joiner = "\n\n"
            full_text = f"{base_text}{joiner}{piece}" if base_text else piece
            section += 1
            nudge = False
            self.stats.words_written = count_words(full_text)
            if progress_callback:
                progress_callback(full_text, self.stats.words_written, target)

            if last_finish == "cancelled":
                break
            if last_finish == "stop" and count_words(full_text) < target:
                if count_words(full_text) >= NATURAL_END_FRACTION * target:
                    break  # el modelo cerro el capitulo por su cuenta
                nudge = True

        if last_finish == "length":
            # El capitulo no deberia terminar a mitad de una oracion.
            trimmed, was_trimmed = self._trim_dangling_sentence(full_text)
            if was_trimmed:
                full_text = trimmed
                if progress_callback:
                    progress_callback(full_text, count_words(full_text), target)
        return full_text

    # ---------------- resumen / expandir / refinar ----------------
    def summarize(
        self, text: str, max_words: int = 150,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """
        Genera un resumen corto de un capitulo, para dar contexto al
        siguiente. Si el capitulo entero no cabe en la ventana de contexto,
        ya no se recorta (antes se conservaban inicio y final y los eventos
        del medio nunca llegaban al resumen): se resume por partes
        consecutivas y despues se resumen esos resumenes
        (`progress_callback(parte, total)`). Lanza OperationCancelled si se
        detiene.

        Nota (B2 d): no se resume seccion por seccion DURANTE la generacion:
        eso agregaria una llamada al modelo por seccion y pisaria el prefijo
        reutilizable de la cache KV entre secciones; este resumen por partes
        cubre el mismo objetivo (que cualquier capitulo quepa) al final.
        """
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)
        self.begin_operation("Resumen")
        try:
            return self._summarize(text, max_words, cancel_check, progress_callback)
        finally:
            self._end_operation()

    def _summarize(self, text, max_words, cancel_check, progress_callback) -> str:
        max_out_tokens = int(max_words * TOKENS_PER_WORD_ESTIMATE) + 40
        limit = self._available_context(max_out_tokens)
        prompt = build_summary_chat(text, max_words)
        kw = dict(cancel_check=cancel_check, task=TASK_SUMMARY)
        if self._count_tokens(self.render_prompt(prompt)) <= limit:
            return self._complete(prompt, max_tokens=max_out_tokens, **kw)

        scaffolding = self._count_tokens(self.render_prompt(build_partial_summary_chat("", max_words, 99, 99)))

        def fits(chunk: str) -> bool:
            return self._count_tokens(chunk) + scaffolding <= limit

        if not fits(" ".join(["word"] * 40)):
            # Ni una parte chica cabe: comportamiento anterior (recortar).
            instructions = self._count_tokens(self.render_prompt(build_summary_chat("", max_words)))
            trimmed = self._fit_text_to_token_budget(text, limit - instructions)
            return self._complete(build_summary_chat(trimmed, max_words), max_tokens=max_out_tokens, **kw)

        parts = self._split_text_to_fit(text, fits)
        total = len(parts) + 1
        partials = []
        for i, part in enumerate(parts, start=1):
            self._report_part(i, total, progress_callback)
            partials.append(self._complete(
                build_partial_summary_chat(part, max_words, i, len(parts)), max_tokens=max_out_tokens, **kw,
            ))
        partials = [p for p in partials if p.strip()]
        if len(partials) <= 1:
            return partials[0] if partials else ""
        combine = build_combine_summaries_chat(partials, max_words)
        if self._count_tokens(self.render_prompt(combine)) > limit:
            joined_budget = limit - self._count_tokens(self.render_prompt(build_combine_summaries_chat([""], max_words)))
            combine = build_combine_summaries_chat(
                [self._fit_text_to_token_budget("\n".join(partials), joined_budget)], max_words,
            )
        self._report_part(total, total, progress_callback)
        return self._complete(combine, max_tokens=max_out_tokens, **kw)

    def _report_part(self, part: int, total: int, progress_callback) -> None:
        self.stats.part = part
        self.stats.total_parts = total
        if progress_callback:
            progress_callback(part, total)

    def expand_field(
        self, field_key: str, text: str, max_words: int = 400,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Toma una nota corta (p.ej. una idea de plot en una linea) y la
        desarrolla en un texto mas completo, sin inventar una historia
        distinta. `field_key` es "plot"/"characters"/"setting" (ver
        prompts.EXPAND_FIELD_LABELS). Recorta `text` si por si solo ya no
        cabria en la ventana de contexto. Lanza OperationCancelled si se detiene.
        """
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)

        self.begin_operation("Expandir con IA")
        try:
            max_out_tokens = int(max_words * TOKENS_PER_WORD_ESTIMATE) + 60
            scaffolding_tokens = self._count_tokens(self.render_prompt(build_expand_field_chat(field_key, "", max_words)))
            available_for_text = self._available_context(max_out_tokens) - scaffolding_tokens

            trimmed_text = self._fit_text_to_token_budget(text, available_for_text)
            prompt = build_expand_field_chat(field_key, trimmed_text, max_words)
            # Notas de plot/personajes pueden organizarse en lineas tipo
            # "Chapter 1: ..." -- el corte por defecto de prosa las cortaria.
            return self._complete(
                prompt, max_tokens=max_out_tokens, stop=ONLY_END_MARKER_STOP,
                on_token=on_token, cancel_check=cancel_check, task=TASK_EXPAND,
            )
        finally:
            self._end_operation()

    def refine_chapter(
        self, project: Project, chapter_index: int, instruction: str,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Revisa un capitulo YA generado segun una instruccion del usuario
        (p.ej. "hazlo mas oscuro"), en vez de generar texto nuevo. No incluye
        plot/personajes/setting en el prompt (ver build_refine_chapter_prompt).

        El capitulo NUNCA se recorta: si el capitulo entero mas la respuesta
        no caben en la ventana de contexto, se revisa por partes (grupos de
        parrafos consecutivos, ver _split_for_refine) y las partes revisadas
        se vuelven a unir en orden; `progress_callback(parte, total)` informa
        el avance. Devuelve el texto revisado SIN aplicarlo: la interfaz lo
        muestra en una vista previa con diferencias antes de reemplazar
        nada, asi que detener (OperationCancelled) deja el original intacto.
        """
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)
        self.begin_operation(f"Refinar capítulo {chapter_index + 1}")
        try:
            return self._refine_chapter(project, chapter_index, instruction, cancel_check, progress_callback, on_token)
        finally:
            self._end_operation()

    def _refine_chapter(self, project, chapter_index, instruction, cancel_check, progress_callback, on_token) -> str:
        content = project.chapters[chapter_index].content.strip()
        max_tokens = self._refine_output_tokens(count_words(content))
        prompt = build_refine_chapter_chat(project, chapter_index, instruction)
        kw = dict(stop=ONLY_END_MARKER_STOP, cancel_check=cancel_check, on_token=on_token, task=TASK_REFINE)
        if self._count_tokens(self.render_prompt(prompt)) <= self._available_context(max_tokens):
            self._report_part(1, 1, progress_callback)
            return self._complete(prompt, max_tokens=max_tokens, **kw)

        # El andamiaje (instruccion + guia de estilo + aviso de "parte i de n")
        # es igual para todas las partes; se mide una vez, con texto vacio.
        scaffolding = self._count_tokens(self.render_prompt(
            build_refine_chapter_chat(project, chapter_index, instruction, content="", part=99, total_parts=99)
        ))
        parts = self._split_for_refine(content, scaffolding)
        revised: List[str] = []
        for i, part in enumerate(parts, start=1):
            self._report_part(i, len(parts), progress_callback)
            part_prompt = build_refine_chapter_chat(
                project, chapter_index, instruction, content=part, part=i, total_parts=len(parts),
            )
            if on_token is not None and revised:
                on_token("\n\n")
            out = self._complete(part_prompt, max_tokens=self._refine_output_tokens(count_words(part)), **kw)
            if not out.strip():
                # Unir las demas partes sin esta perderia texto del capitulo.
                raise RuntimeError(
                    S.REFINAR_PARTE_VACIA.format(part=i, total=len(parts))
                )
            revised.append(out.strip())
        return "\n\n".join(revised)

    def rewrite_span(
        self, project: Project, chapter_index: int, before: str, selection: str, after: str,
        mode: str = "rewrite", instruction: str = "",
        cancel_check: Optional[Callable[[], bool]] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Reescribe SOLO el fragmento seleccionado de un capitulo (Reescribir,
        Expandir, Describir o Acortar -- ver prompts.REWRITE_MODES), con el
        texto de alrededor como contexto. Devuelve el fragmento nuevo; la
        interfaz lo muestra en una vista previa con diferencias antes de
        reemplazar la seleccion.
        """
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)
        if not selection.strip():
            raise ValueError(S.NO_HAY_TEXTO_SELECCIONADO)
        self.begin_operation("Reescribir selección")
        try:
            words = count_words(selection)
            factor = 2.4 if mode == "expand" else REFINE_OUTPUT_HEADROOM
            max_tokens = int(words * TOKENS_PER_WORD_ESTIMATE * factor) + 128
            prompt = build_rewrite_span_chat(project, chapter_index, before, selection, after, mode, instruction)
            return self._complete(
                prompt, max_tokens=max_tokens, stop=ONLY_END_MARKER_STOP,
                on_token=on_token, cancel_check=cancel_check, task=TASK_REFINE,
            )
        finally:
            self._end_operation()

    @staticmethod
    def _refine_output_tokens(words: int) -> int:
        return int(words * TOKENS_PER_WORD_ESTIMATE * REFINE_OUTPUT_HEADROOM) + 128

    def _split_for_refine(self, content: str, scaffolding_tokens: int) -> List[str]:
        """
        Parte `content` en trozos consecutivos que, cada uno con su prompt y
        su respuesta, quepan en la ventana de contexto (ver _split_text_to_fit).
        """
        budget = self._n_ctx - SAFETY_MARGIN_TOKENS - scaffolding_tokens

        def fits(text: str) -> bool:
            return self._count_tokens(text) + self._refine_output_tokens(count_words(text)) <= budget

        if not fits(" ".join(["word"] * 20)):
            raise ContextOverflowError(
                S.CAPITULO_NO_CABE_PARA_REFINAR.format(n_ctx=self._n_ctx)
            )
        return self._split_text_to_fit(content, fits)

    @staticmethod
    def _split_text_to_fit(content: str, fits: Callable[[str], bool]) -> List[str]:
        """
        Parte `content` en trozos consecutivos para los que fits(trozo) es
        True. Corta entre parrafos; solo si un parrafo por si solo no cabe se
        corta entre oraciones, y solo si una oracion no cabe, por palabras.
        Nunca descarta texto: los trozos juntos contienen todas las palabras
        de `content`, en orden.
        """
        def split_units(text: str, level: int) -> List[str]:
            if fits(text):
                return [text]
            if level >= 2:
                # Ultimo recurso (una "oracion" enorme sin puntuacion): cortar
                # por palabras, en ventanas del mayor tamano que quepa.
                words = text.split()
                size = 20
                while size * 2 <= len(words) and fits(" ".join(words[:size * 2])):
                    size *= 2
                return [" ".join(words[j:j + size]) for j in range(0, len(words), size)]
            if level == 0:
                pieces, joiner = re.split(r"\n\s*\n", text), "\n\n"
            else:
                pieces, joiner = re.split(r"(?<=[.!?\"”])\s+", text), " "
            pieces = [p.strip() for p in pieces if p.strip()]
            if len(pieces) <= 1:
                return split_units(text, level + 1)
            # Agrupa piezas consecutivas mientras quepan juntas.
            chunks: List[str] = []
            current = ""
            for piece in pieces:
                candidate = f"{current}{joiner}{piece}" if current else piece
                if fits(candidate):
                    current = candidate
                    continue
                if current:
                    chunks.append(current)
                if fits(piece):
                    current = piece
                else:
                    chunks.extend(split_units(piece, level + 1))
                    current = ""
            if current:
                chunks.append(current)
            return chunks

        return split_units(content, 0)
