"""
Motor de generacion local, usando llama-cpp-python sobre un modelo GGUF que el
usuario descarga por separado y coloca en la carpeta models/. No requiere
internet en tiempo de generacion.
"""
from __future__ import annotations

import glob
import os
from typing import Callable, List, Optional, Tuple

from .project import MAX_CHAPTERS, Project, count_words
from .prompts import (
    build_chapter_system_prompt,
    build_continuation_prompt,
    build_outline_prompt,
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
CONTEXT_BUDGET_LEVELS = [
    dict(max_plot_words=1200, max_characters_words=600, max_setting_words=600, max_previous_words=500, max_outline_words=400, tail_words=400),
    dict(max_plot_words=700, max_characters_words=400, max_setting_words=400, max_previous_words=300, max_outline_words=250, tail_words=250),
    dict(max_plot_words=350, max_characters_words=200, max_setting_words=200, max_previous_words=150, max_outline_words=120, tail_words=150),
]


class ModelNotLoadedError(RuntimeError):
    pass


class ContextOverflowError(RuntimeError):
    """El prompt necesario no cabe en la ventana de contexto del modelo cargado."""


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
            from llama_cpp import Llama
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "El paquete 'llama-cpp-python' no esta instalado. "
                "Instala las dependencias con: pip install -r requirements.txt"
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
        head = approx_words // 2
        tail = approx_words - head
        trimmed = " ".join(words[:head]) + " [...] " + " ".join(words[-tail:])
        while self._count_tokens(trimmed) > available_tokens and head > 20:
            head -= 20
            tail = max(approx_words - head, 20)
            trimmed = " ".join(words[:head]) + " [...] " + " ".join(words[-tail:])
        return trimmed

    def _complete(self, prompt: str, max_tokens: int, stop: Optional[List[str]] = None) -> str:
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

        result = self._llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.85,
            top_p=0.92,
            repeat_penalty=1.15,
            stop=stop or ["\n\nCHAPTER", "\n\nChapter", "[END]"],
        )
        return result["choices"][0]["text"].strip()

    def _complete_with_shrinking_budget(
        self,
        prompt_for_budget: Callable[[dict], str],
        max_tokens: int,
    ) -> str:
        """
        Intenta completar con cada nivel de CONTEXT_BUDGET_LEVELS (de mayor a
        menor contexto incluido) hasta que uno quepa en la ventana de
        contexto del modelo. `prompt_for_budget` recibe un dict de budget y
        devuelve el prompt completo a intentar con ese nivel.
        """
        last_error: Optional[Exception] = None
        for budget in CONTEXT_BUDGET_LEVELS:
            try:
                return self._complete(prompt_for_budget(budget), max_tokens=max_tokens)
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

        raw = self._complete_with_shrinking_budget(prompt_for_budget, max_tokens)
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
        de palabras (o hasta MAX_SECTIONS_PER_CHAPTER). progress_callback
        recibe (texto_generado_hasta_ahora, palabras_actuales, palabras_objetivo).

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
            remaining = max(target - count_words(full_text), 200)
            section_words = min(SECTION_TARGET_WORDS, remaining + 150)
            max_tokens = int(section_words * TOKENS_PER_WORD_ESTIMATE)

            def prompt_for_budget(budget: dict, _section=section, _remaining=remaining) -> str:
                system_prompt = build_chapter_system_prompt(
                    project, chapter_index,
                    max_plot_words=budget["max_plot_words"],
                    max_characters_words=budget["max_characters_words"],
                    max_setting_words=budget["max_setting_words"],
                    max_previous_words=budget["max_previous_words"],
                    max_outline_words=budget["max_outline_words"],
                )
                if _section == 0:
                    return f"{system_prompt}\n\nBegin the chapter now:\n"
                cont = build_continuation_prompt(full_text, _remaining, tail_words=budget["tail_words"])
                return f"{system_prompt}\n\n{cont}\n"

            try:
                piece = self._complete_with_shrinking_budget(prompt_for_budget, max_tokens)
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
