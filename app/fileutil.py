"""
Escritura atomica de archivos, compartida por Project.save(), settings.json y
las exportaciones (.txt/.md/.docx/.epub).

Se escribe a un archivo temporal en la misma carpeta y se reemplaza el
destino con os.replace(): un fallo a mitad de escritura (disco lleno, cierre
inesperado) nunca deja el archivo truncado.

En Windows, os.replace() falla con PermissionError si otro proceso (el
cliente de OneDrive, un antivirus, el indexador) tiene el destino abierto un
instante -- el proyecto vive justamente en una carpeta de OneDrive. Por eso
se reintenta unas cuantas veces con una espera corta antes de rendirse.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Callable, Optional, Union

PathLike = Union[str, Path]

REPLACE_RETRIES = 6
REPLACE_FIRST_DELAY_SECONDS = 0.05


def replace_with_retry(src: PathLike, dst: PathLike, retries: int = REPLACE_RETRIES,
                       first_delay: float = REPLACE_FIRST_DELAY_SECONDS,
                       sleep: Callable[[float], None] = time.sleep) -> None:
    """os.replace() que reintenta ante PermissionError (archivo tomado un
    instante por otro proceso), con espera exponencial: 0.05, 0.1, 0.2 s..."""
    delay = first_delay
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            sleep(delay)
            delay *= 2


def atomic_write_bytes(path: PathLike, data: bytes, backup: bool = False) -> None:
    """Escribe `data` en `path` de forma atomica. Con `backup=True`, la version
    anterior (si existia) se conserva como `<archivo>.bak`."""
    path = Path(path)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        replace_with_retry(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def atomic_write_text(path: PathLike, text: str, backup: bool = False, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding), backup=backup)


def atomic_write_with(path: PathLike, writer: Callable[[str], None], backup: bool = False) -> None:
    """Para librerias que solo saben guardar a una ruta (p.ej. python-docx):
    `writer(tmp_path)` escribe el archivo temporal y despues se reemplaza el
    destino de forma atomica."""
    path = Path(path)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        writer(str(tmp_path))
        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        replace_with_retry(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def is_under(path: str, folder: Optional[str]) -> bool:
    """True si `path` esta dentro de `folder` (comparacion sin distinguir
    mayusculas en Windows)."""
    if not path or not folder:
        return False
    try:
        path_abs = os.path.normcase(os.path.abspath(path))
        folder_abs = os.path.normcase(os.path.abspath(folder))
        return os.path.commonpath([path_abs, folder_abs]) == folder_abs
    except ValueError:  # distinta unidad en Windows
        return False
