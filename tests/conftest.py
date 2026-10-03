"""
Configuracion comun de pytest: todo lo que la app escribe en user_data_dir()
(autoguardado, settings.json) va a una carpeta temporal de la sesion de
pruebas, nunca a la del usuario (ver app/paths.py, STORYFORGE_USER_DATA_DIR).
tests/test_gui.py hace lo mismo por su cuenta para `python -m unittest`.
"""
import os
import tempfile

_SESSION_DIR = tempfile.TemporaryDirectory(prefix="storyforge-pytest-")
os.environ.setdefault("STORYFORGE_USER_DATA_DIR", _SESSION_DIR.name)


def _retry_tk_init_on_transient_tcl_read() -> None:
    """En los runners Windows de GitHub, crear una ventana Tk a veces falla
    con "Can't find a usable init.tcl ... couldn't read file ...: No error"
    (una lectura que falla un instante, no un Tcl roto: la siguiente ventana
    se crea bien). Las pruebas reintentan ese error puntual; la app no cambia."""
    try:
        import tkinter
    except ImportError:
        return
    if getattr(tkinter.Tk.__init__, "_storyforge_retry", False):
        return
    original_init = tkinter.Tk.__init__

    def init_with_retry(self, *args, **kwargs):
        import time

        for attempt in range(5):
            try:
                return original_init(self, *args, **kwargs)
            except tkinter.TclError as exc:
                if "init.tcl" not in str(exc) or attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))

    init_with_retry._storyforge_retry = True
    tkinter.Tk.__init__ = init_with_retry


_retry_tk_init_on_transient_tcl_read()
