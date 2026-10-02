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
