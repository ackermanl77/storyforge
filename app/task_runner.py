"""
EngineTaskRunner: la UNICA forma en que la interfaz ejecuta algo con el
modelo en segundo plano (F12).

Antes el mismo patron (comprobar el candado, crear un hilo, tres bloques
except, after(0, ...), un finally que suelta el candado y autoguarda) estaba
copiado cinco veces en gui.py, con pequenas diferencias. Ahora cada accion
solo describe que hacer (`work`) y que hacer con el resultado (`on_success`);
el runner se ocupa de:

- el candado global del motor (StoryForgeApp._set_engine_busy);
- "Detener": un flag propio + LocalStoryEngine.request_stop(), que el motor
  revisa en cada token (cancel_check);
- la barra de estado (operacion, tiempo, tokens/s, contexto);
- traducir los errores a un mensaje (capturando el texto ANTES de salir del
  except: `exc` se borra al terminar el bloque y after() lo usaria despues);
- el autoguardado al terminar.
"""
from __future__ import annotations

import inspect
import logging
import threading
from tkinter import messagebox
from typing import Any, Callable, Optional

from . import strings_es as S
from .error_text import describe_exception
from .engine import ContextOverflowError, ModelNotLoadedError, OperationCancelled
from .strings_es import APP_NAME

logger = logging.getLogger("app.gui")


def call_supported(fn: Callable, *args, **kwargs):
    """Llama a `fn` pasando solo los argumentos con nombre que acepta: los
    motores de prueba (y versiones viejas) no conocen cancel_check/on_token."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


class EngineTaskRunner:
    def __init__(self, app) -> None:
        self.app = app
        self._cancel = threading.Event()
        self.running_label: Optional[str] = None

    # ---- detener ----
    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def cancel_check(self) -> bool:
        return self._cancel.is_set()

    def request_stop(self) -> None:
        if self.running_label is None:
            return
        self._cancel.set()
        stop = getattr(self.app.engine, "request_stop", None)
        if callable(stop):
            stop()

    # ---- ejecucion ----
    def run(
        self,
        label: str,
        work: Callable[[Callable[[], bool]], Any],
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[BaseException], Optional[str]]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        on_finally: Optional[Callable[[], None]] = None,
        error_prefix: str = "",
        autosave: bool = True,
    ) -> None:
        """
        Ejecuta `work(cancel_check)` en un hilo. En el hilo principal:
        `on_success(resultado)`, u `on_cancel()` si se detuvo, u
        `on_error(exc)` (que puede devolver el mensaje a mostrar, o "" para
        no mostrar nada) / un mensaje de error estandar; siempre `on_finally()`.
        """
        app = self.app
        self._cancel.clear()
        clear = getattr(app.engine, "clear_stop", None)
        if callable(clear):
            clear()
        self.running_label = label
        app._set_engine_busy(True)
        status_bar = getattr(app, "status_bar", None)
        if status_bar is not None:
            status_bar.start(label)

        def deliver(fn, *args) -> None:
            if fn is not None:
                app.after(0, lambda: fn(*args))

        def show_error(message: str) -> None:
            app.after(0, lambda: messagebox.showerror(APP_NAME, message))

        def worker() -> None:
            outcome = "error"
            try:
                result = work(self.cancel_check)
                outcome = "ok"
                deliver(on_success, result)
            except OperationCancelled:
                outcome = "cancelled"
                deliver(on_cancel)
            except Exception as exc:  # noqa: BLE001
                message: Optional[str] = None
                if on_error is not None:
                    message = on_error(exc)
                if message is None:
                    if isinstance(exc, ModelNotLoadedError):
                        message = str(exc)
                    elif isinstance(exc, ContextOverflowError):
                        message = S.EL_CONTEXTO_ES_DEMASIADO_GRANDE.format(exc=exc)
                    else:
                        logger.exception("Error en '%s'", label)
                        shown = describe_exception(exc)
                        message = f"{error_prefix}{shown}" if error_prefix else S.ERROR_GENERICO.format(exc=shown)
                if message:
                    show_error(message)
            finally:
                def finish(_outcome=outcome) -> None:
                    self.running_label = None
                    if status_bar is not None:
                        status_bar.stop(_outcome)
                    if on_finally is not None:
                        on_finally()
                    if autosave:
                        app._autosave()
                    app._set_engine_busy(False)
                app.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()
