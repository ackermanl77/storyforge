"""El nucleo de completado de LocalStoryEngine (R6: separado de engine.py): conteo de tokens y
presupuestos de contexto, la llamada al modelo (local o servidor) con su guardia de frases,
los procesadores de logits y el reintento con menos contexto. Un mixin: usa el estado del
motor (self._llm, self._formatter, ...) que crean __init__ y load() en engine.py / engine_model.py."""

from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import strings_es as S
from .chat_format import (
    CHAT_FORMAT_AUTO,
    ChatFormatter,
    RawFormatter,
    detect_formatter,
    preset_formatter,
)
from .engine_types import (
    CONTEXT_BUDGET_LEVELS,
    DEFAULT_PROSE_STOP,
    PHRASE_GUARD_TASKS,
    SAFETY_MARGIN_TOKENS,
    TOKEN_CACHE_SIZE,
    TOKENS_PER_WORD_ESTIMATE,
    CompletionResult,
    ContextOverflowError,
    ModelNotLoadedError,
    OperationCancelled,
    PromptLike,
)
from .phrase_guard import MAX_REWINDS, MAX_REWINDS_AT_ONE_POINT, PhraseGuard, PhraseMatch, word_variants
from .sampling import (
    TASK_PROSE,
)

logger = logging.getLogger("app.engine")


