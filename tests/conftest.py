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
# Nunca preguntar a GitHub por una versión nueva durante las pruebas (update_check.py).
os.environ["STORYFORGE_UPDATE_FEED_URL"] = "off"


def _retry_tk_init_on_transient_tcl_read() -> None:
    """En los runners Windows de GitHub, crear una ventana Tk a veces falla
    con "Can't find a usable init.tcl (o tk.tcl) ... couldn't read file ...: No error"
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
                # The same transient read failure has shown up as "Can't find a
                # usable init.tcl"/"tk.tcl" and, when init.tcl was half read, as
                # 'invalid command name "tcl_findLibrary"'.
                message = str(exc)
                transient = "Can't find a usable" in message or "tcl_findLibrary" in message
                if not transient or attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))

    init_with_retry._storyforge_retry = True
    tkinter.Tk.__init__ = init_with_retry


_retry_tk_init_on_transient_tcl_read()


try:
    import pytest
except ImportError:  # python -m unittest: no fixtures
    pytest = None

if pytest is not None:

    @pytest.fixture(autouse=True)
    def _no_blocking_message_boxes(monkeypatch):
        """Un messagebox real bloquea para siempre sin nadie que lo cierre
        (en CI una prueba quedo colgada asi hasta el limite del job). Durante
        las pruebas se reemplazan por dobles que solo registran; una prueba que
        quiere un dialogo lo parchea ella misma (eso tiene prioridad). Un
        showerror no esperado -- un error de la app en un callback de Tk --
        hace fallar la prueba con su texto, en vez de colgarla."""
        try:
            from tkinter import messagebox
        except ImportError:
            yield []
            return
        shown = []

        def stub(kind, answer):
            def show(title=None, message=None, **_kwargs):
                shown.append((kind, title, message))
                return answer

            return show

        for kind, answer in (
            ("showerror", "ok"), ("showwarning", "ok"), ("showinfo", "ok"),
            ("askyesno", False), ("askokcancel", False), ("askretrycancel", False),
            ("askyesnocancel", None), ("askquestion", "no"),
        ):
            monkeypatch.setattr(messagebox, kind, stub(kind, answer))
        yield shown
        errors = [message for kind, _title, message in shown if kind == "showerror"]
        if errors:
            pytest.fail("unexpected error dialog(s) during the test:\n" + "\n---\n".join(map(str, errors)))
