"""
Punto de entrada de StoryForge Local.
"""
from __future__ import annotations

import logging
import os
import sys


def _configure_logging() -> None:
    """
    El .exe se empaqueta sin consola (console=False en storyforge.spec), asi
    que en ese caso los errores registrados con logging (p.ej. un
    autoguardado que no se pudo escribir) van a %APPDATA%\\StoryForge\\
    storyforge.log en vez de perderse. En desarrollo van a la consola.
    """
    from .paths import is_frozen, log_file_path, user_data_dir

    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if is_frozen():
        try:
            log_dir = user_data_dir()
            os.makedirs(log_dir, exist_ok=True)
            logging.basicConfig(
                filename=log_file_path(), level=logging.INFO,
                format=fmt, encoding="utf-8",
            )
            return
        except OSError:
            pass
    logging.basicConfig(level=logging.INFO, format=fmt)


def _log_uncaught_exception(exc_type, exc, tb) -> None:
    """sys.excepthook: un error no capturado (p.ej. al arrancar, antes de
    que exista la ventana) queda en el registro en vez de perderse en el
    .exe sin consola."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("storyforge").critical("Error no capturado", exc_info=(exc_type, exc, tb))


def main() -> None:
    _configure_logging()
    sys.excepthook = _log_uncaught_exception
    from .gui import run
    run()


if __name__ == "__main__":
    sys.exit(main())