class CompletionMixin:
    def _has_special_token(self, text: str) -> bool:
        """True si `text` es UN solo token especial del vocabulario del
        modelo cargado (p.ej. "<|start_header_id|>" en Llama 3)."""
        try:
            tokens = self._llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)
        except Exception:  # noqa: BLE001 - dobles de prueba sin tokenize()
            return False
        return len(tokens) == 1

    def _end_token_ids(self) -> List[int]:
        """Ids de los tokens con los que el modelo termina su turno: el EOS y
        los de corte del formato de chat que son un solo token especial
        (<|eot_id|>, <|im_end|>...). Vacio si no se pueden leer."""
        ids = set()
        try:
            eos = self._llm.token_eos()
            if eos is not None and eos >= 0:
                ids.add(int(eos))
        except Exception:  # noqa: BLE001 - dobles de prueba sin token_eos()
            pass
        for text in self.formatter.stop:
            try:
                tokens = self._llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)
            except Exception:  # noqa: BLE001
                continue
            if len(tokens) == 1:
                ids.add(int(tokens[0]))
        return sorted(ids)

    def _min_length_processor(self, min_tokens: int, prompt_tokens: int):
        """logits_processor de llama.cpp que prohibe los tokens de fin de turno
        hasta que se generaron `min_tokens` tokens; None si no hace falta."""
        return self._logits_processor(min_tokens, prompt_tokens)

    def _logits_processor(self, min_tokens: int, prompt_tokens: int, banned_first: Sequence[int] = ()):
        """logits_processor de llama.cpp: prohibe los tokens de fin de turno
        hasta generar `min_tokens` tokens, y los `banned_first` como primer
        token generado (frases a evitar, B15). None si no hace falta."""
        if self.is_server:
            return None  # a server can't run a local logits processor (see app/server_backend.py)
        end_ids = self._end_token_ids() if min_tokens > 0 else []
        first_ids = list(banned_first)
        if not end_ids and not first_ids:
            return None
        # llama.cpp llama al procesador una vez por token generado, el primero
        # con el prompt ya evaluado: su largo en ese momento es el del prompt
        # tal como lo tokenizo llama.cpp (special=True, su BOS), que
        # _count_tokens() solo aproxima. Asi "primer token" y el minimo son exactos.
        start: List[int] = []

        def processor(input_ids, scores):
            if not start:
                start.append(len(input_ids))
            generated = len(input_ids) - start[0]
            if end_ids and generated < min_tokens:
                scores[end_ids] = -float("inf")
            if first_ids and generated == 0:
                scores[first_ids] = -float("inf")
            return scores

        try:  # llama-cpp-python iterates over a LogitsProcessorList
            from llama_cpp import LogitsProcessorList
        except Exception:  # noqa: BLE001 - dobles de prueba / sin llama_cpp
            return [processor]
        return LogitsProcessorList([processor])

    def _top_tokens(self, rendered: str, top_k: int) -> List[Tuple[str, float]]:
        """Los `top_k` primeros tokens mas probables tras `rendered`, con su probabilidad (sin
        temperatura). Local: un logits processor copia los logits de la primera posicion (asi no
        hace falta logits_all=True); servidor: sus logprobs."""
        top_tokens = getattr(self._llm, "top_tokens", None)
        if callable(top_tokens):  # ServerLlama
            return top_tokens(rendered, top_k)
        import numpy as np

        captured: Dict[str, object] = {}

        def grab(input_ids, scores):
            if "scores" not in captured:
                captured["scores"] = np.array(scores, dtype=np.float64, copy=True)
            return scores

        try:
            from llama_cpp import LogitsProcessorList
            processors = LogitsProcessorList([grab])
        except Exception:  # noqa: BLE001 - dobles de prueba
            processors = [grab]
        self._llm(rendered, max_tokens=1, temperature=0.0, logits_processor=processors)
        scores = captured.get("scores")
        if scores is None:
            return []
        scores = np.asarray(scores, dtype=np.float64)
        scores[np.isinf(scores)] = -1e30
        probs = np.exp(scores - scores.max())
        probs /= probs.sum()
        skip = set(self._end_token_ids())
        out: List[Tuple[str, float]] = []
        for token_id in np.argsort(probs)[::-1][: top_k * 3]:
            if int(token_id) in skip:
                continue
            text = self._llm.detokenize([int(token_id)]).decode("utf-8", errors="ignore")
            if not text or not text.strip(" ") and "\n" not in text:
                continue
            out.append((text, float(probs[token_id])))
            if len(out) >= top_k:
                break
        return out

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
        min_tokens: int = 0,
    ) -> CompletionResult:
        """
        Una llamada al modelo. `min_tokens`: el modelo no puede terminar su
        turno antes de generar esos tokens (ver MIN_SECTION_FRACTION). `prompt` puede ser texto ya armado o un
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
        guard = self.phrase_guard if task in PHRASE_GUARD_TASKS else None
        if guard:
            return self._complete_guarded(guard, text_prompt, max_tokens, stops, task, min_tokens, on_token, cancel_check)
        result, _used = self._run_completion(
            text_prompt, prompt_tokens, max_tokens, stops, task, min_tokens, on_token, cancel_check,
        )
        return result

    def _complete_guarded(
        self, guard: PhraseGuard, text_prompt: str, max_tokens: int, stops: List[str], task: str,
        min_tokens: int, on_token: Optional[Callable[[str], None]], cancel_check: Optional[Callable[[], bool]],
    ) -> CompletionResult:
        """
        _complete_ex con frases a evitar (B15, app/phrase_guard.py). Cuando el
        texto completa una frase de la lista, se detiene la generacion, se
        retrocede hasta justo antes de la frase y se sigue desde ahi (el texto
        aceptado se agrega al prompt, asi llama.cpp reutiliza su cache) con la
        primera palabra de la frase prohibida en esa posicion. Al transmitir se
        retienen los ultimos `guard.max_span` caracteres, asi una frase que se
        va a cortar nunca llega a `on_token`. Si el modelo insiste
        (MAX_REWINDS_AT_ONE_POINT en el mismo lugar, o MAX_REWINDS en total),
        el texto se acepta como quedo.
        """
        hold = guard.max_span
        accepted = ""          # texto ya aceptado en esta llamada
        emitted = 0            # caracteres de `accepted + actual` ya pasados a on_token
        allowed_until = 0      # coincidencias que empiezan antes de esto se aceptan
        bans: dict = {}        # posicion en `accepted` -> ids prohibidos ahi
        tries_at: dict = {}    # posicion -> retrocesos en ese lugar
        remaining, generated, rewinds = max_tokens, 0, 0

        def emit(text: str, final: bool = False) -> None:
            nonlocal emitted
            safe = len(text) if final else max(emitted, len(text) - hold)
            if on_token is not None and safe > emitted:
                on_token(text[emitted:safe])
            emitted = max(emitted, safe)

        while True:
            prompt_text = text_prompt + accepted
            prompt_tokens = self._count_tokens(prompt_text)
            current: List[str] = []
            hit: List[PhraseMatch] = []

            def watch(delta: str, _current=current, _hit=hit, _accepted=accepted) -> bool:
                _current.append(delta)
                text = _accepted + "".join(_current)
                found = guard.search(text, max(allowed_until, len(text) - len(delta) - hold))
                if found is not None and found.start >= emitted:
                    _hit.append(found)
                    return True  # detener: se retrocede
                emit(text)
                return False

            result, used = self._run_completion(
                prompt_text, prompt_tokens, remaining, stops, task, max(0, min_tokens - generated),
                None, cancel_check, banned_first=bans.get(len(accepted), ()), watch=watch,
            )
            generated += used
            remaining -= used
            # Siempre transmitido (watch), asi una frase se detecta al aparecer y no
            # despues de escribir toda la seccion; una respuesta entera (un doble de
            # prueba) pasa por watch() de una vez.
            text = accepted + "".join(current)
            logger.debug("frases a evitar: llamada con %d caracteres aceptados -> %d tokens, %s, termina en %r",
                         len(accepted), used, result.finish_reason, text[-60:])
            match = hit[0] if hit else None
            done = (match is None or result.finish_reason == "cancelled" or remaining <= 0
                    or rewinds >= MAX_REWINDS)
            if match is not None and not done:
                cut = text[: match.start].rstrip()
                cut = text[: max(len(cut), emitted)]
                if tries_at.get(len(cut), 0) >= MAX_REWINDS_AT_ONE_POINT:
                    # El modelo insiste en esta frase aqui: se acepta y se sigue.
                    allowed_until = match.end
                    accepted = text
                    if result.finish_reason != "phrase":
                        done = True
                else:
                    tries_at[len(cut)] = tries_at.get(len(cut), 0) + 1
                    ids = set(bans.get(len(cut), ()))
                    ids.update(self._first_token_ids(match.first_word))
                    bans[len(cut)] = tuple(sorted(ids))
                    rewinds += 1
                    self.stats.phrase_rewinds += 1
                    logger.info("Frase a evitar %r: se retrocede y se sigue de otra forma", match.phrase)
                    accepted = cut
                    continue
            if done or match is None:
                finish = result.finish_reason if result.finish_reason != "phrase" else "length"
                emit(text, final=True)
                self.last_finish_reason = finish
                return CompletionResult(text, finish)

    def _first_token_ids(self, word: str) -> List[int]:
        """Los primeros tokens con los que el modelo empezaria `word` (con y sin
        espacio, minuscula y mayuscula inicial). Vacio si no se puede tokenizar."""
        if self.is_server:
            return []  # the ban needs a logits processor, which a server doesn't run
        ids = set()
        for form in word_variants(word):
            try:
                tokens = self._llm.tokenize(form.encode("utf-8"), add_bos=False, special=False)
            except Exception:  # noqa: BLE001 - dobles de prueba
                continue
            if tokens:
                ids.add(int(tokens[0]))
        return sorted(ids)

    def _run_completion(
        self, text_prompt: str, prompt_tokens: int, max_tokens: int, stops: List[str], task: str,
        min_tokens: int, on_token: Optional[Callable[[str], None]], cancel_check: Optional[Callable[[], bool]],
        banned_first: Sequence[int] = (), watch: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[CompletionResult, int]:
        """Una sola llamada a llama.cpp: devuelve el resultado y los tokens
        generados. `banned_first`: ids prohibidos como PRIMER token generado.
        `watch(delta)` (solo al transmitir) puede detener la generacion
        devolviendo True; el resultado lleva entonces finish_reason "phrase"."""
        call_kwargs = dict(max_tokens=max_tokens, stop=stops)
        call_kwargs.update(self._sampling_kwargs(task))
        processor = self._logits_processor(min_tokens, prompt_tokens, banned_first)
        if processor is not None:
            call_kwargs["logits_processor"] = processor
        # Solo pedimos streaming token a token (llama_cpp.Llama.__call__(...,
        # stream=True), que devuelve un generador en vez de un dict) cuando
        # hay alguien escuchando o alguien que puede cancelar.
        if on_token is not None or cancel_check is not None or watch is not None:
            call_kwargs["stream"] = True

        stats = self.stats
        stats.calls += 1
        stats.prompt_tokens = prompt_tokens
        stats.max_tokens = max_tokens
        stats.n_ctx = self._n_ctx
        stats.prompt_text = text_prompt
        stats.seed = call_kwargs.get("seed")
        stats.sampling = {k: v for k, v in call_kwargs.items() if k not in ("stop", "stream", "max_tokens", "seed", "logits_processor")}
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
            used = int(usage.get("completion_tokens") or (self._count_tokens(text) if text else 0))
            stats.generated_tokens += used
            stats.decode_seconds += elapsed
            if watch is not None and text:
                watch(text)
            if on_token is not None and text:
                on_token(text)
            self.last_finish_reason = choice.get("finish_reason")
            return CompletionResult(text, self.last_finish_reason), used

        # Streaming real: `response` es un generador de fragmentos, cada uno
        # con un delta incremental de texto (NO acumulado; ~1 token cada
        # uno). El ultimo trae finish_reason. La cancelacion se revisa en
        # cada fragmento, asi que Cancelar/Detener corta a mitad de una seccion.
        pieces: List[str] = []
        finish_reason: Optional[str] = None
        first_token_at: Optional[float] = None
        used = 0
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
                used += 1
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
                if watch is not None and watch(delta):
                    finish_reason = "phrase"
                    break
        finally:
            # Cortar el generador de llama-cpp-python lo cierra limpiamente.
            close = getattr(response, "close", None)
            if finish_reason in ("cancelled", "phrase") and callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
        self.last_finish_reason = finish_reason
        return CompletionResult("".join(pieces), finish_reason), used

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
        min_tokens: int = 0,
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
                    on_token=on_token, cancel_check=cancel_check, task=task, min_tokens=min_tokens,
                )
            except ContextOverflowError as exc:
                last_error = exc
                continue
        raise ContextOverflowError(
            S.CONTEXTO_NO_CABE_NI_REDUCIDO
        ) from last_error
