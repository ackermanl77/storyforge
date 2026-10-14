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


def _parse_args(argv):
    import argparse

    from . import strings_es as S
    from .web_server import DEFAULT_PORT

    parser = argparse.ArgumentParser(prog="StoryForge")
    parser.add_argument("--servidor", action="store_true", help=S.WEB_AYUDA_SERVIDOR)
    parser.add_argument("--generador", action="store_true", help=S.WEB_AYUDA_GENERADOR)
    parser.add_argument("--puerto", type=int, default=DEFAULT_PORT, help=S.WEB_AYUDA_PUERTO.format(port=DEFAULT_PORT))
    parser.add_argument("--carpeta", default=None, help=S.WEB_AYUDA_CARPETA)
    parser.add_argument("--modelos", default=None, help=S.WEB_AYUDA_MODELOS)
    parser.add_argument("--sin-navegador", action="store_true", help=S.WEB_AYUDA_SIN_NAVEGADOR)
    # parse_known_args: un argumento ajeno (p.ej. un archivo soltado sobre el .exe) no impide abrir la app.
    return parser.parse_known_args(argv)[0]


def main(argv=None) -> int:
    _configure_logging()
    sys.excepthook = _log_uncaught_exception
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.servidor or args.generador:
        # StoryForge en el celular (app/web_server.py): sin ventana.
        from .web_server import serve

        return serve(port=args.puerto, projects_dir=args.carpeta, open_browser=not args.sin_navegador,
                     models_dir=args.modelos, generator_page=args.generador)
    from .gui import run
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
