"""
Preferencias del usuario que no pertenecen a un proyecto (settings.json en
user_data_dir(): %APPDATA%\\StoryForge en el .exe, la carpeta del proyecto en
desarrollo, o STORYFORGE_USER_DATA_DIR si esta definida).

Que va aqui y que va en el proyecto:
- Proyecto (Project): que modelo y que contexto (n_ctx) se usaron, el
  muestreo, la nota del autor... lo que define la HISTORIA.
- settings.json: lo que depende de ESTA PC, por modelo (capas en GPU, hilos,
  flash attention, lote, tipo de cache KV, formato de chat), el ultimo modelo
  cargado, y preferencias de la interfaz (tema, escala, fuente del editor,
  carpeta de modelos adicional).

Un archivo ilegible o corrupto se ignora: nunca debe impedir que la app arranque.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from .fileutil import atomic_write_text
from .paths import user_data_dir

logger = logging.getLogger(__name__)

# Opciones de carga que se recuerdan por modelo (ver LocalStoryEngine.load).
MODEL_SETTING_KEYS = ("n_ctx", "n_gpu_layers", "n_threads", "flash_attn", "n_batch", "n_ubatch", "kv_cache_type")

UI_DEFAULTS = {
    "appearance": "dark",   # "dark", "light" o "system"
    "ui_scale": 1.0,
    "editor_font_family": "",  # "" = la fuente por defecto de CustomTkinter
    "editor_font_size": 14,
    "editor_line_spacing": 4,
    "models_dir": "",       # carpeta de modelos adicional (p.ej. fuera de OneDrive)
}


def settings_path() -> str:
    return os.path.join(user_data_dir(), "settings.json")


def load_settings() -> dict:
    path = settings_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo leer %s; se usan valores por defecto", path)
        return {}


def save_settings(data: dict) -> None:
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _update(mutator) -> None:
    """Lee, modifica y guarda; un error al escribir se registra y se ignora
    (son solo preferencias)."""
    try:
        data = load_settings()
        mutator(data)
        save_settings(data)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudieron guardar las preferencias")


def _model_key(model_path: str) -> str:
    return os.path.basename(model_path or "").lower()


# ---------------- formato de chat por modelo ----------------
def get_chat_format_for_model(model_path: str) -> Optional[str]:
    value = load_settings().get("chat_format_by_model", {}).get(_model_key(model_path))
    return value if isinstance(value, str) else None


def set_chat_format_for_model(model_path: str, chat_format: str) -> None:
    """Recuerda el formato de chat elegido para este modelo."""
    def mutate(data: dict) -> None:
        by_model = data.get("chat_format_by_model")
        if not isinstance(by_model, dict):
            by_model = {}
        by_model[_model_key(model_path)] = chat_format
        data["chat_format_by_model"] = by_model
    _update(mutate)


# ---------------- opciones de carga por modelo ----------------
def get_model_settings(model_path: str) -> dict:
    """Ultimas opciones de carga usadas con este modelo en esta PC ({} si nunca)."""
    by_model = load_settings().get("model_settings", {})
    value = by_model.get(_model_key(model_path)) if isinstance(by_model, dict) else None
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if k in MODEL_SETTING_KEYS}


def set_model_settings(model_path: str, options: dict) -> None:
    def mutate(data: dict) -> None:
        by_model = data.get("model_settings")
        if not isinstance(by_model, dict):
            by_model = {}
        by_model[_model_key(model_path)] = {k: options.get(k) for k in MODEL_SETTING_KEYS if k in options}
        data["model_settings"] = by_model
        data["last_model"] = model_path
    _update(mutate)


def get_last_model() -> Optional[str]:
    value = load_settings().get("last_model")
    return value if isinstance(value, str) and value else None


# ---------------- modelo en un servidor (B14) ----------------
def get_server_settings() -> dict:
    """URL, modelo y clave del ultimo servidor usado (la clave queda en settings.json, como texto)."""
    stored = load_settings().get("server")
    out = {"url": "http://127.0.0.1:1234/v1", "model": "", "api_key": ""}
    if isinstance(stored, dict):
        for key in out:
            if isinstance(stored.get(key), str):
                out[key] = stored[key][:500]
    return out


def set_server_settings(url: str, model: str, api_key: str) -> None:
    def mutate(data: dict) -> None:
        data["server"] = {"url": url.strip(), "model": model.strip(), "api_key": api_key.strip()}

    _update(mutate)


def get_embedding_model() -> str:
    """El GGUF de embeddings para Recordar pasajes anteriores (B16), o "" para BM25."""
    value = load_settings().get("embedding_model")
    return value if isinstance(value, str) else ""


def set_embedding_model(path: str) -> None:
    def mutate(data: dict) -> None:
        if path:
            data["embedding_model"] = path
        else:
            data.pop("embedding_model", None)

    _update(mutate)


# ---------------- preferencias de interfaz ----------------
def get_ui_preferences() -> dict:
    prefs = dict(UI_DEFAULTS)
    stored = load_settings().get("ui")
    if isinstance(stored, dict):
        for key, default in UI_DEFAULTS.items():
            value = stored.get(key, default)
            if isinstance(value, type(default)) or (isinstance(default, float) and isinstance(value, int)):
                prefs[key] = value
    return prefs


def set_ui_preferences(prefs: dict) -> None:
    def mutate(data: dict) -> None:
        current = data.get("ui") if isinstance(data.get("ui"), dict) else {}
        current.update({k: v for k, v in prefs.items() if k in UI_DEFAULTS})
        data["ui"] = current
    _update(mutate)
