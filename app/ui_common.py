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
