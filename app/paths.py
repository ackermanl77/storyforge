"""
Rutas base de la app, compartidas por gui.py y repetition.py.

En desarrollo (python storyforge.py) la raiz es la carpeta del proyecto, dos
niveles arriba de este archivo. En el .exe empaquetado (PyInstaller 6,
modo onedir) __file__ vive dentro de _internal\\, asi que "dos niveles
arriba" apuntaria a _internal\\ en vez de a la carpeta donde esta
StoryForge.exe -- que es donde el README le dice al usuario que ponga
models\\. Por eso, cuando sys.frozen, la raiz es la carpeta del ejecutable.
"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> str:
    """Carpeta donde viven models\\ y nltk_data\\ (junto al .exe si esta empaquetado)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user_data_dir() -> str:
    """
    Carpeta escribible por el usuario para autoguardado y logs. En el .exe se
    usa %APPDATA%\\StoryForge: la carpeta del programa puede no ser
    escribible (p.ej. si se copio a Program Files). En desarrollo se sigue
    usando la carpeta del proyecto, como siempre.

    La variable de entorno STORYFORGE_USER_DATA_DIR, si esta definida, tiene
    prioridad en ambos casos: la usan las pruebas (para no tocar nunca el
    autoguardado real del usuario) y sirve tambien para una instalacion
    portable. Se lee en cada llamada, no una sola vez al importar.
    """
    override = os.environ.get("STORYFORGE_USER_DATA_DIR", "").strip()
    if override:
        return os.path.abspath(override)
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "StoryForge")
    return app_root()


def log_file_path() -> str:
    """Archivo de registro del .exe (en desarrollo el registro va a la consola)."""
    return os.path.join(user_data_dir(), "storyforge.log")
