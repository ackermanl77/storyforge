"""
Motor de generacion local, usando llama-cpp-python sobre un modelo GGUF que el
usuario descarga por separado y coloca en la carpeta models/. No requiere
internet en tiempo de generacion.
"""
from __future__ import annotations

import glob
import os
import re
import sys
from typing import Callable, List, Optional, Tuple

from .project import MAX_CHAPTERS, MAX_WORDS_PER_CHAPTER, Project, count_words
from .prompts import (
    build_chapter_system_prompt,
    build_continuation_prompt,
    build_expand_field_prompt,
    build_outline_prompt,
    build_refine_chapter_prompt,
    parse_outline_response,
)

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
    if not os.path.isdir(models_dir):
        return []
    return sorted(glob.glob(os.path.join(models_dir, "*.gguf")))


class LocalStoryEngine:
    """Envuelve un modelo GGUF cargado con llama-cpp-python."""

    def __init__(self) -> None:
        self._llm = None
        self._model_path: Optional[str] = None
        self._n_ctx: int = 8192  # valor por defecto hasta que se cargue un modelo

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
              n_gpu_layers: int = 0) -> None:
        try:
            _ensure_cuda_dlls_discoverable()
            from llama_cpp import Llama
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "El paquete 'llama-cpp-python' no esta instalado. "
                "Instala las dependencias con: pip install -r requirements.txt"
            ) from exc
        except Exception as exc:
            # Un build de llama-cpp-python con CUDA cuyas DLLs de runtime
            # (cudart/cublas) no se encuentran NO lanza ImportError, sino
            # RuntimeError("Failed to load shared library ...") u OSError
            # desde el propio import -- antes eso llegaba al usuario como un
            # mensaje crudo en ingles sin pista de como resolverlo.
            raise RuntimeError(
                "llama-cpp-python esta instalado, pero no se pudo cargar su libreria nativa "
                "(llama.dll o alguna de las DLLs que necesita). Si instalaste la version con "
                "CUDA, instala tambien las DLLs de runtime (pip install nvidia-cuda-runtime "
                "nvidia-cublas, ver README > Rendimiento / GPU) o vuelve a la version "
                f"solo-CPU.\n\nDetalle: {exc}"
            ) from exc

        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"No se encontro el modelo en: {model_path}")

        # Soltamos el modelo anterior (si habia uno) antes de reservar memoria
        # para el nuevo: construir el Llama nuevo antes de liberar el viejo
        # tendria ambos modelos completos en RAM/VRAM a la vez, lo cual para
        # modelos de varios GB puede agotar la memoria disponible.
        self.unload()

        self._llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        self._model_path = model_path
        self._n_ctx = n_ctx

    def unload(self) -> None:
        self._llm = None
        self._model_path = None

    # ---------------- manejo de contexto / tokens ----------------
    def _count_tokens(self, text: str) -> int:
        """
        Cuenta tokens usando el tokenizador real del modelo cuando esta
        disponible; si no (modelo no soporta tokenize, o esta simulado en
        pruebas), cae a una estimacion por palabras.
        """
        if self._llm is not None:
            try:
                return len(self._llm.tokenize(text.encode("utf-8", errors="ignore")))
            except Exception:
                pass
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
        prompt: str,
        max_tokens: int,
        stop: Optional[List[str]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        if self._llm is None:
            raise ModelNotLoadedError("No hay un modelo cargado. Carga un archivo .gguf primero.")

        prompt_tokens = self._count_tokens(prompt)
        available = self._available_context(max_tokens)
        if prompt_tokens > available:
            raise ContextOverflowError(
                f"El contexto necesario ({prompt_tokens:,} tokens) no cabe en la ventana de "
                f"contexto del modelo ({self._n_ctx:,} tokens) junto con el espacio reservado "
                f"para la respuesta ({max_tokens:,} tokens)."
            )

        call_kwargs = dict(
            max_tokens=max_tokens,
            temperature=0.85,
            top_p=0.92,
            repeat_penalty=1.15,
            stop=stop or DEFAULT_PROSE_STOP,
        )
        # Solo pedimos streaming token a token (llama_cpp.Llama.__call__(...,
        # stream=True), que devuelve un generador en vez de un dict) cuando
        # hay alguien escuchando -- summarize()/expand_field()/
        # generate_outline()/refine_chapter() no pasan on_token y siguen
        # pidiendo la respuesta completa de una sola vez, sin el overhead
        # extra de iterar chunk por chunk para algo que no se muestra en vivo.
        if on_token is not None:
            call_kwargs["stream"] = True

        response = self._llm(prompt, **call_kwargs)

        if isinstance(response, dict):
            # Respuesta no incremental: ya sea porque no se pidio streaming,
            # o porque _llm (p.ej. un doble de prueba, o una version de
            # llama_cpp que ignora stream=True) devolvio el resultado
            # completo de una. Se trata igual en ambos casos -- si hay
            # on_token, se le entrega el texto completo de una sola vez en
            # vez de por fragmentos, para no perder la actualizacion.
            text = response["choices"][0]["text"]
            if on_token is not None and text:
                on_token(text)
            return text.strip()

        # Streaming real: `response` es un generador de fragmentos, cada uno
        # con un delta incremental de texto (NO acumulado) en
        # choices[0]["text"] -- el formato propio de llama_cpp en modo
        # stream. Revisar cancel_check aqui (no solo entre secciones, como
        # antes de este cambio) deja que Cancelar corte la generacion a
        # mitad de una seccion en vez de tener que esperar a que termine.
        pieces: List[str] = []
        for chunk in response:
            if cancel_check and cancel_check():
                break
            delta = chunk["choices"][0].get("text", "")
            if not delta:
                continue
            pieces.append(delta)
            if on_token is not None:
                on_token(delta)
        return "".join(pieces).strip()

    def _complete_with_shrinking_budget(
        self,
        prompt_for_budget: Callable[[dict], str],
        max_tokens: int,
        on_token: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        """
        Intenta completar con cada nivel de CONTEXT_BUDGET_LEVELS (de mayor a
        menor contexto incluido) hasta que uno quepa en la ventana de
        contexto del modelo. `prompt_for_budget` recibe un dict de budget y
        devuelve el prompt completo a intentar con ese nivel. `on_token`/
        `cancel_check` se pasan tal cual a `_complete()` -- ver ahi.
        """
        last_error: Optional[Exception] = None
        for budget in CONTEXT_BUDGET_LEVELS:
            try:
                return self._complete(
                    prompt_for_budget(budget), max_tokens=max_tokens, stop=stop,
                    on_token=on_token, cancel_check=cancel_check,
                )
            except ContextOverflowError as exc:
                last_error = exc
                continue
        raise ContextOverflowError(
            "Incluso reduciendo al minimo el contexto (plot, personajes, setting y "
            "resumen previo), el prompt sigue sin caber en la ventana de contexto de "
            "este modelo. Prueba con un plot, personajes o setting mas cortos, un "
            "objetivo de palabras menor, o carga el modelo con un n_ctx mayor si tu "
            "hardware lo permite."
        ) from last_error

    def generate_outline(self, project: Project, num_chapters: int) -> List[Tuple[str, str]]:
        """
        Genera un esquema (beat sheet) de toda la historia antes de escribir
        prosa: una lista de (titulo, beats) por capitulo. Hacer esto primero
        ayuda mucho a que una historia de varios capitulos mantenga
        coherencia narrativa de principio a fin.
        """
        if self._llm is None:
            raise ModelNotLoadedError("No hay un modelo cargado. Carga un archivo .gguf primero.")

        num_chapters = max(1, min(int(num_chapters), MAX_CHAPTERS))
        max_tokens = int(num_chapters * OUTLINE_WORDS_PER_CHAPTER * TOKENS_PER_WORD_ESTIMATE) + 60

        def prompt_for_budget(budget: dict) -> str:
            return build_outline_prompt(
                project, num_chapters,
                max_plot_words=budget["max_plot_words"],
                max_characters_words=budget["max_characters_words"],
                max_setting_words=budget["max_setting_words"],
            )

        # stop explicito: con el corte por defecto ("\n\nChapter") el modelo
        # se detenia justo al empezar "Chapter 2:" y el esquema salia con un
        # solo capitulo.
        raw = self._complete_with_shrinking_budget(prompt_for_budget, max_tokens, stop=ONLY_END_MARKER_STOP)
        return parse_outline_response(raw, num_chapters)

    def generate_chapter(
        self,
        project: Project,
        chapter_index: int,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        Genera un capitulo completo por secciones hasta acercarse al objetivo
        de palabras (o hasta MAX_SECTIONS_PER_CHAPTER). Cada seccion se pide
        con streaming token a token (llama_cpp.Llama.__call__(..., stream=
        True) via _complete()) cuando hay progress_callback: en vez de
        esperar a que toda la seccion (~900 palabras) termine para recien
        entonces notificar, progress_callback recibe actualizaciones mucho
        mas frecuentes -- (texto_generado_hasta_ahora, palabras_actuales,
        palabras_objetivo), igual firma de siempre, pero ahora incluyendo el
        texto parcial de la seccion en curso, no solo secciones ya
        completas. El llamador (app/gui.py) es responsable de no reaccionar
        a cada llamada con una actualizacion de UI -- ver el throttling ahi.

        cancel_check tambien se revisa dentro de cada seccion (no solo entre
        secciones, como antes de que existiera streaming), asi que Cancelar
        ahora puede cortar la generacion a mitad de una seccion en vez de
        tener que esperar a que termine.

        Si el prompt de una seccion no cabe en la ventana de contexto del
        modelo, se reintenta automaticamente con un contexto mas chico
        (CONTEXT_BUDGET_LEVELS) antes de propagar ContextOverflowError.
        """
        chapter = project.chapters[chapter_index]
        target = chapter.target_words

        full_text = ""
        section = 0
        while count_words(full_text) < target and section < MAX_SECTIONS_PER_CHAPTER:
            if cancel_check and cancel_check():
                break
            written = count_words(full_text)
            remaining = max(target - written, 200)
            section_words = min(SECTION_TARGET_WORDS, remaining + 150)
            # La ultima seccion no debe empujar el capitulo por encima de
            # MAX_WORDS_PER_CHAPTER: con el piso de 200 + 150 palabras de
            # arriba, un objetivo de 10,000 podia terminar en ~10,300.
            section_words = min(section_words, MAX_WORDS_PER_CHAPTER - written)
            if section_words <= 0:
                break
            max_tokens = int(section_words * TOKENS_PER_WORD_ESTIMATE)

            def prompt_for_budget(budget: dict, _section=section, _remaining=remaining) -> str:
                system_prompt = build_chapter_system_prompt(
                    project, chapter_index,
                    max_plot_words=budget["max_plot_words"],
                    max_characters_words=budget["max_characters_words"],
                    max_setting_words=budget["max_setting_words"],
                    max_previous_words=budget["max_previous_words"],
                    max_outline_words=budget["max_outline_words"],
                    max_lore_words=budget["max_lore_words"],
                )
                if _section == 0:
                    return f"{system_prompt}\n\nBegin the chapter now:\n"
                cont = build_continuation_prompt(full_text, _remaining, tail_words=budget["tail_words"])
                return f"{system_prompt}\n\n{cont}\n"

            # base_text se captura AHORA (no dentro de on_token, que se
            # llama repetidamente mientras se generan tokens) para que cada
            # actualizacion parcial de esta seccion se combine con el texto
            # de las secciones YA completadas, no con lo que full_text valga
            # en el momento en que finalmente se invoque cada callback.
            base_text = full_text
            section_piece = {"text": ""}

            def on_token(delta: str, _base=base_text, _piece=section_piece) -> None:
                _piece["text"] += delta
                if progress_callback:
                    combined = f"{_base}\n\n{_piece['text']}".strip() if _base else _piece["text"]
                    progress_callback(combined, count_words(combined), target)

            try:
                piece = self._complete_with_shrinking_budget(
                    prompt_for_budget, max_tokens,
                    on_token=on_token if progress_callback else None,
                    cancel_check=cancel_check,
                )
            except ContextOverflowError as exc:
                raise ContextOverflowError(
                    f"No fue posible generar esta seccion del capitulo: {exc}"
                ) from exc

            if not piece:
                break
            full_text = (full_text + "\n\n" + piece).strip() if full_text else piece
            section += 1
            if progress_callback:
                progress_callback(full_text, count_words(full_text), target)

        return full_text

    def summarize(self, text: str, max_words: int = 150) -> str:
        """
        Genera un resumen corto de un capitulo, para dar contexto al
        siguiente. Recorta el capitulo (conservando inicio y final) si por si
        solo ya no cabria en la ventana de contexto del modelo.
        """
        if self._llm is None:
            raise ModelNotLoadedError("No hay un modelo cargado. Carga un archivo .gguf primero.")

        instructions = (
            "Summarize the following story chapter in at most "
            f"{max_words} words, focusing on plot-relevant events only "
            "(no stylistic commentary):\n\n"
        )
        suffix = "\n\nSummary:"
        max_out_tokens = int(max_words * TOKENS_PER_WORD_ESTIMATE) + 40
        reserved_for_scaffolding = self._count_tokens(instructions + suffix)
        available_for_text = self._available_context(max_out_tokens) - reserved_for_scaffolding

        text_to_summarize = self._fit_text_to_token_budget(text, available_for_text)
        prompt = f"{instructions}{text_to_summarize}{suffix}"
        return self._complete(prompt, max_tokens=max_out_tokens)

    def expand_field(self, field_key: str, text: str, max_words: int = 400) -> str:
        """
        Toma una nota corta (p.ej. una idea de plot en una linea) y la
        desarrolla en un texto mas completo, sin inventar una historia
        distinta. `field_key` es "plot"/"characters"/"setting" (ver
        prompts.EXPAND_FIELD_LABELS). Recorta `text` si por si solo ya no
        cabria en la ventana de contexto, igual que summarize().
        """
        if self._llm is None:
            raise ModelNotLoadedError("No hay un modelo cargado. Carga un archivo .gguf primero.")

        max_out_tokens = int(max_words * TOKENS_PER_WORD_ESTIMATE) + 60
        scaffolding_tokens = self._count_tokens(build_expand_field_prompt(field_key, "", max_words))
        available_for_text = self._available_context(max_out_tokens) - scaffolding_tokens

        trimmed_text = self._fit_text_to_token_budget(text, available_for_text)
        prompt = build_expand_field_prompt(field_key, trimmed_text, max_words)
        # Notas de plot/personajes pueden organizarse en lineas tipo
        # "Chapter 1: ..." -- el corte por defecto de prosa las cortaria.
        return self._complete(prompt, max_tokens=max_out_tokens, stop=ONLY_END_MARKER_STOP)

    def refine_chapter(self, project: Project, chapter_index: int, instruction: str) -> str:
        """
        Revisa un capitulo YA generado segun una instruccion del usuario
        (p.ej. "hazlo mas oscuro"), en vez de generar texto nuevo. No incluye
        plot/personajes/setting en el prompt (ver build_refine_chapter_prompt).

        El capitulo NUNCA se recorta: el resultado reemplaza el capitulo
        completo, asi que revisar solo un recorte perdia en silencio todo lo
        que quedaba fuera (normalmente el final). Si el capitulo entero mas la
        respuesta no caben en la ventana de contexto, se revisa por partes
        (grupos de parrafos consecutivos, ver _split_for_refine) y las partes
        revisadas se vuelven a unir en orden.
        """
        if self._llm is None:
            raise ModelNotLoadedError("No hay un modelo cargado. Carga un archivo .gguf primero.")

        content = project.chapters[chapter_index].content.strip()
        max_tokens = self._refine_output_tokens(count_words(content))
        prompt = build_refine_chapter_prompt(project, chapter_index, instruction)
        if self._count_tokens(prompt) <= self._available_context(max_tokens):
            return self._complete(prompt, max_tokens=max_tokens, stop=ONLY_END_MARKER_STOP)

        # El andamiaje (instruccion + guia de estilo + aviso de "parte i de n")
        # es igual para todas las partes; se mide una vez, con texto vacio.
        scaffolding = self._count_tokens(
            build_refine_chapter_prompt(project, chapter_index, instruction, content="", part=99, total_parts=99)
        )
        parts = self._split_for_refine(content, scaffolding)
        revised: List[str] = []
        for i, part in enumerate(parts, start=1):
            part_prompt = build_refine_chapter_prompt(
                project, chapter_index, instruction, content=part, part=i, total_parts=len(parts),
            )
            out = self._complete(
                part_prompt, max_tokens=self._refine_output_tokens(count_words(part)),
                stop=ONLY_END_MARKER_STOP,
            )
            if not out.strip():
                # Unir las demas partes sin esta perderia texto del capitulo.
                raise RuntimeError(
                    f"El modelo devolvio un texto vacio al refinar la parte {i} de {len(parts)} "
                    "del capitulo. No se modifico el capitulo; intentalo de nuevo."
                )
            revised.append(out.strip())
        return "\n\n".join(revised)

    @staticmethod
    def _refine_output_tokens(words: int) -> int:
        return int(words * TOKENS_PER_WORD_ESTIMATE * REFINE_OUTPUT_HEADROOM) + 128

    def _split_for_refine(self, content: str, scaffolding_tokens: int) -> List[str]:
        """
        Parte `content` en trozos consecutivos que, cada uno con su prompt y
        su respuesta, quepan en la ventana de contexto. Corta entre parrafos;
        solo si un parrafo por si solo no cabe se corta entre oraciones, y
        solo si una oracion no cabe, por palabras. Nunca descarta texto: los
        trozos juntos contienen todas las palabras de `content`, en orden.
        """
        budget = self._n_ctx - SAFETY_MARGIN_TOKENS - scaffolding_tokens

        def fits(text: str) -> bool:
            return self._count_tokens(text) + self._refine_output_tokens(count_words(text)) <= budget

        if not fits(" ".join(["word"] * 20)):
            raise ContextOverflowError(
                "El capitulo no cabe completo en la ventana de contexto del modelo "
                f"({self._n_ctx:,} tokens) y ni siquiera hay espacio para refinarlo por partes. "
                "Carga el modelo con un n_ctx mayor en la pestana Modelo."
            )

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
                pieces, joiner = re.split(r"(?<=[.!?\"\u201d])\s+", text), " "
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
