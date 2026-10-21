"""Cargar y descargar el modelo de LocalStoryEngine (R6: separado de engine.py): el GGUF local
con sus opciones (contexto, capas en GPU, cache KV), la conexion a un servidor compatible con
OpenAI y el formato de chat. Un mixin de LocalStoryEngine."""

from __future__ import annotations

import gc
import logging
import os
from typing import Optional

from . import strings_es as S
from .chat_format import (
    CHAT_FORMAT_AUTO,
)
from .cuda_env import _ensure_cuda_dlls_discoverable
from .engine_types import (
    GGML_KV_TYPES,
)
from .gguf import KV_CACHE_TYPES, friendly_load_error, missing_shards, model_info

logger = logging.getLogger("app.engine")


class ModelMixin:
    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    @property
    def model_path(self) -> Optional[str]:
        return self._model_path

    @property
    def n_ctx(self) -> int:
        return self._n_ctx

    @property
    def is_server(self) -> bool:
        """True when the model runs on an OpenAI-compatible server (connect_server)."""
        from .server_backend import ServerLlama

        return isinstance(self._llm, ServerLlama)

    def connect_server(self, base_url: str, model: str = "", api_key: str = "", n_ctx: Optional[int] = None,
                       chat_format: Optional[str] = None) -> None:
        """
        Usa un modelo de un servidor compatible con OpenAI (B14, app/server_backend.py):
        LM Studio, Ollama, KoboldCpp, llama-server... `model` vacio = el primero que
        ofrece el servidor; `n_ctx` vacio = el que publica el servidor (o 8192).
        Lanza ServerError con un mensaje para el usuario si no se puede conectar.
        """
        from .server_backend import ServerLlama

        if chat_format is not None:
            self.set_chat_format(chat_format)
        llm = ServerLlama(base_url, model=model, api_key=api_key, n_ctx=n_ctx)
        self.unload()
        self._llm = llm
        self._model_path = f"{llm.root} ({llm.model or 'servidor'})"
        self._n_ctx = llm.n_ctx()
        self.model_info = None
        self.load_options = dict(n_ctx=self._n_ctx, server=llm.root, model=llm.model)

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
