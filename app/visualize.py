"""
Visualizar una entrada del lorebook (F25): el texto de un personaje o un lugar
se manda a un PixelFlow local (la app de imagenes por nodos del mismo autor) y
la imagen vuelve como miniatura de la entrada. Todo queda en esta PC: se usan
los modelos y el flujo de trabajo guardado del usuario.

Se habla con la API HTTP local de PixelFlow, la misma que usa su servidor MCP:
el flujo guardado trae su "prompt" listo para ejecutar
(extra.pixelflow_prompt); se reemplaza el texto del CLIP Text Encode que
alimenta la entrada "positive" del sampler, se encola (POST /api/queue) y se
espera (GET /api/history/<id>) a que termine; la imagen se descarga de
/outputs/<archivo> o /temp/<archivo>.
"""
from __future__ import annotations

import base64

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

DEFAULT_PIXELFLOW_URL = "http://127.0.0.1:8288"
SAVED_PROMPT_KEY = "pixelflow_prompt"
TIMEOUT_S = 600
POLL_S = 0.5
THUMBNAIL_SIDE = 256


class VisualizeError(RuntimeError):
    pass


def _request(base_url: str, method: str, path: str, body: Any = None, raw: bool = False, opener=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=30) as response:  # noqa: S310 -- local PixelFlow
            payload = response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail, ensure_ascii=False)
        raise VisualizeError(f"PixelFlow respondió {exc.code}: {detail or exc.reason}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise VisualizeError(f"No se pudo conectar con PixelFlow en {base_url} ({exc}). ¿Está abierto?") from None
    return payload if raw else json.loads(payload.decode("utf-8") or "null")


def list_workflows(base_url: str = DEFAULT_PIXELFLOW_URL, opener=None) -> List[str]:
    return [item["name"] for item in _request(base_url, "GET", "/api/workflows", opener=opener) or []
            if isinstance(item, dict) and item.get("name")]


def positive_text_nodes(prompt: Dict[str, Any]) -> List[str]:
    """Los nodos de texto que alimentan una entrada "positive" (el prompt
    positivo); si el flujo no tiene, todos los nodos con una entrada "text"."""
    ids = []
    for node in prompt.values():
        link = (node.get("inputs") or {}).get("positive")
        if isinstance(link, list) and link and str(link[0]) in prompt:
            ids.append(str(link[0]))
    if ids:
        return sorted(set(ids))
    return [node_id for node_id, node in prompt.items() if isinstance((node.get("inputs") or {}).get("text"), str)]


def portrait_prompt(name: str, description: str, kind: str = "personaje") -> str:
    text = " ".join((description or "").split())[:600]
    subject = "portrait of" if kind == "personaje" else "illustration of"
    return f"{subject} {name.strip()}: {text}, detailed, high quality".strip()


def generate_image(text: str, workflow: str, base_url: str = DEFAULT_PIXELFLOW_URL, opener=None,
                   sleep: Callable[[float], None] = time.sleep, cancel_check: Optional[Callable[[], bool]] = None) -> bytes:
    """Ejecuta el flujo `workflow` de PixelFlow con `text` como prompt positivo y
    devuelve la primera imagen (bytes PNG)."""
    data = _request(base_url, "GET", f"/api/workflows/{urllib.parse.quote(workflow, safe='')}", opener=opener)
    prompt = (data.get("extra") or {}).get(SAVED_PROMPT_KEY) if isinstance(data, dict) else None
    if not isinstance(prompt, dict) or not prompt:
        raise VisualizeError(f"El flujo «{workflow}» se guardó con un PixelFlow viejo: ábrelo y guárdalo una vez.")
    prompt = json.loads(json.dumps(prompt))
    targets = positive_text_nodes(prompt)
    if not targets:
        raise VisualizeError(f"El flujo «{workflow}» no tiene un nodo de texto para el prompt.")
    for node_id in targets:
        prompt[node_id]["inputs"]["text"] = text
    queued = _request(base_url, "POST", "/api/queue", {"prompt": prompt, "client_id": "storyforge"}, opener=opener)
    prompt_id = queued["prompt_id"]
    deadline = time.monotonic() + TIMEOUT_S
    while True:
        if cancel_check is not None and cancel_check():
            raise VisualizeError("Cancelado.")
        entry = _request(base_url, "GET", f"/api/history/{urllib.parse.quote(prompt_id)}", opener=opener) or {}
        status = entry.get("status")
        if status == "completed":
            break
        if status in ("error", "interrupted", "cancelled"):
            raise VisualizeError(f"PixelFlow no pudo generar la imagen ({entry.get('error') or status}).")
        if time.monotonic() >= deadline:
            raise VisualizeError("PixelFlow tardó demasiado.")
        sleep(POLL_S)
    for output in (entry.get("outputs") or {}).values():
        if isinstance(output, dict) and output.get("images"):
            folder = "temp" if output.get("type") == "temp" else "outputs"
            name = output["images"][0]
            return _request(base_url, "GET", f"/{folder}/{urllib.parse.quote(name)}", raw=True, opener=opener)
    raise VisualizeError("El flujo terminó sin ninguna imagen: agrégale un Save Image o Preview Image.")


def thumbnail_b64(image_bytes: bytes, side: int = THUMBNAIL_SIDE, master=None) -> str:
    """La imagen reducida (lado mayor <= ~`side` px, por un factor entero) como PNG
    en base64 -- lo que guarda la entrada. Con el PNG de Tk (la app no usa Pillow);
    necesita una ventana Tk existente (`master`, o la ventana por defecto)."""
    import math
    import os
    import tempfile
    import tkinter as tk

    photo = tk.PhotoImage(master=master, data=base64.b64encode(image_bytes).decode("ascii"))
    factor = max(1, math.ceil(max(photo.width(), photo.height()) / side))
    small = photo.subsample(factor) if factor > 1 else photo
    handle, path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    try:
        small.write(path, format="png")
        with open(path, "rb") as file:
            return base64.b64encode(file.read()).decode("ascii")
    finally:
        os.remove(path)
