"""
Piezas compartidas por los modulos de la ventana principal (app/gui.py y
app/ui_*.py): constantes de la app, ayudantes de cuadros de texto y
LimitedTextBox (cuadro con contador de palabras).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

import customtkinter as ctk

from . import strings_es as S
from .paths import app_root
from .project import count_words
from .strings_es import (
    PURPOSE_OPTIONS,
    STYLE_OPTIONS,
)
from .ui_focus import apply_tab_order
from .ui_dialogs import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_OK,
)

APP_TITLE = S.APP_NAME
# Ver app/paths.py: en el .exe, "dos carpetas arriba de __file__" seria
# _internal\, no la carpeta de StoryForge.exe donde el usuario pone models\.
APP_ROOT = app_root()
MODELS_DIR = os.path.join(APP_ROOT, "models")
WRITING_STYLE_OPTIONS = STYLE_OPTIONS
CHAPTER_PURPOSE_OPTIONS = PURPOSE_OPTIONS
NO_MODELS_LABEL = S.NO_MODELS_LABEL
# Espera tras la ultima tecla antes de filtrar el Lorebook (F11).
LORE_FILTER_DEBOUNCE_MS = 250

# Deshacer/rehacer (Ctrl+Z / Ctrl+Y) en todos los cuadros de texto editables.
UNDO_TEXTBOX_OPTIONS = dict(undo=True, autoseparators=True, maxundo=-1)
# Borde del cuadro de un capitulo mientras el modelo escribe en el (solo lectura).
GENERATING_BORDER_COLOR = "#c9a227"
SELECTED_SIDEBAR_COLOR = ("#9cc3ec", "#3a5f8a")
# Tamaño de la ventana la primera vez, y cuanto de la pantalla puede ocupar como mucho (UI5).
DEFAULT_WINDOW_SIZE = (1100, 800)
MAX_SCREEN_SHARE = 0.92


def fit_window_geometry(saved: str, screen_w: int, screen_h: int) -> str:
    """La geometria guardada ("AnchoxAlto+X+Y"), o la de por defecto, recortada para que quepa en
    una pantalla de screen_w x screen_h (en las mismas unidades); sin posicion si la guardada queda
    fuera de la pantalla (un monitor que ya no esta)."""
    import re

    match = re.fullmatch(r"(\d+)x(\d+)(?:([+-]-?\d+)([+-]-?\d+))?", (saved or "").strip())
    width, height = (int(match.group(1)), int(match.group(2))) if match else DEFAULT_WINDOW_SIZE
    width = max(600, min(width, int(screen_w * MAX_SCREEN_SHARE)))
    height = max(500, min(height, int(screen_h * MAX_SCREEN_SHARE)))
    if match and match.group(3) is not None:
        x, y = int(match.group(3).replace("+-", "-")), int(match.group(4).replace("+-", "-"))
        if 0 <= x <= screen_w - 100 and 0 <= y <= screen_h - 100:
            x, y = min(x, max(0, screen_w - width)), min(y, max(0, screen_h - height))
            return f"{width}x{height}+{x}+{y}"
    return f"{width}x{height}"


# Lo que la etiqueta deja libre a los lados dentro de su contenedor (padx y borde).
WRAP_MARGIN = 28


def fit_label_wrap(label, container=None) -> None:
    """Ajusta el ancho de linea de una etiqueta con wraplength al de su contenedor.

    Las etiquetas de ayuda se crean con un wraplength fijo (900 y parecidos): en una
    ventana mas angosta el texto salia cortado por los dos lados (UI4). El valor fijo
    queda como tope y la etiqueta se reajusta cada vez que el contenedor cambia de tamaño."""
    cap = label.cget("wraplength")
    if not cap or getattr(label, "_wrap_cap", None) is not None:
        return
    label._wrap_cap = cap
    container = container or label.master

    def refit(_event=None) -> None:
        if not label.winfo_exists():
            return
        room = int(container.winfo_width() / label._get_widget_scaling()) - WRAP_MARGIN
        if room > 80 and min(cap, room) != label.cget("wraplength"):
            label.configure(wraplength=min(cap, room))

    container.bind("<Configure>", refit, add="+")
    refit()


def keep_labels_inside(root) -> None:
    """fit_label_wrap() para toda etiqueta que se muestre en la app, tambien las de los
    dialogos y las que se crean despues (se engancha al <Map> de su tk.Label interno)."""
    def on_map(event) -> None:
        label = getattr(event.widget, "master", None)
        if isinstance(label, ctk.CTkLabel):
            fit_label_wrap(label)

    root.bind_all("<Map>", on_map, add="+")


def _set_text_readonly_content(box, text: str) -> None:
    """Reemplaza el texto de un CTkTextbox aunque este en solo lectura
    (state="disabled" tambien bloquea insert/delete programaticos)."""
    state = box.cget("state")
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("1.0", text)
    box.configure(state=state)


def _append_text(box, text: str) -> None:
    state = box.cget("state")
    box.configure(state="normal")
    box.insert("end", text)
    box.configure(state=state)


def _parse_optional_int(text: str) -> Optional[int]:
    text = (text or "").strip()
    return int(text) if text else None


class LimitedTextBox(ctk.CTkFrame):
    """
    Textbox con contador de palabras en vivo y limite maximo visible.
    Opcionalmente muestra botones "Importar desde archivo..." (siempre
    sincrono, no toca el motor) y/o "Expandir con IA" (llama al motor: se
    deshabilita durante self.app.busy, ver StoryForgeApp._set_engine_busy()).
    """

    def __init__(
        self, master, label: str, max_words: int, height: int = 160,
        on_expand: Optional[Callable[[], None]] = None,
        on_import: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.max_words = max_words
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text=label, font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w")
        self.counter_label = ctk.CTkLabel(header, text=S.CONTADOR_PALABRAS_VACIO.format(max_words=max_words))
        self.counter_label.grid(row=0, column=1, sticky="e")

        self.import_btn = None
        self.expand_btn = None
        text_row = 1
        if on_expand or on_import:
            btn_bar = ctk.CTkFrame(self, fg_color="transparent")
            btn_bar.grid(row=1, column=0, sticky="w", padx=4, pady=(2, 0))
            if on_import:
                self.import_btn = ctk.CTkButton(
                    btn_bar, text=S.IMPORTAR_DESDE_ARCHIVO, width=170, command=on_import
                )
                self.import_btn.pack(side="left", padx=(0, 6))
            if on_expand:
                self.expand_btn = ctk.CTkButton(btn_bar, text=S.EXPANDIR_CON_IA, width=140, command=on_expand)
                self.expand_btn.pack(side="left")
            text_row = 2

        self.textbox = ctk.CTkTextbox(self, height=height, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.textbox.grid(row=text_row, column=0, sticky="nsew", padx=4, pady=4)
        self.grid_rowconfigure(text_row, weight=1)
        self.textbox.bind("<KeyRelease>", self._on_change)
        self._bind_tab_order()

    def _on_change(self, _event=None) -> None:
        words = count_words(self.get())
        over = words > self.max_words
        color = COLOR_ERROR if over else (COLOR_OK if words > 0 else COLOR_MUTED)
        self.counter_label.configure(text=S.CONTADOR_PALABRAS.format(words=words, max_words=self.max_words), text_color=color)

    def get(self) -> str:
        return self.textbox.get("1.0", "end-1c")

    def set(self, text: str, undoable: bool = False) -> None:
        """Reemplaza el contenido. Con `undoable=True` (p.ej. "Expandir con
        IA") Ctrl+Z vuelve al texto anterior; si no (cargar un proyecto), se
        limpia la pila de deshacer para no "deshacer" hacia otro proyecto."""
        if undoable:
            self.textbox.configure(autoseparators=False)
            self.textbox.edit_separator()
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text or "")
        if undoable:
            self.textbox.edit_separator()
            self.textbox.configure(autoseparators=True)
        else:
            self.textbox.edit_reset()
        self._on_change()

    def focus_order_widgets(self):
        return [btn for btn in (self.import_btn, self.expand_btn, self.textbox) if btn is not None]

    def _bind_tab_order(self) -> None:
        apply_tab_order(self, self.focus_order_widgets())
