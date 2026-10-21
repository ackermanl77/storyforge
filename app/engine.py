"""
Motor de generacion local, usando llama-cpp-python sobre un modelo GGUF que el
usuario descarga por separado y coloca en la carpeta models/. No requiere
internet en tiempo de generacion.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import strings_es as S
from .chat_format import (
    CHAT_FORMAT_AUTO,
    ChatFormatter,
)
from .completion import CompletionMixin
from .cuda_env import (  # noqa: F401 -- reexportados
    _ensure_cuda_dlls_discoverable,
    find_nvidia_dll_dirs,
    supports_gpu_offload,
)
from .engine_model import ModelMixin
from .engine_types import (  # noqa: F401 -- reexportados: engine.X sigue funcionando
    CONTEXT_BUDGET_LEVELS,
    DEFAULT_N_BATCH,
    DEFAULT_PROSE_STOP,
    GGML_KV_TYPES,
    MAX_DANGLING_FRACTION,
    MAX_EMPTY_SECTION_RETRIES,
    MAX_SECTIONS_PER_CHAPTER,
    MIN_SECTION_FRACTION,
    NATURAL_END_FRACTION,
    NEW_PARAGRAPH,
    ONLY_END_MARKER_STOP,
    OUTLINE_WORDS_PER_CHAPTER,
    PHRASE_GUARD_TASKS,
    REFINE_OUTPUT_HEADROOM,
    SAFETY_MARGIN_TOKENS,
    SECTION_TARGET_WORDS,
    TOKEN_CACHE_SIZE,
    TOKENS_PER_WORD_ESTIMATE,
    WORD_ALTERNATIVES,
    WORD_COMPLETION_TOKENS,
    CompletionResult,
    ContextOverflowError,
    GenerationStats,
    ModelNotLoadedError,
    OperationCancelled,
    PromptLike,
    WordAlternative,
)
from .gguf import list_model_entries
from .output_guard import clean_section
from .phrase_guard import PhraseGuard
from .project import MAX_CHAPTERS, MAX_WORDS_PER_CHAPTER, Project, count_words
from .prompts import (
    FINAL_SECTION_HINT,
    NOT_OVER_NUDGE,
    SIDE_CHAT_BRAINSTORM,
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
    build_section_scope_hint,
    build_side_chat,
    build_summary_chat,
    parse_outline_response,
)
from .sampling import (
    MAX_SEED,
    TASK_EXPAND,
    TASK_OUTLINE,
    TASK_REFINE,
    TASK_SUMMARY,
    SamplingConfig,
)

logger = logging.getLogger(__name__)


def find_local_models(models_dir: str) -> List[str]:
    """Rutas cargables de models_dir: una por modelo (la primera parte de un
    modelo partido en varios archivos); los modelos partidos incompletos no
    se incluyen (ver gguf.list_model_entries para la lista completa con
    etiquetas)."""
    return [e.path for e in list_model_entries(models_dir) if e.complete]


class LocalStoryEngine(ModelMixin, CompletionMixin):
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
        # Frases a evitar del proyecto de la operacion en curso (B15), o None.
        self.phrase_guard: Optional[PhraseGuard] = None
        # Donde empezo la ultima seccion del ultimo generate_chapter() (posicion
        # en el texto devuelto; lo anterior es prefijo intacto), o None si no se
        # escribio ninguna. "Reintentar última sección" continua desde ahi.
        self.last_section_start: Optional[int] = None
        # Secciones del ultimo generate_chapter() a las que output_guard les quito
        # algo (eco del prompt, cercas de codigo...): la UI sugiere revisar el formato de chat.
        self.cleaned_sections = 0
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


    # ---- alternativas en una palabra (F15) ----
    def _alternatives_prompt(self, project: Project, chapter_index: int, text_before: str) -> str:
        """El prompt con el que el modelo escribiria lo que sigue a `text_before` (el mismo que usa
        Continuar), achicando el contexto si no cabe."""
        chapter = project.chapters[chapter_index]
        text = text_before.rstrip(" \t")
        for budget in CONTEXT_BUDGET_LEVELS:
            if not text.strip():
                prompt = build_chapter_start_chat(project, chapter_index, budget, hints=[])
            else:
                remaining = max(chapter.target_words - count_words(text), 200)

                def build(tail_words: int, _budget=budget, _remaining=remaining) -> ChatPrompt:
                    return build_chapter_continuation_chat(project, chapter_index, _budget, text, _remaining,
                                                           tail_words, hints=[])

                prompt = build(self._dynamic_tail_words(build, text, budget["tail_words"], 16))
            rendered = self.render_prompt(prompt)
            if self._count_tokens(rendered) <= self._available_context(16):
                return rendered
        raise ContextOverflowError(S.CONTEXTO_NO_CABE_NI_REDUCIDO)


    def word_alternatives(self, project: Project, chapter_index: int, text_before: str,
                          top_k: int = WORD_ALTERNATIVES) -> List[WordAlternative]:
        """Lo que el modelo podria escribir en lugar de la palabra que empieza despues de
        `text_before` (F15): sus `top_k` primeros tokens mas probables, cada uno completado a
        palabra entera con unos tokens greedy, con la probabilidad del primer token (las que
        terminan en la misma palabra se suman). No modifica el capitulo."""
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)
        self.begin_operation(S.ALTERNATIVAS_OPERACION)
        try:
            rendered = self._alternatives_prompt(project, chapter_index, text_before)
            merged: "OrderedDict[str, WordAlternative]" = OrderedDict()
            for token, probability in self._top_tokens(rendered, top_k):
                word = token
                if token.strip() and self._is_word_char(token.rstrip()[-1]):
                    response = self._llm(rendered + token, max_tokens=WORD_COMPLETION_TOKENS, temperature=0.0)
                    following = response["choices"][0].get("text", "") if isinstance(response, dict) else ""
                    rest = ""
                    for ch in following:
                        if not self._is_word_char(ch):
                            break
                        rest += ch
                    word = token + rest
                key = word.strip().lower() or word
                if key in merged:
                    old = merged[key]
                    merged[key] = WordAlternative(old.word, old.probability + probability, old.token)
                else:
                    merged[key] = WordAlternative(word, probability, token)
            return sorted(merged.values(), key=lambda a: -a.probability)
        finally:
            self._end_operation()


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
        self.last_section_start = None
        self.phrase_guard = PhraseGuard.for_project(project)
        self.cleaned_sections = 0

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
        empty_retries = 0
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
            final_part = target - written <= section_words
            if full_text:
                hints.append(build_beat_progress_hint(chapter.outline, written, target))
            if not final_part:
                # Cada parte que no es la ultima recibe sus beats y la orden de
                # no cerrar el capitulo (la primera tambien: era la que comprimia
                # todo el esquema y escribia un final).
                hints.append(build_section_scope_hint(chapter.outline, written, section_words, target))
            if nudge:
                hints.append(NOT_OVER_NUDGE)
            elif full_text and final_part:
                hints.append(FINAL_SECTION_HINT)

            def prompt_for_budget(budget: dict, _text=full_text, _remaining=remaining, _hints=hints) -> ChatPrompt:
                if not _text:
                    return build_chapter_start_chat(project, chapter_index, budget, hints=_hints)

                def build(tail_words: int) -> ChatPrompt:
                    return build_chapter_continuation_chat(
                        project, chapter_index, budget, _text, _remaining, tail_words, hints=_hints,
                    )

                tail = self._dynamic_tail_words(build, _text, budget["tail_words"], max_tokens)
                prompt = build(tail)
                if _new_paragraph:
                    # El texto anterior termino en un final natural: la respuesta
                    # pre-llenada empieza un parrafo nuevo, en vez de quedar justo
                    # despues de una oracion cerrada -- donde el siguiente token
                    # mas probable de un modelo de chat es "fin del turno".
                    prompt = replace(prompt, prefill=prompt.prefill + NEW_PARAGRAPH)
                return prompt

            # En modo chat, al continuar, el final del capitulo va pre-llenado
            # en la respuesta: el modelo sigue escribiendo desde ahi mismo,
            # asi que su salida se pega tal cual (con su espacio inicial).
            prefilled = bool(full_text) and self.formatter.is_chat
            # Solo tras una seccion que el modelo cerro en esta misma ejecucion:
            # "Continuar (desde el cursor)" puede empezar a mitad de una oracion.
            new_paragraph = prefilled and last_finish == "stop"
            _new_paragraph = new_paragraph
            base_text = full_text
            if new_paragraph:
                joiner = NEW_PARAGRAPH
            else:
                joiner = "" if prefilled or not base_text else raw_joiner
            # B13: el conteo de palabras se mantiene INCREMENTAL (solo se
            # cuentan las palabras del fragmento nuevo, corrigiendo la palabra
            # que queda partida entre fragmentos) en vez de recontar todo el
            # capitulo en cada token: eso era O(n) por token y, con un
            # capitulo de 10k palabras, ~0.7 ms por token con el GIL tomado.
            base_words = count_words(base_text)
            section_piece = {"parts": [], "words": 0, "last_char": ""}
            if base_text and prefilled and not new_paragraph:
                section_piece["last_char"] = base_text[-1]

            def on_token(delta: str, _base=base_text, _joiner=joiner, _piece=section_piece,
                         _prefilled=prefilled and not new_paragraph, _base_words=base_words) -> None:
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
                    # La ultima parte puede cerrar cuando quiera; las demas no.
                    min_tokens=0 if final_part else int(max_tokens * MIN_SECTION_FRACTION),
                )
            except ContextOverflowError as exc:
                raise ContextOverflowError(
                    S.NO_SE_PUDO_GENERAR_SECCION.format(exc=exc)
                ) from exc

            piece = result.text.rstrip() if prefilled and not new_paragraph else result.text.strip()
            # Code fences, echoed instructions and the already-written ending copied back
            # (a model in the wrong chat format "answers" instead of continuing): app/output_guard.py.
            piece, removed = clean_section(piece, base_text)
            if removed:
                logger.warning("Capítulo %d, sección %d: se quitó %s de la respuesta del modelo (¿formato de chat?)",
                               chapter_index + 1, section + 1, ", ".join(removed))
                self.cleaned_sections += 1
            if not piece.strip():
                if result.finish_reason == "cancelled" or empty_retries >= MAX_EMPTY_SECTION_RETRIES:
                    break
                # El modelo cerro su turno sin escribir: otra semilla (distinta
                # tambien con una semilla fija del proyecto) y el aviso de que
                # el capitulo no termino.
                empty_retries += 1
                self._op_seed = (self._op_seed + 1) if self._op_seed is not None else random.randint(0, MAX_SEED)
                nudge = True
                continue
            last_finish = result.finish_reason
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
            self.last_section_start = len(base_text)
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
                if self.last_section_start is not None:
                    self.last_section_start = min(self.last_section_start, len(full_text))
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

    def side_chat(
        self, project: Project, chapter_index: Optional[int], history: Sequence[Tuple[str, str]], message: str,
        mode: str = SIDE_CHAT_BRAINSTORM, character: str = "", max_words: int = 350,
        cancel_check: Optional[Callable[[], bool]] = None, on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Un turno de la conversacion lateral (F14): lluvia de ideas o entrevista a un personaje,
        con la biblia de la historia y el capitulo actual como contexto. Si no cabe, se descartan los
        turnos mas viejos y se achica el contexto (CONTEXT_BUDGET_LEVELS). No toca el proyecto."""
        if self._llm is None:
            raise ModelNotLoadedError(S.NO_HAY_MODELO_CARGADO)
        self.begin_operation(S.CONVERSACION_OPERACION)
        try:
            max_out_tokens = int(max_words * TOKENS_PER_WORD_ESTIMATE) + 60
            limit = self._available_context(max_out_tokens)
            turns = list(history)
            prompt = None
            for budget in CONTEXT_BUDGET_LEVELS:
                for tail in (600, 300, 0):
                    while True:
                        candidate = build_side_chat(project, chapter_index, turns, message, mode, character,
                                                    budget, tail)
                        if self._count_tokens(self.render_prompt(candidate)) <= limit:
                            prompt = candidate
                            break
                        if len(turns) <= 2:
                            break
                        turns = turns[2:]  # olvidar el intercambio mas viejo
                    if prompt is not None:
                        break
                if prompt is not None:
                    break
            if prompt is None:
                raise ContextOverflowError(S.CONTEXTO_NO_CABE_NI_REDUCIDO)
            return self._complete(prompt, max_tokens=max_out_tokens, stop=ONLY_END_MARKER_STOP,
                                  on_token=on_token, cancel_check=cancel_check, task=TASK_EXPAND)
        finally:
            self._end_operation()

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
        self.phrase_guard = PhraseGuard.for_project(project)
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
        self.phrase_guard = PhraseGuard.for_project(project)
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
