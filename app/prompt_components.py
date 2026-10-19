"""
Componentes de prompt (F20): textos con nombre que se reutilizan en cualquier
proyecto -- una guia de estilo, el tono de una saga, reglas de formato --
escribiendo {@nombre} en el prompt propio de un capitulo o en los campos del
generador de historias. Al armar el prompt, cada {@nombre} se reemplaza por su
texto (que puede tener a su vez marcadores como {plot} o {notas}); un nombre
que no existe queda tal cual, para que se note.

Se guardan en user_data_dir()/componentes_prompt.json, compartidos por todos
los proyectos (como los presets del generador).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List

from . import strings_es as S
from .fileutil import atomic_write_text
from .paths import user_data_dir
from .project import count_words

logger = logging.getLogger(__name__)

MAX_COMPONENTS = 100
MAX_COMPONENT_WORDS = 1500
NAME_RE = re.compile(r"^[\w\-]{1,40}$", re.UNICODE)
COMPONENT_RE = re.compile(r"\{@([\w\-]{1,40})\}", re.UNICODE)


def components_path() -> str:
    return os.path.join(user_data_dir(), "componentes_prompt.json")


def load_components() -> Dict[str, str]:
    try:
        with open(components_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("No se pudieron leer los componentes de prompt: %s", exc)
        return {}
    items = data.get("componentes") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    return {name: text for name, text in list(items.items())[:MAX_COMPONENTS]
            if isinstance(name, str) and NAME_RE.match(name) and isinstance(text, str)}


def _write(components: Dict[str, str]) -> None:
    atomic_write_text(components_path(), json.dumps({"componentes": components}, ensure_ascii=False, indent=2))


def clean_name(name: str) -> str:
    """Nombre normalizado: espacios por guiones bajos; ValueError si no sirve."""
    name = re.sub(r"\s+", "_", (name or "").strip())
    if not NAME_RE.match(name):
        raise ValueError(S.COMPONENTE_NOMBRE_INVALIDO)
    return name


def save_component(name: str, text: str) -> str:
    """Crea o reemplaza un componente; devuelve el nombre guardado."""
    name = clean_name(name)
    if not (text or "").strip():
        raise ValueError(S.COMPONENTE_VACIO)
    if count_words(text) > MAX_COMPONENT_WORDS:
        raise ValueError(S.COMPONENTE_DEMASIADO_LARGO.format(maximum=MAX_COMPONENT_WORDS))
    components = load_components()
    if name not in components and len(components) >= MAX_COMPONENTS:
        raise ValueError(S.COMPONENTES_MAXIMO.format(maximum=MAX_COMPONENTS))
    components[name] = text.strip()
    _write(components)
    return name


def delete_component(name: str) -> bool:
    components = load_components()
    if name not in components:
        return False
    del components[name]
    _write(components)
    return True


def expand_components(text: str, components: Dict[str, str] | None = None) -> str:
    """`text` con cada {@nombre} reemplazado por su componente (un nivel: un componente no
    expande otros, asi que no hay ciclos). Los nombres desconocidos quedan tal cual."""
    if not text or "{@" not in text:
        return text
    components = load_components() if components is None else components
    return COMPONENT_RE.sub(lambda match: components.get(match.group(1), match.group(0)), text)


def used_components(text: str) -> List[str]:
    return list(dict.fromkeys(COMPONENT_RE.findall(text or "")))
