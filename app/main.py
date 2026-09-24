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
    from .paths import is_frozen, user_data_dir

    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if is_frozen():
        try:
            log_dir = user_data_dir()
            os.makedirs(log_dir, exist_ok=True)
            logging.basicConfig(
                filename=os.path.join(log_dir, "storyforge.log"), level=logging.INFO,
                format=fmt, encoding="utf-8",
            )
            return
        except OSError:
            pass
    logging.basicConfig(level=logging.INFO, format=fmt)


def main() -> None:
    _configure_logging()
    from .gui import run
    run()


if __name__ == "__main__":
    sys.exit(main())
