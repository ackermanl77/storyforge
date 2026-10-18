"""
Modelo en un servidor compatible con OpenAI (B14): LM Studio, Ollama, KoboldCpp,
llama-server de llama.cpp, el servidor de llama-cpp-python, vLLM... en esta PC o
en otra de la red (por ejemplo, un modelo de 70B que aqui no cabe).

ServerLlama imita la parte de llama_cpp.Llama que usa el motor: se le llama con el
prompt ya armado por StoryForge (con su formato de chat y la respuesta pre-llenada),
asi que continuar desde el final del capitulo funciona igual que con el modelo
local. Usa /v1/completions (texto, no /v1/chat/completions, que no deja pre-llenar),
transmitido con SSE, y solo la biblioteca estandar.

Lo que un servidor no permite: los logits_processor (el largo minimo de seccion y la
prohibicion del primer token tras cortar un cliche) se ignoran -- las frases se
siguen cortando y reescribiendo, pero sin esa ayuda. Los tokens se cuentan con el
/tokenize del servidor cuando lo tiene (llama-server, llama-cpp-python, KoboldCpp);
si no, se estiman. El contexto y la plantilla de chat se leen de /props cuando el
servidor los publica.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.error
import urllib.request
from typing import Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 600
PROBE_TIMEOUT_S = 8
# Parametros de muestreo que no son del API de OpenAI pero que llama-server,
# KoboldCpp, LM Studio y llama-cpp-python aceptan; si el servidor los rechaza
# (400), se reintenta sin ellos.
EXTRA_SAMPLING = ("min_p", "top_k", "repeat_penalty", "typical_p", "mirostat_mode", "mirostat_tau", "mirostat_eta")
CHARS_PER_TOKEN_ESTIMATE = 3.6


class ServerError(RuntimeError):
    pass


def _root(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


class ServerLlama:
    def __init__(self, base_url: str, model: str = "", api_key: str = "", n_ctx: Optional[int] = None,
                 timeout: float = DEFAULT_TIMEOUT_S):
        self.root = _root(base_url)
        if not self.root.startswith(("http://", "https://")):
            raise ServerError("La dirección del servidor debe empezar con http:// o https://")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.metadata: dict = {}
        self._n_ctx = n_ctx
        self._tokenize_style: Optional[str] = None  # "llama-server", "llama-cpp-python", "kobold", "estimate"
        self._send_extras = True
        models = self._models()
        self.model = model.strip() or (models[0] if models else "")
        self._read_props()

    # -- HTTP ------------------------------------------------------------------------
    def _request(self, path: str, payload: Optional[dict] = None, timeout: Optional[float] = None, stream: bool = False):
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if stream else "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.root + path, data=data, headers=headers, method="POST" if data else "GET")
        return urllib.request.urlopen(request, timeout=timeout or self.timeout)

    def _json(self, path: str, payload: Optional[dict] = None, timeout: float = PROBE_TIMEOUT_S):
        with self._request(path, payload, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _models(self) -> List[str]:
        try:
            data = self._json("/v1/models")
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise ServerError("El servidor rechazó la clave de API") from error
            return []
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ServerError(f"No se pudo conectar con {self.root}: {getattr(error, 'reason', error)}") from error
        return [str(m.get("id")) for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]

    def _read_props(self) -> None:
        """llama-server y llama-cpp-python publican el contexto y la plantilla de chat."""
        try:
            props = self._json("/props")
        except (urllib.error.URLError, OSError, ValueError):
            props = {}
        template = props.get("chat_template")
        if isinstance(template, str) and template.strip():
            self.metadata["tokenizer.chat_template"] = template
        settings = props.get("default_generation_settings") or {}
        n_ctx = settings.get("n_ctx") or props.get("n_ctx")
        if not self._n_ctx and isinstance(n_ctx, int) and n_ctx > 0:
            self._n_ctx = n_ctx
        if not self._n_ctx:
            try:  # KoboldCpp
                value = self._json("/api/extra/true_max_context_length").get("value")
                if isinstance(value, int) and value > 0:
                    self._n_ctx = value
            except (urllib.error.URLError, OSError, ValueError):
                pass

    # -- la interfaz de llama_cpp.Llama que usa el motor ---------------------------------
    def n_ctx(self) -> int:
        return int(self._n_ctx or 8192)

    def token_bos(self) -> int:
        return -1

    def token_eos(self) -> int:
        return -1

    def detokenize(self, tokens, special: bool = False) -> bytes:
        return b""

    def tokenize(self, text: bytes, add_bos: bool = True, special: bool = False) -> List[int]:
        content = text.decode("utf-8", errors="ignore")
        for style in ([self._tokenize_style] if self._tokenize_style else ["llama-server", "llama-cpp-python", "kobold"]):
            try:
                tokens = self._tokenize_with(style, content, add_bos, special)
            except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
                continue
            self._tokenize_style = style
            return tokens
        self._tokenize_style = "estimate"
        return list(range(max(1 if content else 0, int(len(content) / CHARS_PER_TOKEN_ESTIMATE))))

    def _tokenize_with(self, style: str, content: str, add_bos: bool, special: bool) -> List[int]:
        if style == "llama-server":
            data = self._json("/tokenize", {"content": content, "add_special": add_bos, "parse_special": special})
            return [t if isinstance(t, int) else t["id"] for t in data["tokens"]]
        if style == "llama-cpp-python":
            data = self._json("/extras/tokenize", {"input": content, "model": self.model})
            return list(data["tokens"])
        if style == "kobold":
            count = int(self._json("/api/extra/tokencount", {"prompt": content})["value"])
            return list(range(count))
        raise ValueError(style)

    def close(self) -> None:
        pass

    def top_tokens(self, prompt: str, top_k: int) -> List[Tuple[str, float]]:
        """The ``top_k`` most likely next tokens after ``prompt`` with their probabilities (F15),
        through the server's logprobs; [] when it doesn't return them."""
        payload = {"prompt": prompt, "max_tokens": 1, "temperature": 0.0, "logprobs": int(top_k),
                   "n_probs": int(top_k)}
        if self.model:
            payload["model"] = self.model
        try:
            data = self._json("/v1/completions", payload, timeout=DEFAULT_TIMEOUT_S)
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ServerError(f"El servidor no devolvió alternativas: {getattr(error, 'reason', error)}") from error
        pairs = [(token, prob) for token, prob in _top_logprobs(data) if token]
        return sorted(pairs, key=lambda pair: -pair[1])[:top_k]

    def __call__(self, prompt: str, max_tokens: int = 256, stop=None, stream: bool = False, seed=None,
                 logits_processor=None, **sampling):
        payload = {"prompt": prompt, "max_tokens": int(max_tokens), "stream": bool(stream)}
        if self.model:
            payload["model"] = self.model
        if stop:
            payload["stop"] = list(stop)[:16]  # some servers cap the stop list
        if seed is not None:
            payload["seed"] = int(seed)
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
            if sampling.get(key) is not None:
                payload[key] = sampling[key]
        if self._send_extras:
            for key in EXTRA_SAMPLING:
                if sampling.get(key) is not None:
                    payload[key] = sampling[key]
        try:
            response = self._request("/v1/completions", payload, stream=stream)
        except urllib.error.HTTPError as error:
            if error.code == 400 and self._send_extras:
                self._send_extras = False  # a strict server: only OpenAI's own parameters
                return self.__call__(prompt, max_tokens, stop, stream, seed, logits_processor, **sampling)
            detail = error.read().decode("utf-8", errors="replace")[:300]
            raise ServerError(f"El servidor respondió {error.code}: {detail}") from error
        except (urllib.error.URLError, OSError) as error:
            raise ServerError(f"Se perdió la conexión con el servidor: {getattr(error, 'reason', error)}") from error
        if not stream:
            with response:
                data = json.loads(response.read().decode("utf-8"))
            return {"choices": [_choice(data)], "usage": data.get("usage") or {}}
        return _sse_chunks(response)


def _top_logprobs(data: dict) -> List[Tuple[str, float]]:
    """(token, probability) pairs of the first generated position, from an OpenAI-style
    ``logprobs.top_logprobs`` or llama-server's ``completion_probabilities``."""
    choice = (data.get("choices") or [{}])[0]
    logprobs = choice.get("logprobs") or {}
    top = (logprobs.get("top_logprobs") or [None])[0]
    if isinstance(top, dict):
        return [(token, math.exp(value)) for token, value in top.items()]
    content = logprobs.get("content") or []
    if content and isinstance(content[0], dict) and content[0].get("top_logprobs"):
        return [(entry.get("token", ""), math.exp(entry.get("logprob", -99.0))) for entry in content[0]["top_logprobs"]]
    probs = data.get("completion_probabilities") or []
    if probs and isinstance(probs[0], dict):
        return [(entry.get("tok_str", ""), float(entry.get("prob", 0.0))) for entry in probs[0].get("probs", [])]
    return []


def _choice(data: dict) -> dict:
    choice = (data.get("choices") or [{}])[0]
    return {"text": choice.get("text") or "", "finish_reason": choice.get("finish_reason")}


class _Stream:
    """El generador de fragmentos de una respuesta SSE, con close() para cortarla."""

    def __init__(self, response):
        self._response = response
        self._iter = self._chunks()

    def __iter__(self) -> Iterator[dict]:
        return self._iter

    def __next__(self) -> dict:
        return next(self._iter)

    def _chunks(self) -> Iterator[dict]:
        try:
            for raw in self._response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    return
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    raise ServerError(f"El servidor informó un error: {data['error']}")
                yield {"choices": [_choice(data)]}
        finally:
            self.close()

    def close(self) -> None:
        try:
            self._response.close()
        except Exception:  # noqa: BLE001
            pass


def _sse_chunks(response) -> _Stream:
    return _Stream(response)
