"""
Interfaz grafica de escritorio (CustomTkinter) para StoryForge Local.

Modulos relacionados: app/task_runner.py (como se ejecuta cualquier tarea
del modelo en segundo plano), app/ui_status.py (barra de estado),
app/ui_dialogs.py (vista previa con diferencias, buscar en el proyecto,
preferencias, visor de prompt) y app/strings_es.py (etiquetas visibles).
"""
from __future__ import annotations

import logging
import os
import platform
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Dict, List, Optional

import customtkinter as ctk

from . import __version__
from .chat_format import (
    CHAT_FORMAT_AUTO,
    CHAT_FORMAT_CHOICES,
    CHAT_FORMAT_LABELS,
    chat_format_from_label,
)
from .engine import (
    ContextOverflowError,  # noqa: F401 - reexportado para las pruebas
    LocalStoryEngine,
    ModelNotLoadedError,  # noqa: F401 - reexportado para las pruebas
    OperationCancelled,
    supports_gpu_offload,
)
from .export import export_docx, export_epub, export_markdown, export_txt
from .gguf import (
    KV_CACHE_TYPES,
    estimate_vram,
    list_model_entries,
    model_info,
    query_free_vram_bytes,
    query_total_ram_bytes,
)
from .paths import app_root, is_frozen, log_file_path, user_data_dir
from .project import (
    CHAPTER_HEADING_CHOICES,
    CHAPTER_PURPOSES,
    DEFAULT_PROJECT_NAME,
    MAX_AUTHOR_NOTE_WORDS,
    MAX_CHAPTERS,
    MAX_CHARACTERS_WORDS,
    MAX_LORE_ENTRIES,
    MAX_OUTLINE_WORDS_PER_CHAPTER,
    MAX_PLOT_WORDS,
    MAX_SETTING_WORDS,
    MAX_WORDS_PER_CHAPTER,
    WRITING_STYLES,
    Chapter,
    LoreEntry,
    Project,
    content_hash,
    count_words,
    portable_model_path,
    resolve_model_path,
    save_json_text,
)
from .prompts import (
    REWRITE_MODE_LABELS,
    OutlineParseError,
    build_lore_scan_text,
    build_previous_context,
    match_lore_entries,
)
from .repetition import reduce_repetition, repetition_report
from .sampling import (
    PRESET_CHOICES,
    PRESET_CUSTOM,
    PROSE_PRESETS,
    SamplingConfig,
    SamplingSettings,
    parse_seed,
)
from .settings import (
    get_chat_format_for_model,
    get_last_model,
    get_model_settings,
    get_ui_preferences,
    set_chat_format_for_model,
    set_model_settings,
    set_ui_preferences,
)
from .strings_es import (
    CHAPTER_HEADING_LABELS,
    CHAPTER_PURPOSE_DEFAULT_LABEL,
    PURPOSE_OPTIONS,
    STYLE_OPTIONS,
    WRITING_STYLE_DEFAULT_LABEL,
    history_source_label,
    purpose_key,
    purpose_label,
    style_key,
    style_label,
)
from .task_runner import EngineTaskRunner, call_supported
from .ui_dialogs import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_WARN,
    DiffPreviewDialog,
    PreferencesDialog,
    ProjectSearchDialog,
    SearchHit,
    TextViewerDialog,
    replace_in_text,
)
from .ui_status import StatusBar

APP_TITLE = "StoryForge Local"
# Ver app/paths.py: en el .exe, "dos carpetas arriba de __file__" seria
# _internal\, no la carpeta de StoryForge.exe donde el usuario pone models\.
APP_ROOT = app_root()
MODELS_DIR = os.path.join(APP_ROOT, "models")
WRITING_STYLE_OPTIONS = STYLE_OPTIONS
CHAPTER_PURPOSE_OPTIONS = PURPOSE_OPTIONS
NO_MODELS_LABEL = "(sin modelos en models/)"

# Copia de autoguardado, separada del guardado explicito del usuario. Vive en
# user_data_dir() (%APPDATA%\StoryForge en el .exe) y se resuelve al crear la
# ventana (StoryForgeApp.autosave_path): asi STORYFORGE_USER_DATA_DIR
# redirige el autoguardado -- las pruebas lo usan para no tocar nunca el
# autoguardado real del usuario.


def log_location() -> str:
    """Donde quedan los errores registrados (ver app/main.py)."""
    if is_frozen():
        return log_file_path()
    return "la consola desde la que se inició la app"


def default_autosave_path() -> str:
    return os.path.join(user_data_dir(), "autosave", "autosave.json")


# Cada cuanto se revisa si hay que autoguardar: siempre mientras el modelo
# trabaja, y cada AUTOSAVE_IDLE_SECONDS si hay cambios sin guardar (F10:
# antes solo se autoguardaba durante una generacion).
AUTOSAVE_INTERVAL_MS = 20_000
AUTOSAVE_IDLE_SECONDS = 60
# Intervalo minimo entre refrescos de pantalla durante el streaming token a
# token (la actualizacion final nunca pasa por este throttle).
CHAPTER_STREAM_UI_INTERVAL_SECONDS = 0.15
# Espera tras la ultima tecla antes de filtrar el Lorebook (F11) o
# recalcular "cambios sin guardar" (F10).
LORE_FILTER_DEBOUNCE_MS = 250
DIRTY_CHECK_DEBOUNCE_MS = 500

logger = logging.getLogger(__name__)

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
        self.counter_label = ctk.CTkLabel(header, text=f"0 / {max_words:,} palabras")
        self.counter_label.grid(row=0, column=1, sticky="e")

        text_row = 1
        if on_expand or on_import:
            btn_bar = ctk.CTkFrame(self, fg_color="transparent")
            btn_bar.grid(row=1, column=0, sticky="w", padx=4, pady=(2, 0))
            if on_import:
                self.import_btn = ctk.CTkButton(
                    btn_bar, text="Importar desde archivo...", width=170, command=on_import
                )
                self.import_btn.pack(side="left", padx=(0, 6))
            if on_expand:
                self.expand_btn = ctk.CTkButton(btn_bar, text="Expandir con IA", width=140, command=on_expand)
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
        self.counter_label.configure(text=f"{words:,} / {self.max_words:,} palabras", text_color=color)

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


class ChapterPanel(ctk.CTkFrame):
    """Un capitulo: metadatos, barra de acciones, editor, buscar/reemplazar,
    refinamiento y resumen. Se muestra uno a la vez (ver _jump_to_chapter)."""

    def __init__(self, master, app: "StoryForgeApp", index: int, chapter: Chapter, **kwargs):
        super().__init__(master, border_width=1, corner_radius=8, **kwargs)
        self.app = app
        self.index = index
        self.chapter = chapter
        self._cancel_flag: Optional[dict] = None
        self.is_generating = False
        # "Reintentar": la ultima ejecucion de Generar/Continuar se puede
        # repetir (otra semilla) y recorrer sus alternativas con < >.
        self._last_run: Optional[dict] = None
        self.alternatives: List[str] = []
        self.alt_index = -1
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=f"Capítulo {index + 1}", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )
        self.title_entry = ctk.CTkEntry(self, placeholder_text="Título del capítulo")
        self.title_entry.insert(0, chapter.title)
        self.title_entry.grid(row=0, column=1, padx=8, pady=(8, 2), sticky="ew")
        ctk.CTkLabel(self, text="Palabras objetivo:").grid(row=0, column=2, padx=(8, 2), sticky="e")
        self.target_entry = ctk.CTkEntry(self, width=80)
        self.target_entry.insert(0, str(chapter.target_words))
        self.target_entry.grid(row=0, column=3, padx=(0, 8), sticky="e")

        # Proposito narrativo + Nota del autor (F7) de este capitulo.
        purpose_row = ctk.CTkFrame(self, fg_color="transparent")
        purpose_row.grid(row=1, column=0, columnspan=4, sticky="ew", padx=8, pady=(2, 0))
        purpose_row.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(purpose_row, text="Propósito:").grid(row=0, column=0, padx=(0, 6))
        self.purpose_menu = ctk.CTkOptionMenu(purpose_row, values=CHAPTER_PURPOSE_OPTIONS, width=170)
        self.purpose_menu.set(purpose_label(chapter.purpose if chapter.purpose in CHAPTER_PURPOSES else ""))
        self.purpose_menu.grid(row=0, column=1)
        ctk.CTkLabel(purpose_row, text="Nota del autor:").grid(row=0, column=2, padx=(14, 6))
        self.author_note_entry = ctk.CTkEntry(
            purpose_row,
            placeholder_text="Instrucción corta que el modelo lee justo antes de escribir (p.ej. \"Elena oculta que está herida\")",
        )
        self.author_note_entry.insert(0, chapter.author_note)
        self.author_note_entry.grid(row=0, column=3, sticky="ew")

        # Barra de acciones compacta: las acciones principales a la vista y
        # las demas en "Más herramientas" (se despliega debajo).
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=8)
        self.generate_btn = ctk.CTkButton(btn_frame, text="Generar", width=80, command=self._on_generate)
        self.generate_btn.pack(side="left", padx=(0, 4), pady=4)
        self.continue_btn = ctk.CTkButton(btn_frame, text="Continuar", width=80, command=self._on_continue)
        self.continue_btn.pack(side="left", padx=4, pady=4)
        self.continue_cursor_btn = ctk.CTkButton(
            btn_frame, text="Desde el cursor", width=110,
            command=lambda: self._on_continue(from_cursor=True),
        )
        self.continue_cursor_btn.pack(side="left", padx=4, pady=4)
        self.retry_btn = ctk.CTkButton(btn_frame, text="Reintentar", width=85, state="disabled", command=self._on_retry)
        self.retry_btn.pack(side="left", padx=4, pady=4)
        self.prev_alt_btn = ctk.CTkButton(btn_frame, text="<", width=28, state="disabled",
                                          command=lambda: self._cycle_alternative(-1))
        self.prev_alt_btn.pack(side="left", padx=(4, 0), pady=4)
        self.alt_label = ctk.CTkLabel(btn_frame, text="", width=40)
        self.alt_label.pack(side="left")
        self.next_alt_btn = ctk.CTkButton(btn_frame, text=">", width=28, state="disabled",
                                          command=lambda: self._cycle_alternative(1))
        self.next_alt_btn.pack(side="left", padx=(0, 4), pady=4)
        self.cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancelar", width=80, state="disabled",
            fg_color="#8a6a2f", hover_color="#6e5526", command=self._on_cancel,
        )
        self.cancel_btn.pack(side="left", padx=4, pady=4)
        self.history_btn = ctk.CTkButton(btn_frame, text="Versiones anteriores (0)", width=170, command=self._on_show_history)
        self.history_btn.pack(side="left", padx=4, pady=4)
        self.more_btn = ctk.CTkButton(btn_frame, text="Más herramientas ▾", width=140, command=self._toggle_tools)
        self.more_btn.pack(side="left", padx=4, pady=4)

        self.tools_row = ctk.CTkFrame(self, fg_color="transparent")
        self.reduce_btn = ctk.CTkButton(self.tools_row, text="Reducir repetición", width=140, command=self._on_reduce)
        self.reduce_btn.pack(side="left", padx=(0, 6), pady=2)
        self.report_btn = ctk.CTkButton(self.tools_row, text="Reporte de repetición", width=150, command=self._on_report)
        self.report_btn.pack(side="left", padx=6, pady=2)
        self.find_btn = ctk.CTkButton(self.tools_row, text="Buscar y reemplazar (Ctrl+F)", width=190, command=self.show_find_bar)
        self.find_btn.pack(side="left", padx=6, pady=2)
        self.remove_btn = ctk.CTkButton(
            self.tools_row, text="Eliminar capítulo", width=130, fg_color="#8a3b3b",
            hover_color="#6e2f2f", command=self._on_remove,
        )
        self.remove_btn.pack(side="right", padx=(6, 0), pady=2)
        self.tools_visible = False

        # Buscar / reemplazar en este capitulo (F5), oculto hasta Ctrl+F.
        self.find_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.find_bar.grid_columnconfigure((1, 3), weight=1)
        ctk.CTkLabel(self.find_bar, text="Buscar:").grid(row=0, column=0, padx=(0, 4))
        self.find_entry = ctk.CTkEntry(self.find_bar)
        self.find_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(self.find_bar, text="Reemplazar:").grid(row=0, column=2, padx=(8, 4))
        self.replace_entry = ctk.CTkEntry(self.find_bar)
        self.replace_entry.grid(row=0, column=3, sticky="ew")
        for col, (text, cmd) in enumerate((
            ("<", lambda: self.find_next(backwards=True)), (">", self.find_next),
            ("Reemplazar", self.replace_current), ("Reemplazar todo", self.replace_all),
            ("Cerrar", self.hide_find_bar),
        ), start=4):
            ctk.CTkButton(self.find_bar, text=text, width=28 if len(text) == 1 else 90, command=cmd).grid(row=0, column=col, padx=2)
        self.find_count_label = ctk.CTkLabel(self.find_bar, text="", text_color=COLOR_MUTED)
        self.find_count_label.grid(row=0, column=9, padx=6)
        self.find_entry.bind("<Return>", lambda _e: (self.find_next(), "break")[1])
        self.find_entry.bind("<KeyRelease>", lambda e: None if e.keysym == "Return" else self.highlight_matches())
        self.find_entry.bind("<Escape>", lambda _e: (self.hide_find_bar(), "break")[1])
        self.find_visible = False

        self.status_label = ctk.CTkLabel(self, text="", text_color=COLOR_MUTED)
        self.status_label.grid(row=5, column=0, columnspan=4, sticky="w", padx=8)

        self.content_box = ctk.CTkTextbox(self, height=220, wrap="word", border_width=2, **UNDO_TEXTBOX_OPTIONS)
        self._idle_border_color = self.content_box.cget("border_color")
        self.content_box.grid(row=6, column=0, columnspan=4, sticky="nsew", padx=8, pady=(4, 8))
        self.content_box.insert("1.0", chapter.content)
        self.content_box.edit_reset()
        self.content_box.tag_config("find_match", background="#c9a227", foreground="black")
        self.content_box.tag_config("find_current", background="#e07b00", foreground="black")
        self.grid_rowconfigure(6, weight=1)
        app.apply_editor_preferences(self.content_box)

        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.grid(row=7, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 4))
        self.word_count_label = ctk.CTkLabel(info_row, text="")
        self.word_count_label.pack(side="left")
        self.summary_status_label = ctk.CTkLabel(info_row, text="")
        self.summary_status_label.pack(side="left", padx=(16, 0))
        self.content_box.bind("<KeyRelease>", lambda e: self._on_content_edited())
        # Ctrl+Enter: Generar (capitulo vacio) o Continuar (ya tiene texto).
        self.content_box.bind("<Control-Return>", self._on_ctrl_enter)
        # Clic derecho: reescribir / expandir / describir / acortar la seleccion (F7).
        self.content_box.bind("<Button-3>", self._show_context_menu)

        # Refinamiento: reescribe el capitulo segun una instruccion, con
        # vista previa de diferencias antes de aplicar (F4).
        self.refine_row = ctk.CTkFrame(self, fg_color="transparent")
        self.refine_row.grid(row=8, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 8))
        self.refine_row.grid_columnconfigure(0, weight=1)
        self.refine_entry = ctk.CTkEntry(
            self.refine_row,
            placeholder_text="Instrucción de refinamiento (ej: hazlo más oscuro, acorta el diálogo del final)",
        )
        self.refine_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.refine_btn = ctk.CTkButton(self.refine_row, text="Aplicar refinamiento", width=160, command=self._on_refine)
        self.refine_btn.grid(row=0, column=1)

        # Resumen: la "memoria" que recibe el capitulo siguiente.
        self.summary_header = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_header.grid(row=9, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 4))
        self.summary_toggle_btn = ctk.CTkButton(
            self.summary_header, text="Mostrar resumen", width=140, command=self._toggle_summary,
        )
        self.summary_toggle_btn.pack(side="left")
        self.regen_summary_btn = ctk.CTkButton(
            self.summary_header, text="Regenerar resumen", width=150, command=self._on_regenerate_summary,
        )
        self.regen_summary_btn.pack(side="left", padx=6)
        self.summary_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_frame.grid_columnconfigure(0, weight=1)
        self.summary_box = ctk.CTkTextbox(self.summary_frame, height=90, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.summary_box.grid(row=0, column=0, sticky="ew")
        self.summary_box.insert("1.0", chapter.summary)
        self.summary_box.edit_reset()
        self.summary_box.bind("<KeyRelease>", lambda e: self._refresh_summary_status())
        self.summary_visible = False

        self._refresh_word_count()
        self._refresh_summary_status()
        self._refresh_history_btn()

    # ---- sincronizacion con el modelo de datos ----
    def sync_to_model(self) -> None:
        self.chapter.title = self.title_entry.get().strip() or f"Capítulo {self.index + 1}"
        try:
            target = int(self.target_entry.get())
        except ValueError:
            target = self.chapter.target_words
        self.chapter.target_words = max(1, min(target, MAX_WORDS_PER_CHAPTER))
        self.chapter.content = self.content_box.get("1.0", "end-1c")
        self.chapter.purpose = purpose_key(self.purpose_menu.get())
        self.chapter.author_note = self.author_note_entry.get().strip()
        # Un resumen editado a mano se considera al dia con el texto actual.
        summary_text = self.summary_box.get("1.0", "end-1c")
        if summary_text.strip() != self.chapter.summary.strip():
            self.chapter.set_summary(summary_text)

    def push_history(self, source: str) -> None:
        self.app.project.push_chapter_history(self.chapter, source)
        self._refresh_history_btn()

    def _show_summary_text(self, text: str) -> None:
        _set_text_readonly_content(self.summary_box, text or "")
        self.summary_box.edit_reset()
        self._refresh_summary_status()

    def _toggle_summary(self) -> None:
        self.summary_visible = not self.summary_visible
        if self.summary_visible:
            self.summary_frame.grid(row=10, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 8))
            self.summary_toggle_btn.configure(text="Ocultar resumen")
        else:
            self.summary_frame.grid_remove()
            self.summary_toggle_btn.configure(text="Mostrar resumen")

    def _toggle_tools(self) -> None:
        self.tools_visible = not self.tools_visible
        if self.tools_visible:
            self.tools_row.grid(row=3, column=0, columnspan=4, sticky="ew", padx=8)
            self.more_btn.configure(text="Menos herramientas ▴")
        else:
            self.tools_row.grid_remove()
            self.more_btn.configure(text="Más herramientas ▾")

    def set_focus_mode(self, focus: bool) -> None:
        """Modo enfoque: oculta refinamiento y resumen (queda el editor)."""
        if focus:
            self.refine_row.grid_remove()
            self.summary_header.grid_remove()
            self.summary_frame.grid_remove()
        else:
            self.refine_row.grid()
            self.summary_header.grid()
            if self.summary_visible:
                self.summary_frame.grid()

    def summary_state(self) -> str:
        """"ok", "stale" (el texto cambio desde el resumen), "missing" (hay
        texto pero no resumen) o "empty" (capitulo sin texto), segun lo que
        hay AHORA en pantalla."""
        content = self.content_box.get("1.0", "end-1c")
        summary = self.summary_box.get("1.0", "end-1c")
        if not content.strip():
            return "empty"
        if not summary.strip():
            return "missing"
        if summary.strip() != self.chapter.summary.strip():
            return "ok"  # editado a mano: se guarda como al dia (ver sync_to_model)
        return "stale" if self.chapter.summary_source_hash != content_hash(content) else "ok"

    def _refresh_summary_status(self) -> None:
        state = self.summary_state()
        text, color = {
            "ok": ("Resumen al día", COLOR_MUTED),
            "stale": ("Resumen desactualizado", COLOR_WARN),
            "missing": ("Sin resumen", COLOR_WARN),
            "empty": ("", COLOR_MUTED),
        }[state]
        self.summary_status_label.configure(text=text, text_color=color)

    def _on_content_edited(self) -> None:
        self._refresh_word_count()
        self._refresh_summary_status()
        if self.alternatives and self.content_box.get("1.0", "end-1c") != self.alternatives[self.alt_index]:
            self._clear_alternatives()  # una edicion a mano descarta las alternativas
        if self.find_visible:
            self.highlight_matches()

    def _refresh_history_btn(self) -> None:
        self.history_btn.configure(text=f"Versiones anteriores ({len(self.chapter.history)})")

    def _refresh_word_count(self) -> None:
        words = count_words(self.content_box.get("1.0", "end-1c"))
        over = words > MAX_WORDS_PER_CHAPTER
        self.word_count_label.configure(
            text=f"{words:,} / {MAX_WORDS_PER_CHAPTER:,} palabras (objetivo {self.chapter.target_words:,})",
            text_color=COLOR_ERROR if over else COLOR_MUTED,
        )

    def _set_busy(self, busy: bool, status: str = "") -> None:
        state = "disabled" if busy else "normal"
        for btn in (self.generate_btn, self.continue_btn, self.continue_cursor_btn, self.regen_summary_btn,
                    self.reduce_btn, self.remove_btn, self.refine_btn, self.history_btn):
            btn.configure(state=state)
        self._refresh_retry_controls(busy)
        self.cancel_btn.configure(state=("normal" if busy else "disabled"))
        self.status_label.configure(text=status)

    def _set_generating(self, generating: bool) -> None:
        """
        Mientras el modelo escribe en ESTE capitulo (generar, continuar o
        refinar), el cuadro de texto y los campos que usa el prompt quedan en
        solo lectura: antes lo que el usuario tecleaba ahi se perdia sin aviso
        cuando el texto final reemplazaba el cuadro completo.
        """
        self.is_generating = generating
        state = "disabled" if generating else "normal"
        self.content_box.configure(state=state)
        self.content_box.configure(
            border_color=GENERATING_BORDER_COLOR if generating else self._idle_border_color
        )
        for widget in (self.title_entry, self.target_entry, self.purpose_menu, self.summary_box,
                       self.author_note_entry):
            widget.configure(state=state)

    def _on_cancel(self) -> None:
        if self._cancel_flag is not None:
            self._cancel_flag["cancel"] = True
            self.cancel_btn.configure(state="disabled")
            self.status_label.configure(text="Cancelando... se detendrá en breve.")
        self.app.task_runner.request_stop()

    def _on_ctrl_enter(self, _event=None):
        if self.app.busy:
            return "break"
        if self.content_box.get("1.0", "end-1c").strip():
            self._on_continue()
        else:
            self._on_generate()
        return "break"

    def _can_start_engine_task(self) -> bool:
        if not self.app.engine.is_loaded:
            messagebox.showwarning(APP_TITLE, "Primero carga un modelo local (.gguf) en la pestaña 'Modelo'.")
            return False
        if self.app.busy:
            messagebox.showwarning(
                APP_TITLE,
                "Ya hay una generación en curso (otro capítulo, el esquema, o cargando un "
                "modelo). Espera a que termine antes de iniciar otra.",
            )
            return False
        return True

    def _stale_previous_summaries(self) -> list[int]:
        """Indices de capitulos anteriores con texto cuyo resumen falta o
        quedo desactualizado."""
        return [i for i in range(self.index) if self.app.project.chapters[i].needs_summary()]

    def _ask_regenerate_summaries(self) -> list[int]:
        stale = self._stale_previous_summaries()
        if not stale:
            return []
        numbers = ", ".join(str(i + 1) for i in stale)
        if messagebox.askyesno(
            APP_TITLE,
            f"El resumen de los capítulos {numbers} falta o está desactualizado (el texto "
            "cambió después de resumirlo). Esos resúmenes son la memoria que recibe este "
            "capítulo.\n\n¿Regenerarlos antes de generar? (No = generar igual, con los "
            "resúmenes actuales)",
        ):
            return stale
        return []

    def _validate_before_generation(self) -> bool:
        self.app._sync_all()
        errors = self.app.project.validate_inputs()
        if errors:
            messagebox.showwarning(APP_TITLE, "Corrige antes de generar:\n\n" + "\n".join(errors))
            return False
        return True

    def _on_generate(self) -> None:
        if not self._can_start_engine_task():
            return
        # Sincronizamos TODO (plot/personajes/setting/esquema/capitulos): la
        # generacion depende de esos datos.
        if not self._validate_before_generation():
            return
        if self.chapter.content.strip() and not messagebox.askyesno(
            APP_TITLE,
            f"El capítulo {self.index + 1} ya tiene texto generado. Generar de nuevo "
            "reemplazará ese contenido (la versión actual se guarda en "
            "\"Versiones anteriores\", así que es recuperable). Para seguir escribiendo "
            "sin borrar nada usa \"Continuar\". ¿Regenerar desde cero?",
        ):
            return
        self._start_generation(resume_from=None, regenerate=self._ask_regenerate_summaries())

    def _on_continue(self, from_cursor: bool = False) -> None:
        """Sigue escribiendo el capitulo desde el final del texto actual (o
        desde el cursor, descartando lo que haya despues) en vez de empezar
        de cero -- lo que tambien hace que Cancelar ya no sea destructivo."""
        if not self._can_start_engine_task():
            return
        if not self._validate_before_generation():
            return
        text = self.chapter.content
        if from_cursor:
            before = self.content_box.get("1.0", "insert")
            after = self.content_box.get("insert", "end-1c")
            if after.strip() and not messagebox.askyesno(
                APP_TITLE,
                f"Se continuará desde el cursor: las {count_words(after):,} palabras que hay "
                "después del cursor se reemplazarán por texto nuevo (la versión actual se "
                "guarda en \"Versiones anteriores\"). ¿Continuar?",
            ):
                return
            text = before
        if not text.strip():
            self._on_generate()
            return
        self._start_generation(resume_from=text, regenerate=self._ask_regenerate_summaries())

    # ---- Reintentar / alternativas (F4) ----
    def _on_retry(self) -> None:
        """Repite la ultima ejecucion de Generar/Continuar desde el mismo punto
        de partida (con otra semilla, salvo que el proyecto fije una) y
        agrega el resultado como una alternativa mas."""
        if self._last_run is None or not self._can_start_engine_task():
            return
        if not self._validate_before_generation():
            return
        if self.content_box.get("1.0", "end-1c") not in self.alternatives:
            self.alternatives = []  # el texto cambio desde la ultima ejecucion
        self._start_generation(resume_from=self._last_run["resume_from"], regenerate=[], retry=True)

    def _cycle_alternative(self, step: int) -> None:
        if not self.alternatives or self.app.busy:
            return
        current = self.content_box.get("1.0", "end-1c")
        if current != self.alternatives[self.alt_index]:
            self._clear_alternatives()
            return
        self.alt_index = (self.alt_index + step) % len(self.alternatives)
        text = self.alternatives[self.alt_index]
        self.content_box.delete("1.0", "end")
        self.content_box.insert("1.0", text)
        self.content_box.edit_reset()
        self.chapter.content = text
        self._refresh_word_count()
        self._refresh_summary_status()
        self._refresh_retry_controls(False)

    def _clear_alternatives(self) -> None:
        self.alternatives = []
        self.alt_index = -1
        self._refresh_retry_controls(self.app.busy)

    def _refresh_retry_controls(self, busy: bool) -> None:
        self.retry_btn.configure(state="disabled" if busy or self._last_run is None else "normal")
        many = len(self.alternatives) > 1 and not busy
        self.prev_alt_btn.configure(state="normal" if many else "disabled")
        self.next_alt_btn.configure(state="normal" if many else "disabled")
        self.alt_label.configure(
            text=f"{self.alt_index + 1}/{len(self.alternatives)}" if len(self.alternatives) > 1 else ""
        )

    def _start_generation(self, resume_from: Optional[str], regenerate: list[int], retry: bool = False) -> None:
        if retry:
            source = "retry"
        else:
            source = "continue" if resume_from else "generate"
        self.push_history(source)
        mode = "Continuando" if resume_from else "Generando"
        self._set_busy(True, f"{mode}... esto puede tardar varios minutos en CPU.")
        # El cuadro se prepara una sola vez aqui, en el hilo principal: vacio
        # al generar, o con el texto desde el que se continua. De ahi en
        # adelante progress() solo AGREGA texto al final, hasta el
        # redibujado final garantizado (show_final).
        base_text = (resume_from or "").rstrip()
        if resume_from is None:
            self.content_box.delete("1.0", "end")
        else:
            _set_text_readonly_content(self.content_box, base_text)
        self._set_generating(True)
        cancel_flag = {"cancel": False}
        self._cancel_flag = cancel_flag
        stream_state = {"last_update": 0.0, "shown_text": base_text}
        project = self.app.project
        engine = self.app.engine
        app = self.app
        previous_alternatives = list(self.alternatives) if retry else []

        def progress(text: str, words: int, target: int) -> None:
            now = time.monotonic()
            if now - stream_state["last_update"] < CHAPTER_STREAM_UI_INTERVAL_SECONDS:
                return  # descartada a proposito; el redibujado final no pasa por aqui
            stream_state["last_update"] = now

            def apply():
                shown_text = stream_state["shown_text"]
                if text.startswith(shown_text):
                    delta = text[len(shown_text):]
                    if delta:
                        _append_text(self.content_box, delta)
                else:
                    _set_text_readonly_content(self.content_box, text)
                stream_state["shown_text"] = text
                self.content_box.see("end")
                self._refresh_word_count()
                self.status_label.configure(text=f"{mode}... {words:,} / {target:,} palabras")
            app.after(0, apply)

        def set_status(text: str) -> None:
            app.after(0, lambda: self.status_label.configure(text=text))

        def cancelled() -> bool:
            return cancel_flag["cancel"] or app.task_runner.cancel_requested

        def work(_cancel_check):
            final_status = "Listo."
            # Primero, los resumenes desactualizados que el usuario pidio
            # regenerar: son el contexto de este capitulo.
            for i in regenerate:
                if cancelled():
                    break
                ch = project.chapters[i]
                set_status(f"Regenerando el resumen del capítulo {i + 1}...")
                source_text = ch.content
                try:
                    summary = call_supported(engine.summarize, source_text, cancel_check=cancelled)
                except OperationCancelled:
                    break
                ch.set_summary(summary, source_text=source_text)
                app.after(0, app._refresh_summary_views)
            kwargs = dict(progress_callback=progress, cancel_check=cancelled)
            if resume_from is not None:
                kwargs["resume_from"] = base_text
            result = engine.generate_chapter(project, self.index, **kwargs)
            if not result.strip() and base_text:
                result = base_text
            self.chapter.content = result
            summary_text: Optional[str] = None
            if result.strip() and not cancelled():
                set_status("Generando resumen para continuidad entre capítulos...")
                try:
                    summary_text = call_supported(engine.summarize, result, cancel_check=cancelled)
                    self.chapter.set_summary(summary_text, source_text=result)
                except OperationCancelled:
                    final_status = "Cancelado antes del resumen. Usa \"Regenerar resumen\"."
                except Exception:  # noqa: BLE001
                    # El capitulo no se pierde; el resumen queda marcado
                    # como faltante/desactualizado y se puede regenerar.
                    logger.exception("No se pudo generar el resumen del capítulo %d", self.index + 1)
                    final_status = (
                        "Listo, pero no se pudo generar el resumen (ver el registro). "
                        "Usa \"Regenerar resumen\"."
                    )
            elif cancelled():
                final_status = "Cancelado. Puedes seguir con \"Continuar\"."
            return result, summary_text, final_status

        def on_success(outcome) -> None:
            result, summary_text, final_status = outcome
            _set_text_readonly_content(self.content_box, result)
            # Ctrl+Z no debe deshacer la generacion fragmento a fragmento
            # (la version anterior esta en "Versiones").
            self.content_box.edit_reset()
            self.content_box.see("end")
            if summary_text is not None:
                self._show_summary_text(self.chapter.summary)
            self._last_run = {"resume_from": resume_from}
            self.alternatives = previous_alternatives + [result]
            self.alt_index = len(self.alternatives) - 1
            if result.strip() and not cancelled():
                app._record_lore_matches(self.index)
            seed = getattr(engine, "last_seed", None)
            if seed is not None and final_status == "Listo.":
                final_status = f"Listo (semilla {seed})."
            self._done_status = final_status

        self._done_status = ""

        def on_finally() -> None:
            self._cancel_flag = None
            self._set_generating(False)
            self._set_busy(False, self._done_status)
            self._refresh_word_count()
            self._refresh_summary_status()
            app._refresh_word_totals()

        app.task_runner.run(
            f"Capítulo {self.index + 1}", work, on_success=on_success, on_finally=on_finally,
            error_prefix="Error generando capítulo: ",
        )

    def _on_regenerate_summary(self) -> None:
        if not self._can_start_engine_task():
            return
        self.sync_to_model()
        content = self.chapter.content
        if not content.strip():
            messagebox.showwarning(APP_TITLE, "Este capítulo todavía no tiene texto para resumir.")
            return
        self._set_busy(True, "Generando resumen...")
        engine = self.app.engine
        status = {"text": ""}

        def work(cancel_check):
            return call_supported(engine.summarize, content, cancel_check=cancel_check)

        def on_success(summary) -> None:
            self.chapter.set_summary(summary, source_text=content)
            self._show_summary_text(self.chapter.summary)
            status["text"] = "Resumen actualizado."

        def on_cancel() -> None:
            status["text"] = "Resumen cancelado."

        def on_error(exc) -> Optional[str]:
            logger.exception("No se pudo regenerar el resumen del capítulo %d", self.index + 1, exc_info=exc)
            return f"No se pudo generar el resumen: {exc}"

        self.app.task_runner.run(
            "Resumen", work, on_success=on_success, on_cancel=on_cancel, on_error=on_error,
            on_finally=lambda: self._set_busy(False, status["text"]),
        )

    def _on_reduce(self) -> None:
        self.sync_to_model()
        if not self.chapter.content.strip():
            return
        self.push_history("reduce")
        reduced = reduce_repetition(self.chapter.content)
        self.content_box.edit_separator()
        self.content_box.delete("1.0", "end")
        self.content_box.insert("1.0", reduced)
        self.content_box.edit_separator()
        self.chapter.content = reduced
        self._on_content_edited()

    def _on_report(self) -> None:
        self.sync_to_model()
        report = repetition_report(self.chapter.content)
        messagebox.showinfo(f"Repetición - Capítulo {self.index + 1}", report)

    def _on_remove(self) -> None:
        if messagebox.askyesno(APP_TITLE, f"¿Eliminar el capítulo {self.index + 1}?"):
            self.app.remove_chapter(self.index)

    # ---- refinamiento con vista previa (F4) ----
    def _on_refine(self) -> None:
        if not self._can_start_engine_task():
            return
        self.sync_to_model()
        if not self.chapter.content.strip():
            messagebox.showwarning(
                APP_TITLE, "Este capítulo todavía no tiene contenido para refinar. Genéralo primero."
            )
            return
        instruction = self.refine_entry.get().strip()
        if not instruction:
            messagebox.showwarning(
                APP_TITLE, "Escribe una instrucción de refinamiento (por ejemplo: \"hazlo más oscuro\")."
            )
            return
        original = self.chapter.content
        self._set_busy(True, "Refinando capítulo... (verás una vista previa antes de aplicar nada)")
        self._set_generating(True)
        engine = self.app.engine
        project = self.app.project

        def progress(part: int, total: int) -> None:
            if total > 1:
                self.app.after(0, lambda: self.status_label.configure(
                    text=f"Refinando la parte {part} de {total}..."))

        def work(cancel_check):
            return call_supported(
                engine.refine_chapter, project, self.index, instruction,
                cancel_check=cancel_check, progress_callback=progress,
            )

        status = {"text": ""}

        def on_success(revised: str) -> None:
            status["text"] = "Revisa la vista previa: Aceptar aplica el cambio."
            self.app.show_diff_preview(
                f"Refinar capítulo {self.index + 1}: {instruction}", original, revised,
                on_accept=lambda text: self._apply_revision(text, f"refine: {instruction}"),
                on_accept_continue=lambda text: self._apply_revision(
                    text, f"refine: {instruction}", keep_refining=True),
                on_discard=lambda: self.status_label.configure(text="Refinamiento descartado."),
            )

        def on_cancel() -> None:
            status["text"] = "Refinamiento cancelado: el capítulo no cambió."

        def on_finally() -> None:
            self._set_generating(False)
            self._set_busy(False, status["text"])

        self.app.task_runner.run(
            f"Refinar capítulo {self.index + 1}", work, on_success=on_success, on_cancel=on_cancel,
            on_finally=on_finally, error_prefix="Error refinando el capítulo: ",
        )

    def _apply_revision(self, text: str, source: str, keep_refining: bool = False) -> None:
        self.sync_to_model()
        self.push_history(source)
        self.chapter.content = text
        _set_text_readonly_content(self.content_box, text)
        self.content_box.edit_reset()
        self._on_content_edited()
        self.status_label.configure(text="Cambio aplicado (la versión anterior está en \"Versiones anteriores\").")
        self.app.schedule_dirty_check()
        if keep_refining:
            self.refine_entry.delete(0, "end")
            self.refine_entry.focus_set()

    # ---- acciones sobre la seleccion (F7) ----
    def _show_context_menu(self, event) -> str:
        menu = tk.Menu(self, tearoff=0)
        has_selection = bool(self._selection_range())
        state = "normal" if has_selection and not self.app.busy and not self.is_generating else "disabled"
        for mode, label in REWRITE_MODE_LABELS.items():
            menu.add_command(label=f"{label} selección", state=state,
                             command=lambda m=mode: self.rewrite_selection(m))
        menu.add_command(label="Reescribir selección con instrucción...", state=state,
                         command=lambda: self.rewrite_selection("rewrite", ask_instruction=True))
        menu.add_separator()
        menu.add_command(label="Buscar y reemplazar (Ctrl+F)", command=self.show_find_bar)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _selection_range(self):
        try:
            return self.content_box.index("sel.first"), self.content_box.index("sel.last")
        except tk.TclError:
            return None

    def rewrite_selection(self, mode: str, instruction: str = "", ask_instruction: bool = False) -> None:
        """Reescribe solo el texto seleccionado (con ~300 palabras de contexto
        a cada lado) y muestra una vista previa antes de reemplazarlo."""
        rng = self._selection_range()
        if not rng:
            messagebox.showinfo(APP_TITLE, "Selecciona primero el fragmento del capítulo a reescribir.")
            return
        if not self._can_start_engine_task():
            return
        if ask_instruction:
            dialog = ctk.CTkInputDialog(text="Instrucción para este fragmento:", title="Reescribir selección")
            instruction = (dialog.get_input() or "").strip()
            if not instruction:
                return
        self.app._sync_all()
        start, end = rng
        before = self.content_box.get("1.0", start)
        selection = self.content_box.get(start, end)
        after = self.content_box.get(end, "end-1c")
        engine = self.app.engine
        project = self.app.project
        self._set_busy(True, f"{REWRITE_MODE_LABELS.get(mode, mode)}: trabajando sobre la selección...")
        self._set_generating(True)

        def work(cancel_check):
            return call_supported(
                engine.rewrite_span, project, self.index, before, selection, after,
                mode=mode, instruction=instruction, cancel_check=cancel_check,
            )

        def on_success(new_passage: str) -> None:
            new_full = before + new_passage.strip() + after
            label = REWRITE_MODE_LABELS.get(mode, mode)
            self.app.show_diff_preview(
                f"{label} selección - Capítulo {self.index + 1}", selection, new_passage.strip(),
                on_accept=lambda _t: self._apply_revision(new_full, f"rewrite: {label.lower()}"),
            )

        self.app.task_runner.run(
            "Reescribir selección", work, on_success=on_success,
            on_finally=lambda: (self._set_generating(False), self._set_busy(False, "")),
            error_prefix="Error reescribiendo la selección: ",
        )

    # ---- buscar / reemplazar en el capitulo (F5) ----
    def show_find_bar(self) -> None:
        if not self.find_visible:
            self.find_bar.grid(row=4, column=0, columnspan=4, sticky="ew", padx=8, pady=(2, 2))
            self.find_visible = True
        rng = self._selection_range()
        if rng:
            selected = self.content_box.get(*rng)
            if selected and "\n" not in selected:
                self.find_entry.delete(0, "end")
                self.find_entry.insert(0, selected)
        self.find_entry.focus_set()
        self.highlight_matches()

    def hide_find_bar(self) -> None:
        self.find_bar.grid_remove()
        self.find_visible = False
        self.content_box.tag_remove("find_match", "1.0", "end")
        self.content_box.tag_remove("find_current", "1.0", "end")
        self.content_box.focus_set()

    def _match_positions(self) -> List[tuple]:
        query = self.find_entry.get()
        positions = []
        if not query:
            return positions
        start = "1.0"
        while True:
            count = tk.IntVar()
            pos = self.content_box.search(query, start, stopindex="end", nocase=True, count=count)
            if not pos or count.get() == 0:
                break
            end = f"{pos}+{count.get()}c"
            positions.append((pos, self.content_box.index(end)))
            start = end
        return positions

    def highlight_matches(self) -> int:
        self.content_box.tag_remove("find_match", "1.0", "end")
        positions = self._match_positions()
        for a, b in positions:
            self.content_box.tag_add("find_match", a, b)
        self.find_count_label.configure(text=f"{len(positions)} coincidencias" if self.find_entry.get() else "")
        return len(positions)

    def find_next(self, backwards: bool = False) -> bool:
        positions = self._match_positions()
        self.highlight_matches()
        if not positions:
            return False
        cursor = self.content_box.index("insert")
        compare = self.content_box.compare
        if backwards:
            candidates = [p for p in positions if compare(p[1], "<", cursor)]
            target = candidates[-1] if candidates else positions[-1]
        else:
            candidates = [p for p in positions if compare(p[0], ">=", cursor)]
            target = candidates[0] if candidates else positions[0]
        self.content_box.tag_remove("find_current", "1.0", "end")
        self.content_box.tag_add("find_current", *target)
        self.content_box.tag_remove("sel", "1.0", "end")
        self.content_box.tag_add("sel", *target)
        self.content_box.mark_set("insert", target[1] if not backwards else target[0])
        self.content_box.see(target[0])
        return True

    def replace_current(self) -> bool:
        if self.is_generating:
            return False
        rng = self._selection_range()
        query = self.find_entry.get()
        if rng and query and self.content_box.get(*rng).lower() == query.lower():
            self.sync_to_model()
            self.push_history("replace")
            self.content_box.delete(*rng)
            self.content_box.insert(rng[0], self.replace_entry.get())
            self.sync_to_model()
            self._on_content_edited()
            self.find_next()
            return True
        return self.find_next()

    def replace_all(self) -> int:
        if self.is_generating:
            return 0
        self.sync_to_model()
        new_text, count = replace_in_text(self.chapter.content, self.find_entry.get(), self.replace_entry.get())
        if count:
            self.push_history("replace")
            self.content_box.edit_separator()
            self.content_box.delete("1.0", "end")
            self.content_box.insert("1.0", new_text)
            self.content_box.edit_separator()
            self.chapter.content = new_text
            self._on_content_edited()
            self.app.schedule_dirty_check()
        self.find_count_label.configure(text=f"{count} reemplazos")
        return count

    # ---- versiones anteriores ----
    def _on_show_history(self) -> None:
        if not self.chapter.history:
            messagebox.showinfo(APP_TITLE, "Este capítulo no tiene versiones anteriores guardadas todavía.")
            return
        VersionHistoryDialog(self.app, self)


class VersionHistoryDialog(ctk.CTkToplevel):
    """
    Ventana para ver y restaurar versiones anteriores de un capitulo. Cada
    version muestra de donde viene (generar, refinar con que instruccion,
    reducir repeticion...) y cuando se guardo (F4).
    """

    def __init__(self, master, panel: "ChapterPanel"):
        super().__init__(master)
        self.panel = panel
        self.title(f"Versiones anteriores - Capítulo {panel.index + 1}")
        self.geometry("760x520")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # El menu muestra la version mas reciente primero; chapter.history
        # guarda la mas vieja primero (ver _selected_history_index()).
        entries = panel.chapter.history_entries()
        total = len(entries)
        self._labels = []
        for i, entry in enumerate(entries):
            label = f"Versión {i + 1} de {total} ({count_words(entry['text'])} palabras)"
            at = entry.get("at", "")
            if at:
                label += f" - {at.replace('T', ' ')}"
            self._labels.append(label)
        self._labels.reverse()

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(top, text="Versión:").pack(side="left", padx=(0, 6))
        self.version_menu = ctk.CTkOptionMenu(top, values=self._labels, command=self._on_select, width=360)
        self.version_menu.pack(side="left", padx=(0, 12))
        self.restore_btn = ctk.CTkButton(top, text="Restaurar esta versión", command=self._on_restore)
        self.restore_btn.pack(side="left")
        self.diff_btn = ctk.CTkButton(top, text="Comparar con la actual", command=self._on_compare)
        self.diff_btn.pack(side="left", padx=6)
        self.source_label = ctk.CTkLabel(self, text="", text_color=COLOR_MUTED, anchor="w")
        self.source_label.grid(row=1, column=0, sticky="ew", padx=10)

        self.preview_box = ctk.CTkTextbox(self, wrap="word")
        self.preview_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.preview_box.configure(state="disabled")

        self._on_select(self._labels[0])

    def _selected_history_index(self) -> int:
        display_index = self._labels.index(self.version_menu.get())
        return len(self.panel.chapter.history) - 1 - display_index

    def _on_select(self, _value: str = "") -> None:
        index = self._selected_history_index()
        entry = self.panel.chapter.history_entries()[index]
        self.preview_box.configure(state="normal")
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("1.0", entry["text"])
        self.preview_box.configure(state="disabled")
        source = history_source_label(entry.get("source", ""))
        self.source_label.configure(text=f"Guardada antes de: {source}" if source else "")

    def _on_compare(self) -> None:
        self.panel.sync_to_model()
        text = self.panel.chapter.history[self._selected_history_index()]
        DiffPreviewDialog(
            self, "Versión anterior (izquierda) frente a la actual (derecha)", text,
            self.panel.chapter.content, on_accept=lambda _t: None,
        )

    def _on_restore(self) -> None:
        text = self.panel.chapter.history[self._selected_history_index()]
        if not messagebox.askyesno(
            APP_TITLE,
            "Esto reemplaza el contenido actual del capítulo por esta versión anterior. El "
            "contenido actual también se guarda como versión antes de restaurar, así que esto "
            "es reversible. ¿Continuar?",
        ):
            return
        # Sincronizamos primero lo que hay en pantalla: sin esto se guardaba
        # como "version anterior" un texto viejo y se perdian las ediciones a
        # mano hechas desde el ultimo generar/guardar.
        self.panel.sync_to_model()
        self.panel.push_history("restore")
        self.panel.chapter.content = text
        self.panel.content_box.edit_separator()
        self.panel.content_box.delete("1.0", "end")
        self.panel.content_box.insert("1.0", text)
        self.panel.content_box.edit_separator()
        # El resumen queda marcado como desactualizado si la version
        # restaurada no es la que se resumio (ver Chapter.summary_is_stale).
        self.panel._on_content_edited()
        self.panel._refresh_history_btn()
        self.panel.app.schedule_dirty_check()
        self.destroy()


class OutlinePanel(ctk.CTkFrame):
    """
    Panel de esquema (beat sheet) de un capitulo: titulo + beats principales.
    Vive en la pestana 'Esquema', separado de ChapterPanel, para poder revisar
    la estructura completa de la historia de un vistazo.
    """

    def __init__(self, master, index: int, chapter: Chapter, **kwargs):
        super().__init__(master, border_width=1, corner_radius=8, **kwargs)
        self.index = index
        self.chapter = chapter
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)
        title_text = chapter.title or f"Capítulo {index + 1}"
        ctk.CTkLabel(header, text=f"Capítulo {index + 1}: {title_text}", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.counter_label = ctk.CTkLabel(header, text="")
        self.counter_label.grid(row=0, column=1, sticky="e")

        self.outline_box = ctk.CTkTextbox(self, height=90, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.outline_box.insert("1.0", chapter.outline)
        self.outline_box.edit_reset()
        self.outline_box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.outline_box.bind("<KeyRelease>", self._on_change)
        self._on_change()

    def _on_change(self, _event=None) -> None:
        words = count_words(self.outline_box.get("1.0", "end-1c"))
        over = words > MAX_OUTLINE_WORDS_PER_CHAPTER
        self.counter_label.configure(
            text=f"{words:,} / {MAX_OUTLINE_WORDS_PER_CHAPTER:,} palabras",
            text_color=COLOR_ERROR if over else COLOR_MUTED,
        )

    def sync_to_model(self) -> None:
        self.chapter.outline = self.outline_box.get("1.0", "end-1c")


class LoreEntryPanel(ctk.CTkFrame):
    """
    Una entrada del Lorebook / World Info: nombre, palabras clave, texto, y
    si esta activa, siempre incluida o su prioridad (B8). Se inyecta en el
    prompt de un capitulo solo cuando alguna palabra clave aparece en el
    texto cercano de esa generacion (ver prompts.match_lore_entries).
    """

    def __init__(
        self, master, app: "StoryForgeApp", index: int, entry: LoreEntry,
        matched_last_generation: bool = False, match_reason: str = "", **kwargs,
    ):
        super().__init__(master, border_width=1, corner_radius=8, **kwargs)
        self.app = app
        self.index = index
        self.entry = entry
        self.matched_last_generation = matched_last_generation
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Nombre:").grid(row=0, column=0, padx=8, pady=(8, 2), sticky="w")
        self.name_entry = ctk.CTkEntry(self, placeholder_text="p.ej. Elena Vasquez")
        self.name_entry.insert(0, entry.name)
        self.name_entry.grid(row=0, column=1, padx=8, pady=(8, 2), sticky="ew")

        self.badge_label = ctk.CTkLabel(self, text="", text_color=COLOR_OK, font=ctk.CTkFont(size=11))
        self.badge_label.grid(row=0, column=2, padx=(8, 0), pady=(8, 2), sticky="e")
        self.set_match(matched_last_generation, match_reason)

        self.remove_btn = ctk.CTkButton(
            self, text="Eliminar", width=90, fg_color="#8a3b3b", hover_color="#6e2f2f",
            command=self._on_remove,
        )
        self.remove_btn.grid(row=0, column=3, padx=8, pady=(8, 2))

        ctk.CTkLabel(self, text="Palabras clave (separadas por coma):").grid(
            row=1, column=0, padx=8, pady=2, sticky="w"
        )
        self.keywords_entry = ctk.CTkEntry(self, placeholder_text="p.ej. Elena, la reina, Su Majestad")
        self.keywords_entry.insert(0, entry.keywords)
        self.keywords_entry.grid(row=1, column=1, columnspan=2, padx=8, pady=2, sticky="ew")

        options = ctk.CTkFrame(self, fg_color="transparent")
        options.grid(row=2, column=1, columnspan=3, sticky="w", padx=8, pady=2)
        self.enabled_var = ctk.BooleanVar(value=entry.enabled)
        self.constant_var = ctk.BooleanVar(value=entry.constant)
        ctk.CTkCheckBox(options, text="Activa", variable=self.enabled_var).pack(side="left", padx=(0, 12))
        ctk.CTkCheckBox(options, text="Incluir siempre", variable=self.constant_var).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(options, text="Prioridad:").pack(side="left", padx=(0, 4))
        self.priority_entry = ctk.CTkEntry(options, width=50)
        self.priority_entry.insert(0, str(entry.priority))
        self.priority_entry.pack(side="left")

        ctk.CTkLabel(self, text="Texto:").grid(row=3, column=0, padx=8, pady=(2, 8), sticky="nw")
        self.text_box = ctk.CTkTextbox(self, height=80, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.text_box.insert("1.0", entry.text)
        self.text_box.edit_reset()
        self.text_box.grid(row=3, column=1, columnspan=2, padx=8, pady=(2, 8), sticky="ew")

    def set_match(self, matched: bool, reason: str = "") -> None:
        self.matched_last_generation = matched
        text = ""
        if matched:
            text = "✓ usada en la última generación" + (f": {reason}" if reason else "")
        self.badge_label.configure(text=text)

    def sync_to_model(self) -> None:
        self.entry.name = self.name_entry.get().strip()
        self.entry.keywords = self.keywords_entry.get().strip()
        self.entry.text = self.text_box.get("1.0", "end-1c")
        self.entry.enabled = bool(self.enabled_var.get())
        self.entry.constant = bool(self.constant_var.get())
        try:
            self.entry.priority = max(-100, min(int(self.priority_entry.get()), 100))
        except ValueError:
            pass

    def _on_remove(self) -> None:
        label = self.entry.name.strip() or f"entrada {self.index + 1}"
        if messagebox.askyesno(APP_TITLE, f"¿Eliminar la entrada de lorebook '{label}'?"):
            self.app.remove_lore_entry(self.index)


def _lore_entry_matches_search(entry: LoreEntry, query: str) -> bool:
    """True si `entry` deberia mostrarse bajo `query` (ya en minusculas y sin
    espacios sobrantes): subcadena, sin distinguir mayusculas, contra el
    nombre o cualquiera de las palabras clave."""
    if not query:
        return True
    if query in entry.name.lower():
        return True
    return any(query in keyword.lower() for keyword in entry.keyword_list())


def about_text(engine) -> str:
    """Texto de Ayuda > Acerca de (K3)."""
    try:
        from importlib.metadata import version as pkg_version
        llama_version = pkg_version("llama-cpp-python")
    except Exception:  # noqa: BLE001
        llama_version = "no instalado"
    free = query_free_vram_bytes()
    gpu = "sí" if supports_gpu_offload() else "no (solo CPU)"
    lines = [
        f"{APP_TITLE} {__version__}",
        "",
        f"Python {platform.python_version()} ({platform.architecture()[0]}), {platform.system()} {platform.release()}",
        f"llama-cpp-python: {llama_version}",
        f"Soporte de GPU en llama-cpp-python: {gpu}",
        f"VRAM libre (nvidia-smi): {f'{free / 1024**3:.1f} GB' if free is not None else 'no disponible'}",
        f"Modelo cargado: {os.path.basename(engine.model_path) if getattr(engine, 'model_path', None) else 'ninguno'}",
        "",
        f"Carpeta de modelos: {MODELS_DIR}",
        f"Datos de usuario (autoguardado, preferencias): {user_data_dir()}",
        f"Registro de errores: {log_location()}",
    ]
    return "\n".join(lines)


class StoryForgeApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.prefs = get_ui_preferences()
        self._apply_global_preferences()
        self.geometry("1100x800")

        self.project = Project()
        self.engine = LocalStoryEngine()
        self.current_path: Optional[str] = None
        self.chapter_panels: list[ChapterPanel] = []
        self.outline_panels: list[OutlinePanel] = []
        # Paneles del lorebook VISIBLES (filtrados por la busqueda) y todos
        # los creados, por id() de la entrada: filtrar ya no destruye y
        # recrea cada panel en cada tecla (F11).
        self.lore_panels: list[LoreEntryPanel] = []
        self._lore_panel_cache: Dict[int, LoreEntryPanel] = {}
        self._lore_filter_after = None
        # ids de las LoreEntry que coincidieron con la ULTIMA generacion de
        # capitulo (y por que, ver _record_lore_matches()).
        self.last_lore_match_ids: set[int] = set()
        self.last_lore_reasons: Dict[int, str] = {}
        # El motor local envuelve una sola instancia de Llama, que no es
        # segura para llamadas concurrentes: este flag evita dos tareas a la vez.
        self.busy = False
        self.selected_chapter_index = 0
        self.focus_mode = False
        self.last_preview: Optional[DiffPreviewDialog] = None
        self._model_paths: Dict[str, str] = {}
        self._gpu_available = supports_gpu_offload()
        self.task_runner = EngineTaskRunner(self)
        # Resuelto ahora (no al importar el modulo): ver default_autosave_path().
        self.autosave_path = default_autosave_path()
        # Autoguardado en segundo plano (ver _autosave): contador de
        # generaciones para que una escritura vieja nunca pise una nueva.
        self._autosave_lock = threading.Lock()
        self._autosave_gen = 0
        self._autosave_written_gen = 0
        self._autosave_discarded_gen = 0
        self._autosave_errors: list = []
        self._last_autosave = 0.0
        self._clean_json = ""
        self.dirty = False
        self._dirty_after = None
        # Errores inesperados en callbacks de Tk: sin esto, en el .exe
        # (console=False) se imprimian a un stderr inexistente y se perdian.
        self.report_callback_exception = self._report_callback_exception
        self._showing_unexpected_error = False

        self._build_menu()
        self.status_bar = StatusBar(self, self)
        self.status_bar.pack(side="bottom", fill="x", padx=10, pady=(0, 6))
        self._build_tabs()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._mark_clean()
        self._offer_autosave_recovery()
        self._restore_last_model_selection()
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    # ---------------- preferencias (F9) ----------------
    def _apply_global_preferences(self) -> None:
        ctk.set_appearance_mode(self.prefs.get("appearance", "dark"))
        ctk.set_default_color_theme("blue")
        try:
            ctk.set_widget_scaling(float(self.prefs.get("ui_scale", 1.0)))
        except Exception:  # noqa: BLE001
            pass

    def apply_editor_preferences(self, box) -> None:
        family = self.prefs.get("editor_font_family") or None
        size = int(self.prefs.get("editor_font_size", 14))
        spacing = int(self.prefs.get("editor_line_spacing", 4))
        try:
            box.configure(font=ctk.CTkFont(family=family, size=size) if family else ctk.CTkFont(size=size))
            box._textbox.configure(spacing1=spacing // 2, spacing3=spacing - spacing // 2)
        except Exception:  # noqa: BLE001
            pass

    def open_preferences(self) -> None:
        PreferencesDialog(self, self.prefs, self._save_preferences)

    def _save_preferences(self, values: dict) -> None:
        self.prefs.update(values)
        set_ui_preferences(values)
        self._apply_global_preferences()
        for panel in self.chapter_panels:
            self.apply_editor_preferences(panel.content_box)
        self._refresh_models()

    # ---------------- menu ----------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Nuevo proyecto", command=self.new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="Abrir proyecto...", command=self.open_project, accelerator="Ctrl+O")
        file_menu.add_command(label="Guardar proyecto", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_command(
            label="Guardar proyecto como...", command=self.save_project_as, accelerator="Ctrl+Shift+S",
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exportar a Word (.docx)", command=self.export_word)
        file_menu.add_command(label="Exportar a EPUB", command=self.export_epub_file)
        file_menu.add_command(label="Exportar a Markdown (.md)", command=self.export_markdown_file)
        file_menu.add_command(label="Exportar a TXT", command=self.export_txt_file)
        file_menu.add_separator()
        file_menu.add_command(label="Preferencias...", command=self.open_preferences)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self._on_close)
        menubar.add_cascade(label="Archivo", menu=file_menu)
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Buscar en el capítulo", command=self.find_in_chapter, accelerator="Ctrl+F")
        edit_menu.add_command(label="Buscar en todo el proyecto...", command=self.open_project_search,
                              accelerator="Ctrl+Shift+F")
        menubar.add_cascade(label="Editar", menu=edit_menu)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Modo enfoque", command=self.toggle_focus_mode, accelerator="F11")
        view_menu.add_command(label="Ver el último prompt enviado", command=self.show_last_prompt)
        menubar.add_cascade(label="Ver", menu=view_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Acerca de StoryForge", command=self.show_about)
        help_menu.add_command(label="Abrir carpeta de registros", command=self._open_log_folder)
        menubar.add_cascade(label="Ayuda", menu=help_menu)
        self.configure(menu=menubar)

    # ---------------- atajos de teclado ----------------
    SHORTCUTS = {
        "<Control-n>": "new_project",
        "<Control-o>": "open_project",
        "<Control-s>": "save_project",
        "<Control-S>": "save_project_as",  # Ctrl+Shift+S
        "<Control-f>": "find_in_chapter",
        "<Control-F>": "open_project_search",  # Ctrl+Shift+F
        "<F11>": "toggle_focus_mode",
        "<Escape>": "cancel_running_generation",
    }

    def _bind_shortcuts(self) -> None:
        """
        Atajos globales (ver SHORTCUTS). Ctrl+Z / Ctrl+Y los da el propio
        cuadro de texto (undo=True); Ctrl+Enter se liga en el cuadro de cada
        capitulo (ChapterPanel._on_ctrl_enter).
        """
        for sequence, method_name in self.SHORTCUTS.items():
            method = getattr(self, method_name)
            # En la ventana principal (no bind_all): Esc dentro de un dialogo
            # no debe cancelar una generacion.
            self.bind(sequence, lambda _e, m=method: (m(), "break")[1])
        # El cuadro de texto de Tk trae Ctrl+O = "insertar salto de linea" y
        # Ctrl+F = "avanzar un caracter": sin quitarlos, el atajo tambien
        # editaria el texto.
        self.bind_class("Text", "<Control-o>", "")
        self.bind_class("Text", "<Control-f>", "")
        # Cualquier tecla puede dejar cambios sin guardar (F10).
        self.bind_all("<KeyRelease>", lambda _e: self.schedule_dirty_check(), add="+")

    def cancel_running_generation(self) -> None:
        """Esc: cancela la generacion de capitulo (o tarea) en curso."""
        for panel in self.chapter_panels:
            if panel._cancel_flag is not None:
                panel._on_cancel()
        self.task_runner.request_stop()

    def stop_current_task(self) -> None:
        """Boton "Detener" de la barra de estado: cualquier tarea del modelo."""
        self.cancel_running_generation()

    # ---------------- errores inesperados ----------------
    def _report_unexpected_error(self, exc_type, exc, tb, where: str = "") -> None:
        """Registra un error no capturado y se lo muestra al usuario (una
        ventana a la vez, para no apilar dialogos si se repite)."""
        logger.error("Error inesperado%s", where, exc_info=(exc_type, exc, tb))
        if self._showing_unexpected_error:
            return
        self._showing_unexpected_error = True
        try:
            messagebox.showerror(
                APP_TITLE,
                f"Ocurrió un error inesperado{where}:\n\n{exc_type.__name__}: {exc}\n\n"
                f"El detalle quedó registrado en:\n{log_location()}",
            )
        finally:
            self._showing_unexpected_error = False

    def _report_callback_exception(self, exc_type, exc, tb) -> None:
        self._report_unexpected_error(exc_type, exc, tb)

    def _thread_excepthook(self, args) -> None:
        """Para threading.excepthook: un error no capturado en un hilo de
        trabajo se registra y se muestra desde el hilo principal."""
        if args.exc_type is SystemExit:
            return
        exc_type, exc, tb = args.exc_type, args.exc_value, args.exc_traceback
        try:
            self.after(0, lambda: self._report_unexpected_error(exc_type, exc, tb, " en segundo plano"))
        except Exception:  # noqa: BLE001 - la ventana ya no existe
            logger.error("Error inesperado en segundo plano", exc_info=(exc_type, exc, tb))

    def _open_log_folder(self) -> None:
        folder = user_data_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)  # type: ignore[attr-defined]  # solo Windows
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo(APP_TITLE, f"La carpeta de registros es:\n{folder}\n\n({exc})")

    def show_about(self) -> None:
        TextViewerDialog(self, f"Acerca de {APP_TITLE}", about_text(self.engine))

    def show_last_prompt(self) -> None:
        stats = getattr(self.engine, "stats", None)
        if stats is None or not stats.prompt_text:
            messagebox.showinfo(APP_TITLE, "Todavía no se envió ningún prompt al modelo en esta sesión.")
            return
        sampling = ", ".join(f"{k}={v}" for k, v in sorted(stats.sampling.items()))
        header = (
            f"Operación: {stats.operation}  |  {stats.prompt_tokens:,} tokens de prompt + "
            f"{stats.max_tokens:,} reservados de {stats.n_ctx:,} (nivel de presupuesto {stats.budget_level}/3)"
            f"\nSemilla: {stats.seed}   Muestreo: {sampling}"
        )
        TextViewerDialog(self, "Prompt enviado al modelo", stats.prompt_text, header)

    def show_diff_preview(self, title: str, old: str, new: str, on_accept, on_accept_continue=None,
                          on_discard=None) -> DiffPreviewDialog:
        self.last_preview = DiffPreviewDialog(self, title, old, new, on_accept, on_accept_continue, on_discard)
        return self.last_preview

    # ---------------- tabs ----------------
    def _build_tabs(self) -> None:
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        self.tab_model = self.tabview.add("Modelo")
        self.tab_plot = self.tabview.add("Plot")
        self.tab_characters = self.tabview.add("Personajes")
        self.tab_setting = self.tabview.add("Setting")
        self.tab_lorebook = self.tabview.add("Lorebook")
        self.tab_outline = self.tabview.add("Esquema")
        self.tab_chapters = self.tabview.add("Capítulos")

        self._build_model_tab()
        self._build_plot_tab()
        self._build_characters_tab()
        self._build_setting_tab()
        self._build_lorebook_tab()
        self._build_outline_tab()
        self._build_chapters_tab()

    # ---------------- pestana Modelo ----------------
    def _build_model_tab(self) -> None:
        outer = ctk.CTkScrollableFrame(self.tab_model, fg_color="transparent")
        outer.pack(fill="both", expand=True)
        tab = outer
        tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Coloca un archivo de modelo .gguf en la carpeta 'models/' junto al programa "
                "(o en la carpeta de modelos adicional de Archivo > Preferencias) y cárgalo aquí. "
                "Ver models/README.txt para recomendaciones según tu GPU."
            ),
            wraplength=900, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=10)

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=10)
        row.grid_columnconfigure(0, weight=1)
        self.model_combo = ctk.CTkComboBox(
            row, values=self._list_models() or [NO_MODELS_LABEL], command=self._on_model_selected,
        )
        self.model_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(row, text="Actualizar lista", command=self._refresh_models).grid(row=0, column=1, padx=4)
        ctk.CTkButton(row, text="Elegir archivo...", command=self._browse_model).grid(row=0, column=2, padx=4)
        self.load_model_btn = ctk.CTkButton(row, text="Cargar modelo", command=self._load_model)
        self.load_model_btn.grid(row=0, column=3, padx=4)

        self.model_info_label = ctk.CTkLabel(tab, text="", text_color=COLOR_MUTED, wraplength=900, justify="left")
        self.model_info_label.grid(row=2, column=0, sticky="w", padx=10, pady=(6, 0))

        basic = ctk.CTkFrame(tab, fg_color="transparent")
        basic.grid(row=3, column=0, sticky="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(basic, text="Contexto (n_ctx, 0 = el del modelo):").pack(side="left", padx=(0, 4))
        self.n_ctx_entry = ctk.CTkEntry(basic, width=70)
        self.n_ctx_entry.insert(0, "8192")
        self.n_ctx_entry.pack(side="left", padx=(0, 12))
        gpu_layers_label = ("Capas en GPU (-1 = todas):" if self._gpu_available
                            else "Capas en GPU (0 = solo CPU):")
        ctk.CTkLabel(basic, text=gpu_layers_label).pack(side="left", padx=(0, 4))
        self.n_gpu_layers_entry = ctk.CTkEntry(basic, width=50)
        # -1 = TODAS las capas; solo se precarga con soporte de GPU real.
        self.n_gpu_layers_entry.insert(0, "-1" if self._gpu_available else "0")
        self.n_gpu_layers_entry.pack(side="left", padx=(0, 4))
        self.suggest_layers_btn = ctk.CTkButton(basic, text="Estimar VRAM", width=110, command=self._on_estimate_vram)
        self.suggest_layers_btn.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(basic, text="Hilos CPU (vacío = automático):").pack(side="left", padx=(0, 4))
        self.n_threads_entry = ctk.CTkEntry(basic, width=50)
        self.n_threads_entry.pack(side="left")
        gpu_status_text = ("GPU detectada: se usará para acelerar la generación." if self._gpu_available
                           else "Sin soporte de GPU (solo CPU).")
        self.gpu_status_label = ctk.CTkLabel(tab, text=gpu_status_text,
                                             text_color=COLOR_OK if self._gpu_available else COLOR_MUTED)
        self.gpu_status_label.grid(row=4, column=0, sticky="w", padx=10)

        # Opciones avanzadas de rendimiento (P1).
        adv = ctk.CTkFrame(tab, fg_color="transparent")
        adv.grid(row=5, column=0, sticky="w", padx=10, pady=(6, 0))
        self.flash_attn_var = ctk.BooleanVar(value=self._gpu_available)
        ctk.CTkCheckBox(adv, text="Flash attention", variable=self.flash_attn_var).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(adv, text="Lote (n_batch):").pack(side="left", padx=(0, 4))
        self.n_batch_entry = ctk.CTkEntry(adv, width=60)
        self.n_batch_entry.insert(0, "1024" if self._gpu_available else "512")
        self.n_batch_entry.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(adv, text="n_ubatch:").pack(side="left", padx=(0, 4))
        self.n_ubatch_entry = ctk.CTkEntry(adv, width=60, placeholder_text="auto")
        self.n_ubatch_entry.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(adv, text="Caché KV:").pack(side="left", padx=(0, 4))
        self.kv_cache_menu = ctk.CTkOptionMenu(adv, values=list(KV_CACHE_TYPES), width=90)
        self.kv_cache_menu.set("f16")
        self.kv_cache_menu.pack(side="left")

        chat_row = ctk.CTkFrame(tab, fg_color="transparent")
        chat_row.grid(row=6, column=0, sticky="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(chat_row, text="Formato de chat:").pack(side="left", padx=(0, 4))
        self.chat_format_menu = ctk.CTkOptionMenu(
            chat_row, values=[CHAT_FORMAT_LABELS[k] for k in CHAT_FORMAT_CHOICES], width=230,
            command=self._on_chat_format_changed,
        )
        self.chat_format_menu.set(CHAT_FORMAT_LABELS[CHAT_FORMAT_AUTO])
        self.chat_format_menu.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            chat_row,
            text="Auto usa la plantilla del GGUF o la deduce del vocabulario. Usa \"Sin plantilla\" para modelos base.",
            text_color=COLOR_MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")

        ctk.CTkLabel(
            tab,
            text=(
                "Un n_ctx mayor permite más contexto por llamada pero usa más memoria; no pases del "
                "contexto con el que se entrenó el modelo. Con GPU: flash attention + lote 1024-2048 "
                "aceleran el procesamiento del prompt, y la caché KV q8_0 usa la mitad de memoria "
                "(requiere flash attention). En CPU deja n_gpu_layers en 0."
            ),
            wraplength=900, justify="left", text_color=COLOR_MUTED, font=ctk.CTkFont(size=11),
        ).grid(row=7, column=0, sticky="w", padx=10, pady=(4, 0))

        self.model_status = ctk.CTkLabel(tab, text="Ningún modelo cargado.", text_color=COLOR_MUTED,
                                         wraplength=900, justify="left")
        self.model_status.grid(row=8, column=0, sticky="w", padx=10, pady=10)

        self._build_sampling_panel(tab, row=9)
        self._on_model_selected(self.model_combo.get())

    def _build_sampling_panel(self, tab, row: int) -> None:
        """Muestreo (B6): preset de prosa, valores avanzados y semilla. Se
        guarda en el proyecto; las demas tareas usan sus propios valores."""
        frame = ctk.CTkFrame(tab)
        frame.grid(row=row, column=0, sticky="ew", padx=10, pady=(4, 10))
        ctk.CTkLabel(frame, text="Muestreo de la prosa (se guarda con el proyecto)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=8, sticky="w", padx=8, pady=(6, 2))
        ctk.CTkLabel(frame, text="Preset:").grid(row=1, column=0, sticky="w", padx=8)
        self.sampling_preset_menu = ctk.CTkOptionMenu(frame, values=PRESET_CHOICES, width=150,
                                                      command=self._on_sampling_preset)
        self.sampling_preset_menu.grid(row=1, column=1, sticky="w")
        self.sampling_entries: Dict[str, ctk.CTkEntry] = {}
        fields = [("temperature", "Temperatura"), ("min_p", "min_p"), ("top_p", "top_p"), ("top_k", "top_k"),
                  ("repeat_penalty", "Penaliz. repetición"), ("presence_penalty", "Presencia"),
                  ("frequency_penalty", "Frecuencia")]
        for i, (name, label) in enumerate(fields):
            r, c = 2 + i // 4, (i % 4) * 2
            ctk.CTkLabel(frame, text=f"{label}:").grid(row=r, column=c, sticky="e", padx=(8, 4), pady=2)
            entry = ctk.CTkEntry(frame, width=70)
            entry.grid(row=r, column=c + 1, sticky="w", pady=2)
            entry.bind("<KeyRelease>", lambda _e: self.sampling_preset_menu.set(PRESET_CUSTOM))
            self.sampling_entries[name] = entry
        ctk.CTkLabel(frame, text="Semilla (vacío = aleatoria):").grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 8))
        self.seed_entry = ctk.CTkEntry(frame, width=110)
        self.seed_entry.grid(row=4, column=2, sticky="w", pady=(4, 8))
        ctk.CTkButton(frame, text="Usar la última", width=110, command=self._use_last_seed).grid(
            row=4, column=3, sticky="w", padx=6, pady=(4, 8))
        self.last_seed_label = ctk.CTkLabel(frame, text="", text_color=COLOR_MUTED)
        self.last_seed_label.grid(row=4, column=4, columnspan=4, sticky="w", padx=6, pady=(4, 8))
        self._load_sampling_into_ui()

    def _load_sampling_into_ui(self) -> None:
        cfg = self.project.sampling
        self.sampling_preset_menu.set(cfg.preset)
        self._show_sampling_values(cfg.prose())
        self.seed_entry.delete(0, "end")
        if cfg.seed is not None:
            self.seed_entry.insert(0, str(cfg.seed))

    def _show_sampling_values(self, settings: SamplingSettings) -> None:
        for name, entry in self.sampling_entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(getattr(settings, name)))

    def _on_sampling_preset(self, preset: str) -> None:
        if preset in PROSE_PRESETS:
            self._show_sampling_values(PROSE_PRESETS[preset])

    def _use_last_seed(self) -> None:
        seed = getattr(self.engine, "last_seed", None)
        if seed is None:
            messagebox.showinfo(APP_TITLE, "Todavía no se generó nada en esta sesión.")
            return
        self.seed_entry.delete(0, "end")
        self.seed_entry.insert(0, str(seed))

    def _sync_sampling(self) -> None:
        preset = self.sampling_preset_menu.get()
        values = {name: entry.get() for name, entry in self.sampling_entries.items()}
        custom = SamplingSettings.from_dict(values, self.project.sampling.custom_prose)
        if preset != PRESET_CUSTOM:
            custom = self.project.sampling.custom_prose
        self.project.sampling = SamplingConfig(preset=preset, custom_prose=custom,
                                               seed=parse_seed(self.seed_entry.get()))
        if isinstance(self.engine, LocalStoryEngine):
            self.engine.sampling = self.project.sampling
        seed = getattr(self.engine, "last_seed", None)
        if seed is not None:
            self.last_seed_label.configure(text=f"Última semilla usada: {seed}")

    def _selected_chat_format(self) -> str:
        return chat_format_from_label(self.chat_format_menu.get())

    def _resolve_model_selection(self, value: str) -> str:
        if value in self._model_paths:
            return self._model_paths[value]
        return value if os.path.isabs(value) else os.path.join(MODELS_DIR, value)

    def _on_model_selected(self, value: str) -> None:
        """Al elegir un modelo: formato de chat y opciones de carga usados con
        el la ultima vez en esta PC, y su informacion (cabecera GGUF)."""
        if not value or value.startswith("("):
            self.model_info_label.configure(text="")
            return
        path = self._resolve_model_selection(value)
        saved = get_chat_format_for_model(path)
        key = saved if saved in CHAT_FORMAT_CHOICES else CHAT_FORMAT_AUTO
        self.chat_format_menu.set(CHAT_FORMAT_LABELS[key])
        options = get_model_settings(path)
        self._apply_model_options(options)
        if os.path.isfile(path):
            self._current_model_info = model_info(path)
            text = self._current_model_info.summary_es()
            if not options and self._current_model_info.trained_context:
                # Primera vez con este modelo: contexto = el entrenado, como mucho 16k.
                self._set_entry(self.n_ctx_entry, str(min(self._current_model_info.trained_context, 16384)))
            self.model_info_label.configure(text=text)
        else:
            self._current_model_info = None
            self.model_info_label.configure(text="")

    @staticmethod
    def _set_entry(entry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    def _apply_model_options(self, options: dict) -> None:
        if "n_ctx" in options and isinstance(options["n_ctx"], int):
            self._set_entry(self.n_ctx_entry, str(options["n_ctx"]))
        if "n_gpu_layers" in options and isinstance(options["n_gpu_layers"], int):
            self._set_entry(self.n_gpu_layers_entry, str(options["n_gpu_layers"]))
        if "n_threads" in options:
            self._set_entry(self.n_threads_entry, str(options["n_threads"] or ""))
        if "flash_attn" in options:
            self.flash_attn_var.set(bool(options["flash_attn"]))
        if "n_batch" in options:
            self._set_entry(self.n_batch_entry, str(options["n_batch"] or ""))
        if "n_ubatch" in options:
            self._set_entry(self.n_ubatch_entry, str(options["n_ubatch"] or ""))
        if options.get("kv_cache_type") in KV_CACHE_TYPES:
            self.kv_cache_menu.set(options["kv_cache_type"])

    def _on_estimate_vram(self) -> None:
        """P2: cuanto ocupa el modelo elegido con este n_ctx/cache KV y cuantas
        capas conviene poner en la GPU (se completa el campo)."""
        info = getattr(self, "_current_model_info", None)
        if info is None or info.error:
            messagebox.showinfo(APP_TITLE, "Elige primero un modelo .gguf existente.")
            return
        try:
            n_ctx = int(self.n_ctx_entry.get()) or (info.trained_context or 8192)
        except ValueError:
            n_ctx = info.trained_context or 8192
        estimate = estimate_vram(info, n_ctx, self.kv_cache_menu.get(), query_free_vram_bytes(), query_total_ram_bytes())
        if estimate.suggested_gpu_layers is not None and self._gpu_available:
            self._set_entry(self.n_gpu_layers_entry, str(estimate.suggested_gpu_layers))
        color = COLOR_OK if estimate.fits_fully else (COLOR_WARN if estimate.fits_fully is False else COLOR_MUTED)
        self.model_info_label.configure(text=f"{info.summary_es()}\n{estimate.message}", text_color=color)

    def _on_chat_format_changed(self, _label: str = "") -> None:
        """Cambiar el formato no requiere recargar el modelo: se aplica a la
        proxima llamada y se recuerda para este modelo."""
        choice = self._selected_chat_format()
        if self.engine.is_loaded and not self.busy:
            self.engine.set_chat_format(choice)
            if self.engine.model_path:
                set_chat_format_for_model(self.engine.model_path, choice)
            self.model_status.configure(
                text=f"Formato de chat: {self._chat_format_description()}", text_color=COLOR_OK,
            )

    def _chat_format_description(self, choice: Optional[str] = None) -> str:
        choice = choice or self._selected_chat_format()
        try:
            label = self.engine.formatter.label
        except Exception:  # noqa: BLE001 - motores de prueba sin formateador
            label = None
        if not label:
            return CHAT_FORMAT_LABELS.get(choice, "")
        if choice == CHAT_FORMAT_AUTO:
            return f"{label} (auto)"
        return label

    def _model_dirs(self) -> List[str]:
        dirs = [MODELS_DIR]
        extra = (self.prefs.get("models_dir") or "").strip() if hasattr(self, "prefs") else ""
        if extra and os.path.isdir(extra) and os.path.abspath(extra) != os.path.abspath(MODELS_DIR):
            dirs.append(extra)
        return dirs

    def _list_models(self) -> list[str]:
        self._model_paths = {}
        labels = []
        for folder in self._model_dirs():
            for entry in list_model_entries(folder):
                label = entry.label if folder == MODELS_DIR else f"{entry.label} [{folder}]"
                self._model_paths[label] = entry.path
                labels.append(label)
        return labels

    def _refresh_models(self) -> None:
        values = self._list_models() or [NO_MODELS_LABEL]
        self.model_combo.configure(values=values)
        self.model_combo.set(values[0])
        self._on_model_selected(values[0])

    def _browse_model(self) -> None:
        path = filedialog.askopenfilename(title="Selecciona un modelo .gguf", filetypes=[("GGUF", "*.gguf")])
        if path:
            self.model_combo.set(path)
            self._on_model_selected(path)

    def _select_model_path(self, path: str) -> None:
        for label, known in self._model_paths.items():
            if os.path.normcase(known) == os.path.normcase(path):
                self.model_combo.set(label)
                self._on_model_selected(label)
                return
        self.model_combo.set(path)
        self._on_model_selected(path)

    def _restore_last_model_selection(self) -> None:
        """Preselecciona (sin cargar) el ultimo modelo usado en esta PC."""
        last = get_last_model()
        if last and os.path.isfile(last):
            self._select_model_path(last)

    def _restore_project_model(self) -> None:
        """Al abrir un proyecto: preselecciona su modelo y contexto, con un
        aviso explicito si el archivo ya no esta (antes se ignoraba)."""
        stored = self.project.model_path
        if not stored:
            return
        path = None
        for folder in self._model_dirs():
            candidate = resolve_model_path(stored, folder)
            if candidate and os.path.isfile(candidate):
                path = candidate
                break
        if path is None:
            self.model_status.configure(
                text=(f"Este proyecto se escribió con el modelo \"{os.path.basename(stored)}\", que no se "
                      "encontró en la carpeta de modelos. Elige otro modelo o copia ese archivo a models/."),
                text_color=COLOR_WARN,
            )
            return
        self._select_model_path(path)
        if self.project.context_size:
            self._set_entry(self.n_ctx_entry, str(self.project.context_size))
        loaded = getattr(self.engine, "model_path", None)
        if not (loaded and os.path.normcase(loaded) == os.path.normcase(path)):
            self.model_status.configure(
                text=f"Modelo del proyecto seleccionado: {os.path.basename(path)}. Pulsa \"Cargar modelo\".",
                text_color=COLOR_MUTED,
            )

    def _read_load_options(self) -> Optional[dict]:
        try:
            n_ctx = int(self.n_ctx_entry.get())
            if n_ctx < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Contexto (n_ctx) inválido: debe ser un entero >= 0 (0 = el del modelo).")
            return None
        try:
            n_gpu_layers = int(self.n_gpu_layers_entry.get())
            if n_gpu_layers < -1:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                APP_TITLE, "Capas en GPU (n_gpu_layers) inválido: debe ser un entero >= 0, o -1 para todas."
            )
            return None
        try:
            n_threads = _parse_optional_int(self.n_threads_entry.get())
            if n_threads is not None and n_threads <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                APP_TITLE, "Hilos CPU (n_threads) inválido: debe ser un entero mayor a 0, o vacío."
            )
            return None
        try:
            n_batch = _parse_optional_int(self.n_batch_entry.get())
            n_ubatch = _parse_optional_int(self.n_ubatch_entry.get())
            if (n_batch is not None and n_batch <= 0) or (n_ubatch is not None and n_ubatch <= 0):
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_TITLE, "n_batch / n_ubatch inválido: un entero mayor a 0, o vacío.")
            return None
        flash_attn = bool(self.flash_attn_var.get())
        kv = self.kv_cache_menu.get()
        if kv != "f16" and not flash_attn:
            messagebox.showwarning(APP_TITLE, f"La caché KV {kv} requiere flash attention: actívala o usa f16.")
            return None
        return dict(n_ctx=n_ctx, n_threads=n_threads, n_gpu_layers=n_gpu_layers, flash_attn=flash_attn,
                    n_batch=n_batch, n_ubatch=n_ubatch, kv_cache_type=kv)

    def _load_model(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, "Espera a que termine la generación en curso antes de cargar otro modelo.",
            )
            return
        selected = self.model_combo.get()
        if not selected or selected.startswith("("):
            messagebox.showwarning(APP_TITLE, "Selecciona un archivo .gguf válido.")
            return
        options = self._read_load_options()
        if options is None:
            return
        path = self._resolve_model_selection(selected)
        info = model_info(path) if os.path.isfile(path) else None
        if info is not None and info.missing_parts:
            messagebox.showerror(APP_TITLE, info.summary_es())
            return
        trained = info.trained_context if info else None
        if trained and options["n_ctx"] > trained and not messagebox.askyesno(
            APP_TITLE,
            f"Pediste n_ctx={options['n_ctx']:,}, pero este modelo se entrenó con {trained:,} tokens de "
            "contexto: por encima de eso la calidad suele degradarse mucho. ¿Cargar igual?",
        ):
            return
        chat_format = self._selected_chat_format()
        self.model_status.configure(text=f"Cargando {os.path.basename(path)}...", text_color=COLOR_MUTED)
        self.update_idletasks()
        engine = self.engine

        def work(_cancel_check):
            call_supported(engine.load, path, chat_format=chat_format, **options)
            return None

        def on_success(_result) -> None:
            self.project.model_path = portable_model_path(path, MODELS_DIR)
            actual_ctx = getattr(engine, "n_ctx", None)
            actual_ctx = actual_ctx if isinstance(actual_ctx, int) else options["n_ctx"]
            self.project.context_size = actual_ctx or None
            set_chat_format_for_model(path, chat_format)
            saved = dict(options)
            set_model_settings(path, saved)
            extras = []
            if options["n_threads"]:
                extras.append(f"n_threads={options['n_threads']}")
            if options["flash_attn"]:
                extras.append("flash attention")
            if options["kv_cache_type"] != "f16":
                extras.append(f"caché KV {options['kv_cache_type']}")
            extra = f", {', '.join(extras)}" if extras else ""
            self.model_status.configure(
                text=(f"Modelo cargado: {os.path.basename(path)} (n_ctx={actual_ctx}, "
                      f"n_gpu_layers={options['n_gpu_layers']}{extra}; formato de chat: "
                      f"{self._chat_format_description(chat_format)})"),
                text_color=COLOR_OK,
            )
            self.schedule_dirty_check()

        def on_error(exc) -> str:
            logger.error("No se pudo cargar el modelo %s: %s", path, exc)
            message = f"Error: {exc}"
            self.after(0, lambda: self.model_status.configure(text=message, text_color=COLOR_ERROR))
            return ""  # el error queda en la pestana, sin ventana extra

        self.task_runner.run(f"Cargando {os.path.basename(path)}", work, on_success=on_success,
                             on_error=on_error, autosave=False)

    # ---------------- Plot / Personajes / Setting ----------------
    def _build_plot_tab(self) -> None:
        tab = self.tab_plot
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        meta = ctk.CTkFrame(tab, fg_color="transparent")
        meta.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        meta.grid_columnconfigure(1, weight=2)
        meta.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(meta, text="Título de la historia:").grid(row=0, column=0, padx=(0, 6))
        self.story_title_entry = ctk.CTkEntry(meta, placeholder_text=DEFAULT_PROJECT_NAME)
        self.story_title_entry.grid(row=0, column=1, sticky="ew")
        self.story_title_entry.bind("<KeyRelease>", lambda _e: self._update_title())
        ctk.CTkLabel(meta, text="Autor:").grid(row=0, column=2, padx=(12, 6))
        self.author_entry = ctk.CTkEntry(meta)
        self.author_entry.grid(row=0, column=3, sticky="ew")
        ctk.CTkLabel(meta, text="Encabezado al exportar:").grid(row=0, column=4, padx=(12, 6))
        self.heading_menu = ctk.CTkOptionMenu(meta, values=[CHAPTER_HEADING_LABELS[k] for k in CHAPTER_HEADING_CHOICES], width=170)
        self.heading_menu.grid(row=0, column=5)
        note_row = ctk.CTkFrame(tab, fg_color="transparent")
        note_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 0))
        note_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(note_row, text="Nota del autor (toda la historia):").grid(row=0, column=0, padx=(0, 6))
        self.project_note_entry = ctk.CTkEntry(
            note_row, placeholder_text=f"Instrucción corta que se aplica a cada sección (máximo {MAX_AUTHOR_NOTE_WORDS} palabras), p.ej. \"tono sombrío, frases cortas\"",
        )
        self.project_note_entry.grid(row=0, column=1, sticky="ew")
        self.plot_box = LimitedTextBox(
            tab, "Story Plot (idea de la historia)", MAX_PLOT_WORDS, height=460,
            on_expand=lambda: self._expand_field(self.plot_box, "plot", "Plot", MAX_PLOT_WORDS),
            on_import=lambda: self._import_field(self.plot_box),
        )
        self.plot_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        self._load_project_meta_into_ui()

    def _load_project_meta_into_ui(self) -> None:
        self._set_entry(self.story_title_entry, self.project.name if self.project.name != DEFAULT_PROJECT_NAME else "")
        self._set_entry(self.author_entry, self.project.author)
        self._set_entry(self.project_note_entry, self.project.author_note)
        heading = self.project.chapter_heading if self.project.chapter_heading in CHAPTER_HEADING_LABELS else "Chapter"
        self.heading_menu.set(CHAPTER_HEADING_LABELS[heading])

    def _build_characters_tab(self) -> None:
        self.tab_characters.grid_columnconfigure(0, weight=1)
        self.tab_characters.grid_rowconfigure(0, weight=1)
        self.characters_box = LimitedTextBox(
            self.tab_characters, "Personajes (descripción, personalidad, relaciones)",
            MAX_CHARACTERS_WORDS, height=500,
            on_expand=lambda: self._expand_field(
                self.characters_box, "characters", "Personajes", MAX_CHARACTERS_WORDS
            ),
            on_import=lambda: self._import_field(self.characters_box),
        )
        self.characters_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def _build_setting_tab(self) -> None:
        self.tab_setting.grid_columnconfigure(0, weight=1)
        self.tab_setting.grid_rowconfigure(0, weight=1)
        self.setting_box = LimitedTextBox(
            self.tab_setting, "Setting (dónde y cuándo ocurre la historia)",
            MAX_SETTING_WORDS, height=500,
            on_expand=lambda: self._expand_field(self.setting_box, "setting", "Setting", MAX_SETTING_WORDS),
            on_import=lambda: self._import_field(self.setting_box),
        )
        self.setting_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    # ---------------- Lorebook ----------------
    def _build_lorebook_tab(self) -> None:
        tab = self.tab_lorebook
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "El Lorebook guarda personajes secundarios, lugares u objetos que no "
                "necesitas repetir en Personajes/Setting. Cada entrada solo se agrega al "
                "prompt cuando alguna de sus palabras clave aparece en el esquema del capítulo, "
                "en el resumen de los capítulos anteriores o en lo último que se escribió -- así "
                "puedes mantener un elenco o mundo mucho más grande sin agotar el contexto del "
                "modelo. \"Incluir siempre\" la agrega en cada capítulo; con muchas coincidencias "
                "entran primero las de mayor prioridad."
            ),
            wraplength=900, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        self.add_lore_btn = ctk.CTkButton(top, text="+ Agregar entrada", command=self.add_lore_entry)
        self.add_lore_btn.pack(side="left")
        ctk.CTkLabel(top, text=f"(máximo {MAX_LORE_ENTRIES} entradas)").pack(side="left", padx=8)

        search_row = ctk.CTkFrame(tab, fg_color="transparent")
        search_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        search_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search_row, text="Buscar:").grid(row=0, column=0, padx=(0, 6))
        self.lore_search_entry = ctk.CTkEntry(search_row, placeholder_text="Filtrar por nombre o palabra clave...")
        self.lore_search_entry.grid(row=0, column=1, sticky="ew")
        # Filtra con una pequena espera tras la ultima tecla (F11).
        self.lore_search_entry.bind("<KeyRelease>", lambda _e: self._schedule_lore_filter())

        self.lorebook_scroll = ctk.CTkScrollableFrame(tab)
        self.lorebook_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.lorebook_scroll.grid_columnconfigure(0, weight=1)
        self._lore_placeholder = ctk.CTkLabel(self.lorebook_scroll, text="", text_color=COLOR_MUTED,
                                              wraplength=800, justify="left")
        self._render_lore_entries()

    def _schedule_lore_filter(self) -> None:
        if self._lore_filter_after is not None:
            try:
                self.after_cancel(self._lore_filter_after)
            except Exception:  # noqa: BLE001
                pass
        self._lore_filter_after = self.after(LORE_FILTER_DEBOUNCE_MS, self._render_lore_entries)

    def add_lore_entry(self) -> None:
        if not self.project.can_add_lore_entry():
            messagebox.showinfo(APP_TITLE, f"Ya hay {MAX_LORE_ENTRIES} entradas (el máximo).")
            return
        self.project.add_lore_entry()
        self._render_lore_entries()
        self.schedule_dirty_check()

    def remove_lore_entry(self, index: int) -> None:
        self._sync_lore_panels()
        entry = self.project.lore_entries.pop(index)
        panel = self._lore_panel_cache.pop(id(entry), None)
        if panel is not None:
            panel.destroy()
        self._render_lore_entries()
        self.schedule_dirty_check()

    def _sync_lore_panels(self) -> None:
        for panel in self._lore_panel_cache.values():
            panel.sync_to_model()

    def _clear_lore_panels(self) -> None:
        for panel in self._lore_panel_cache.values():
            panel.destroy()
        self._lore_panel_cache = {}
        self.lore_panels = []

    def _render_lore_entries(self) -> None:
        """Muestra las entradas que pasan el filtro de busqueda. Reutiliza los
        paneles existentes (solo los oculta/muestra) en vez de destruir y
        recrear todos en cada tecla (F11); crea solo los que faltan."""
        self._lore_filter_after = None
        self._sync_lore_panels()
        current = {id(e): (i, e) for i, e in enumerate(self.project.lore_entries)}
        for key in [k for k in self._lore_panel_cache if k not in current]:
            self._lore_panel_cache.pop(key).destroy()
        query = self.lore_search_entry.get().strip().lower() if hasattr(self, "lore_search_entry") else ""
        self.lore_panels = []
        row = 0
        for i, entry in enumerate(self.project.lore_entries):
            panel = self._lore_panel_cache.get(id(entry))
            matched = id(entry) in self.last_lore_match_ids
            reason = self.last_lore_reasons.get(id(entry), "")
            if panel is None:
                panel = LoreEntryPanel(self.lorebook_scroll, self, i, entry,
                                       matched_last_generation=matched, match_reason=reason)
                self._lore_panel_cache[id(entry)] = panel
            else:
                panel.index = i
                panel.set_match(matched, reason)
            if _lore_entry_matches_search(entry, query):
                panel.grid(row=row, column=0, sticky="ew", pady=6)
                self.lore_panels.append(panel)
                row += 1
            else:
                panel.grid_remove()
        if not self.project.lore_entries:
            self._lore_placeholder.configure(text="Aún no hay entradas de lorebook. Agrega una arriba.")
            self._lore_placeholder.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        elif not self.lore_panels:
            self._lore_placeholder.configure(text="Ninguna entrada coincide con la búsqueda.")
            self._lore_placeholder.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        else:
            self._lore_placeholder.grid_remove()
        self.add_lore_btn.configure(state="normal" if self.project.can_add_lore_entry() else "disabled")
        if self.busy:
            self._set_engine_busy(True)

    def _record_lore_matches(self, chapter_index: int) -> None:
        """
        Recalcula que entradas del lorebook coincidieron con el texto de
        escaneo de la generacion que acaba de terminar (esquema + capitulos
        previos + final del capitulo) y por que (palabra clave, siempre
        incluida, o mencionada en otra entrada), para la marca "usada en la
        ultima generacion" de la pestana Lorebook.
        """
        if not (0 <= chapter_index < len(self.project.chapters)):
            return
        chapter = self.project.chapters[chapter_index]
        previous = build_previous_context(self.project, chapter_index)
        scan_text = build_lore_scan_text(chapter, previous, chapter.content)
        matches = match_lore_entries(self.project.lore_entries, scan_text)
        self.last_lore_match_ids = {id(m.entry) for m in matches}
        self.last_lore_reasons = {id(m.entry): m.reason_es() for m in matches}
        self._render_lore_entries()

    def _import_field(self, box: LimitedTextBox) -> None:
        """Reemplaza el contenido de `box` con el texto de un archivo elegido
        por el usuario. Sincrono, no toca el motor."""
        path = filedialog.askopenfilename(
            title="Importar texto desde archivo",
            filetypes=[("Texto", "*.txt"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"No se pudo leer el archivo: {exc}")
            return
        if box.get().strip() and not messagebox.askyesno(
            APP_TITLE, "Esto reemplazará el contenido actual de este campo. ¿Continuar?"
        ):
            return
        box.set(text)
        self.schedule_dirty_check()

    def _expand_field(self, box: LimitedTextBox, field_key: str, field_label: str, max_words: int) -> None:
        """Reemplaza la nota corta de `box` por una version mas desarrollada
        (LocalStoryEngine.expand_field()); Ctrl+Z vuelve a la nota."""
        if not self.engine.is_loaded:
            messagebox.showwarning(APP_TITLE, "Primero carga un modelo local (.gguf) en la pestaña 'Modelo'.")
            return
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, "Ya hay una generación en curso. Espera a que termine antes de iniciar otra."
            )
            return
        text = box.get().strip()
        if not text:
            messagebox.showwarning(APP_TITLE, f"Escribe una idea corta en {field_label} primero.")
            return
        if count_words(text) > 60 and not messagebox.askyesno(
            APP_TITLE,
            f"{field_label} ya tiene bastante texto escrito. Expandir con IA lo reemplaza por "
            "completo (Ctrl+Z lo recupera). ¿Continuar?",
        ):
            return
        self._sync_all()
        engine = self.engine

        def work(cancel_check):
            return call_supported(engine.expand_field, field_key, text, max_words=min(max_words, 500),
                                  cancel_check=cancel_check)

        def on_success(expanded: str) -> None:
            box.set(expanded, undoable=True)  # Ctrl+Z vuelve a la nota original
            self.schedule_dirty_check()

        self.task_runner.run(f"Expandir {field_label}", work, on_success=on_success,
                             error_prefix="Error expandiendo el campo: ")

    # ---------------- Esquema ----------------
    def _build_outline_tab(self) -> None:
        tab = self.tab_outline
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Genera primero un esquema (beat sheet) de todos los capítulos a partir "
                "del plot, personajes y setting. Escribir la historia siguiendo un esquema "
                "acordado de antemano ayuda mucho a que se mantenga consistente de principio "
                "a fin. Puedes editar el resultado aquí antes de generar la prosa en la "
                "pestaña 'Capítulos'."
            ),
            wraplength=900, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(controls, text="Número de capítulos:").pack(side="left", padx=(0, 6))
        self.outline_count_entry = ctk.CTkEntry(controls, width=50)
        self.outline_count_entry.insert(0, str(len(self.project.chapters) or MAX_CHAPTERS))
        self.outline_count_entry.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(controls, text="Tipo de escritura:").pack(side="left", padx=(0, 6))
        self.writing_style_menu = ctk.CTkOptionMenu(controls, values=WRITING_STYLE_OPTIONS, width=160)
        self.writing_style_menu.set(style_label(self.project.writing_style if self.project.writing_style in WRITING_STYLES else ""))
        self.writing_style_menu.pack(side="left", padx=(0, 12))
        self.generate_outline_btn = ctk.CTkButton(
            controls, text="Generar esquema completo", command=self._on_generate_outline
        )
        self.generate_outline_btn.pack(side="left")
        self.complete_outline_btn = ctk.CTkButton(
            controls, text="Completar capítulos faltantes", state="disabled", command=self._on_complete_outline,
        )
        self.complete_outline_btn.pack(side="left", padx=(8, 0))
        self.outline_status = ctk.CTkLabel(controls, text="", text_color=COLOR_MUTED)
        self.outline_status.pack(side="left", padx=12)
        self._outline_requested: Optional[int] = None

        self.outline_scroll = ctk.CTkScrollableFrame(tab)
        self.outline_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.outline_scroll.grid_columnconfigure(0, weight=1)
        self._render_outline_panels()

    def _outline_preconditions(self, message_when_busy: str) -> bool:
        if not self.engine.is_loaded:
            messagebox.showwarning(APP_TITLE, "Primero carga un modelo local (.gguf) en la pestaña 'Modelo'.")
            return False
        if self.busy:
            messagebox.showwarning(APP_TITLE, message_when_busy)
            return False
        self._sync_all()
        errors = self.project.validate_inputs()
        if errors:
            messagebox.showwarning(APP_TITLE, "Corrige antes de generar el esquema:\n\n" + "\n".join(errors))
            return False
        return True

    def _on_generate_outline(self) -> None:
        if not self._outline_preconditions(
            "Ya hay una generación en curso (un capítulo u otra operación). Espera a que termine."
        ):
            return
        try:
            num_chapters = int(self.outline_count_entry.get())
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Número de capítulos inválido.")
            return
        num_chapters = max(1, min(num_chapters, MAX_CHAPTERS))

        if self.project.chapters and not messagebox.askyesno(
            APP_TITLE,
            "Esto reemplazará el título y esquema de los capítulos existentes "
            "(la prosa ya generada de cada capítulo se conserva). ¿Continuar?",
        ):
            return

        self.outline_status.configure(text="Generando esquema...", text_color=COLOR_MUTED)
        engine = self.engine
        project = self.project

        def work(cancel_check):
            items = call_supported(engine.generate_outline, project, num_chapters, cancel_check=cancel_check)
            truncated = getattr(engine, "last_finish_reason", None) == "length"
            return items, truncated

        def on_success(outcome) -> None:
            items, truncated = outcome
            self._apply_outline(items)
            self._report_outline_state(len(items), num_chapters, truncated)

        self.task_runner.run(
            "Esquema", work, on_success=on_success, on_error=self._outline_error,
            on_cancel=lambda: self.outline_status.configure(text="Esquema detenido: no se cambió nada.",
                                                            text_color=COLOR_WARN),
            error_prefix="Error generando el esquema: ",
        )

    def _report_outline_state(self, have: int, wanted: int, truncated: bool) -> None:
        if have < wanted or truncated:
            cause = " (la respuesta del modelo se cortó por largo)" if truncated else ""
            self._outline_requested = wanted if have < wanted else None
            self.outline_status.configure(
                text=(f"Esquema incompleto: {have} de {wanted} capítulos{cause}. Usa \"Completar "
                      "capítulos faltantes\", genera de nuevo o complétalos a mano."),
                text_color=COLOR_WARN,
            )
        else:
            self._outline_requested = None
            self.outline_status.configure(text=f"Esquema generado: {have} capítulos.", text_color=COLOR_OK)
        self._refresh_complete_outline_btn()

    def _refresh_complete_outline_btn(self) -> None:
        enabled = (not self.busy and self._outline_requested is not None
                   and len(self._outlined_chapters()) < self._outline_requested)
        self.complete_outline_btn.configure(state="normal" if enabled else "disabled")

    def _outlined_chapters(self) -> list:
        """(titulo, esquema) de los capitulos iniciales que ya tienen esquema."""
        items = []
        for ch in self.project.chapters:
            if not ch.outline.strip():
                break
            items.append((ch.title, ch.outline))
        return items

    def _on_complete_outline(self) -> None:
        """B4: pide solo los capitulos que faltan de un esquema incompleto."""
        if self._outline_requested is None:
            return
        if not self._outline_preconditions("Ya hay una generación en curso. Espera a que termine."):
            return
        existing = self._outlined_chapters()
        wanted = self._outline_requested
        engine = self.engine
        project = self.project
        self.outline_status.configure(text="Completando el esquema...", text_color=COLOR_MUTED)

        def work(cancel_check):
            return call_supported(engine.complete_outline, project, wanted, existing, cancel_check=cancel_check)

        def on_success(new_items) -> None:
            combined = existing + list(new_items)
            self._apply_outline(combined)
            truncated = getattr(engine, "last_finish_reason", None) == "length"
            self._report_outline_state(len(combined), wanted, truncated and len(combined) < wanted)

        self.task_runner.run("Completar esquema", work, on_success=on_success, on_error=self._outline_error,
                             error_prefix="Error completando el esquema: ")

    def _outline_error(self, exc) -> Optional[str]:
        if isinstance(exc, OutlineParseError):
            # Antes, una respuesta sin encabezados reconocibles se aplicaba
            # entera como esquema del capitulo 1.
            snippet = exc.raw_text.strip()
            if len(snippet) > 800:
                snippet = snippet[:800] + " [...]"
            self.after(0, lambda: self.outline_status.configure(text="", text_color=COLOR_MUTED))
            return (f"{exc}\n\nNo se modificó el esquema. Genera de nuevo (o prueba otro "
                    f"\"Formato de chat\" en la pestaña Modelo).\n\nRespuesta del modelo:\n{snippet}")
        return None

    def _apply_outline(self, outline_items: list[tuple[str, str]]) -> None:
        # Los paneles se recrean abajo: sincronizamos ANTES de aplicar el
        # esquema nuevo para no perder la prosa editada a mano mientras el
        # esquema se generaba.
        self._sync_all()
        for i, (title, outline) in enumerate(outline_items):
            if i < len(self.project.chapters):
                self.project.chapters[i].title = title or self.project.chapters[i].title
                self.project.chapters[i].outline = outline
            elif self.project.can_add_chapter():
                self.project.add_chapter(title=title, outline=outline)
        self._render_outline_panels()
        self._render_chapters()
        self.schedule_dirty_check()

    def _render_outline_panels(self) -> None:
        for child in self.outline_scroll.winfo_children():
            child.destroy()
        self.outline_panels = []
        if not self.project.chapters:
            ctk.CTkLabel(
                self.outline_scroll,
                text="Aún no hay capítulos. Genera un esquema completo arriba, o agrega "
                     "capítulos manualmente en la pestaña 'Capítulos'.",
                text_color=COLOR_MUTED, wraplength=800, justify="left",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return
        for i, chapter in enumerate(self.project.chapters):
            panel = OutlinePanel(self.outline_scroll, i, chapter)
            panel.grid(row=i, column=0, sticky="ew", pady=6)
            self.outline_panels.append(panel)

    # ---------------- Capitulos ----------------
    def _build_chapters_tab(self) -> None:
        tab = self.tab_chapters
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        self.chapters_top = ctk.CTkFrame(tab, fg_color="transparent")
        self.chapters_top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        self.add_chapter_btn = ctk.CTkButton(self.chapters_top, text="+ Agregar capítulo", command=self.add_chapter)
        self.add_chapter_btn.pack(side="left")
        ctk.CTkLabel(self.chapters_top, text=f"(máximo {MAX_CHAPTERS} capítulos)").pack(side="left", padx=8)
        self.focus_btn = ctk.CTkButton(self.chapters_top, text="Modo enfoque (F11)", width=150,
                                       command=self.toggle_focus_mode)
        self.focus_btn.pack(side="right")

        # Lista de capitulos (numero, titulo, palabras/objetivo): elige cual
        # se muestra en el editor.
        self.chapter_sidebar = ctk.CTkScrollableFrame(tab, width=190, label_text="Capítulos")
        self.chapter_sidebar.grid(row=1, column=0, sticky="ns", padx=(10, 0), pady=10)
        self.chapter_sidebar.grid_columnconfigure(0, weight=1)

        # Un solo capitulo a la vez, ocupando todo el alto disponible.
        self.chapters_scroll = ctk.CTkFrame(tab, fg_color="transparent")
        self.chapters_scroll.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
        self.chapters_scroll.grid_columnconfigure(0, weight=1)
        self.chapters_scroll.grid_rowconfigure(0, weight=1)
        self._render_chapters()

    def toggle_focus_mode(self) -> None:
        """Modo enfoque: oculta la lista de capitulos y el refinamiento/resumen
        para que el editor ocupe la ventana (F1)."""
        self.focus_mode = not self.focus_mode
        if self.focus_mode:
            self.tabview.set("Capítulos")
            self.chapter_sidebar.grid_remove()
            self.focus_btn.configure(text="Salir del modo enfoque")
        else:
            self.chapter_sidebar.grid()
            self.focus_btn.configure(text="Modo enfoque (F11)")
        for panel in self.chapter_panels:
            panel.set_focus_mode(self.focus_mode)

    def add_chapter(self) -> None:
        if not self.project.can_add_chapter():
            messagebox.showinfo(APP_TITLE, f"Ya hay {MAX_CHAPTERS} capítulos (el máximo).")
            return
        # Los paneles se destruyen y recrean desde project.chapters: cualquier
        # edicion todavia sin sincronizar se perderia sin esto.
        self._sync_all()
        self.project.add_chapter()
        self.selected_chapter_index = len(self.project.chapters) - 1
        self._render_chapters()
        self._render_outline_panels()
        self.schedule_dirty_check()

    def remove_chapter(self, index: int) -> None:
        self._sync_all()
        del self.project.chapters[index]
        if index < self.selected_chapter_index:
            self.selected_chapter_index -= 1
        self._render_chapters()
        self._render_outline_panels()
        self.schedule_dirty_check()

    def _render_chapters(self) -> None:
        for child in self.chapters_scroll.winfo_children():
            child.destroy()
        self.chapter_panels = []
        if self.project.chapters:
            self.selected_chapter_index = max(0, min(self.selected_chapter_index, len(self.project.chapters) - 1))
        else:
            self.selected_chapter_index = 0
        for i, chapter in enumerate(self.project.chapters):
            panel = ChapterPanel(self.chapters_scroll, self, i, chapter)
            panel.grid(row=0, column=0, sticky="nsew")
            if i != self.selected_chapter_index:
                panel.grid_remove()
            if self.focus_mode:
                panel.set_focus_mode(True)
            self.chapter_panels.append(panel)
        if not self.project.chapters:
            ctk.CTkLabel(
                self.chapters_scroll,
                text="Aún no hay capítulos. Agrega uno arriba o genera un esquema en la pestaña 'Esquema'.",
                text_color=COLOR_MUTED,
            ).grid(row=0, column=0, sticky="nw", padx=8, pady=8)
        self.add_chapter_btn.configure(state="normal" if self.project.can_add_chapter() else "disabled")
        # Paneles creados durante una generacion nacen ya deshabilitados.
        if self.busy:
            self._set_engine_busy(True)
        self._render_chapter_sidebar()

    def _render_chapter_sidebar(self) -> None:
        for child in self.chapter_sidebar.winfo_children():
            child.destroy()
        if not self.project.chapters:
            ctk.CTkLabel(self.chapter_sidebar, text="Sin capítulos.", text_color=COLOR_MUTED).grid(
                row=0, column=0, sticky="w", padx=6, pady=6)
            self._refresh_word_totals()
            return
        for i, chapter in enumerate(self.project.chapters):
            title = chapter.title.strip() or f"Capítulo {i + 1}"
            words = chapter.word_count()
            label = f"{i + 1}. {title}\n{words:,} / {chapter.target_words:,} palabras"
            selected = i == self.selected_chapter_index
            btn = ctk.CTkButton(
                self.chapter_sidebar, text=label, anchor="w",
                fg_color=(SELECTED_SIDEBAR_COLOR if selected else "transparent"),
                text_color=("#1a1a1a", "#e6e6e6"),
                hover_color=("#d0d0d0", "#2b2b2b"), command=lambda idx=i: self._jump_to_chapter(idx),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=4, pady=2)
        self._refresh_word_totals()

    def _refresh_word_totals(self) -> None:
        if hasattr(self, "status_bar"):
            self.status_bar.set_word_total(self.project.total_words(), len(self.project.chapters))

    def _jump_to_chapter(self, index: int) -> None:
        """Muestra el capitulo `index` en el editor (uno a la vez); los demas
        paneles siguen existiendo (una generacion en curso en otro capitulo
        sigue actualizando el suyo), solo quedan ocultos."""
        if not (0 <= index < len(self.chapter_panels)):
            return
        for panel in self.chapter_panels:
            if not panel.is_generating:
                panel.sync_to_model()
        self.selected_chapter_index = index
        for i, panel in enumerate(self.chapter_panels):
            if i == index:
                panel.grid()
            else:
                panel.grid_remove()
        self._render_chapter_sidebar()

    select_chapter = _jump_to_chapter

    def current_chapter_panel(self) -> Optional[ChapterPanel]:
        if 0 <= self.selected_chapter_index < len(self.chapter_panels):
            return self.chapter_panels[self.selected_chapter_index]
        return None

    def _refresh_summary_views(self) -> None:
        for panel in self.chapter_panels:
            if panel.summary_box.get("1.0", "end-1c").strip() != panel.chapter.summary.strip():
                panel._show_summary_text(panel.chapter.summary)
            else:
                panel._refresh_summary_status()

    # ---------------- buscar (F5) ----------------
    def find_in_chapter(self) -> None:
        panel = self.current_chapter_panel()
        if panel is None:
            return
        self.tabview.set("Capítulos")
        panel.show_find_bar()

    def open_project_search(self) -> ProjectSearchDialog:
        initial = ""
        panel = self.current_chapter_panel()
        if panel is not None:
            rng = panel._selection_range()
            if rng:
                initial = panel.content_box.get(*rng).strip()[:80]
        return ProjectSearchDialog(self, initial)

    def jump_to_search_hit(self, hit: SearchHit, query: str) -> None:
        if hit.field in ("chapter", "summary") and 0 <= hit.index < len(self.chapter_panels):
            self.tabview.set("Capítulos")
            self._jump_to_chapter(hit.index)
            panel = self.chapter_panels[hit.index]
            if hit.field == "summary":
                if not panel.summary_visible:
                    panel._toggle_summary()
                box = panel.summary_box
            else:
                box = panel.content_box
            start = f"1.0+{hit.start}c"
            end = f"1.0+{hit.end}c"
            box.tag_remove("sel", "1.0", "end")
            box.tag_add("sel", start, end)
            box.mark_set("insert", end)
            box.see(start)
            box.focus_set()
        elif hit.field == "outline":
            self.tabview.set("Esquema")
        elif hit.field == "lore":
            self.tabview.set("Lorebook")
        else:
            self.tabview.set({"plot": "Plot", "characters": "Personajes", "setting": "Setting"}[hit.field])

    def replace_in_project(self, query: str, replacement: str, case_sensitive: bool = False,
                           whole_word: bool = False) -> int:
        """Reemplazar en todo el proyecto. Cada capitulo cuyo texto cambia
        guarda antes una version ("Versiones anteriores")."""
        if self.busy:
            messagebox.showwarning(APP_TITLE, "Espera a que termine la generación en curso.")
            return 0
        if not query:
            return 0
        self._sync_all()
        total = 0

        def rep(text: str) -> tuple[str, int]:
            return replace_in_text(text, query, replacement, case_sensitive, whole_word)

        for attr in ("plot", "characters", "setting"):
            new, n = rep(getattr(self.project, attr))
            setattr(self.project, attr, new)
            total += n
        for ch in self.project.chapters:
            new, n = rep(ch.content)
            if n:
                self.project.push_chapter_history(ch, "replace")
                ch.content = new
                total += n
            ch.outline, n2 = rep(ch.outline)
            total += n2
            summary, n3 = rep(ch.summary)
            if n3:
                # El resumen sigue describiendo el mismo texto (solo cambio un nombre).
                fresh = not ch.summary_is_stale()
                ch.summary = summary
                if fresh:
                    ch.summary_source_hash = content_hash(ch.content)
                total += n3
        for entry in self.project.lore_entries:
            entry.text, n = rep(entry.text)
            entry.name, n2 = rep(entry.name)
            entry.keywords, n3 = rep(entry.keywords)
            total += n + n2 + n3
        if total:
            self._load_into_ui(keep_selection=True)
            self.schedule_dirty_check()
        return total

    # ---------------- exclusion mutua del motor ----------------
    def _set_engine_busy(self, busy: bool) -> None:
        """
        Deshabilita, a nivel de toda la app, todo lo que pueda disparar una
        llamada al modelo mientras alguna operacion ya esta en curso en otro
        hilo. self.engine envuelve una sola instancia de Llama, que no
        soporta llamadas concurrentes.
        """
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.generate_outline_btn.configure(state=state)
        self.load_model_btn.configure(state=state)
        self._refresh_complete_outline_btn()
        # Agregar/quitar capitulos durante una generacion desplazaria los
        # indices de project.chapters que el hilo en curso sigue usando.
        self.add_chapter_btn.configure(
            state="disabled" if busy else ("normal" if self.project.can_add_chapter() else "disabled")
        )
        for panel in self.chapter_panels:
            for btn in (panel.generate_btn, panel.continue_btn, panel.continue_cursor_btn,
                        panel.regen_summary_btn, panel.remove_btn, panel.refine_btn):
                btn.configure(state=state)
            panel._refresh_retry_controls(busy)
        for box in (self.plot_box, self.characters_box, self.setting_box):
            expand_btn = getattr(box, "expand_btn", None)
            if expand_btn is not None:
                expand_btn.configure(state=state)
        self.add_lore_btn.configure(
            state="disabled" if busy else ("normal" if self.project.can_add_lore_entry() else "disabled")
        )
        for panel in self._lore_panel_cache.values():
            panel.remove_btn.configure(state=state)
        if not busy:
            self._refresh_word_totals()

    # ---------------- cambios sin guardar (F10) ----------------
    def _current_json(self) -> str:
        return self.project.to_json()

    def _mark_clean(self) -> None:
        self._sync_all()
        self._clean_json = self._current_json()
        self.dirty = False
        self._update_title()

    def schedule_dirty_check(self) -> None:
        if self._dirty_after is not None:
            return
        try:
            self._dirty_after = self.after(DIRTY_CHECK_DEBOUNCE_MS, self._update_dirty_state)
        except Exception:  # noqa: BLE001 - ventana destruida
            self._dirty_after = None

    def _update_dirty_state(self) -> bool:
        self._dirty_after = None
        try:
            self._sync_all()
            self.dirty = self._current_json() != self._clean_json
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo comprobar si hay cambios sin guardar")
        self._update_title()
        return self.dirty

    def is_dirty(self) -> bool:
        return self._update_dirty_state()

    def _update_title(self) -> None:
        name = (self.story_title_entry.get().strip() if hasattr(self, "story_title_entry") else "") \
            or self.project.name or DEFAULT_PROJECT_NAME
        file_part = f" ({os.path.basename(self.current_path)})" if self.current_path else ""
        mark = " •" if self.dirty else ""
        self.title(f"{APP_TITLE} {__version__} — {name}{file_part}{mark}")

    # ---------------- autoguardado ----------------
    def _offer_autosave_recovery(self) -> None:
        if not os.path.isfile(self.autosave_path):
            return
        try:
            recovered = Project.load(self.autosave_path)
        except Exception:
            # autoguardado corrupto/ilegible: lo ignoramos en vez de fallar al abrir la app
            logger.exception("No se pudo leer el autoguardado %s", self.autosave_path)
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Se encontró una copia de autoguardado de una sesión anterior que no se guardó "
            "(cierre inesperado o crash). ¿Recuperar ese proyecto ahora?",
        ):
            self._discard_autosave()
            return
        self.project = recovered
        self.current_path = None  # se recupera el contenido, pero se debe elegir donde guardarlo
        self._load_into_ui()
        self._clean_json = ""  # lo recuperado no esta guardado en ningun archivo
        self._update_dirty_state()

    def _autosave_tick(self) -> None:
        self._report_autosave_errors()
        if self.busy:
            self._autosave()
        elif self._update_dirty_state() and time.monotonic() - self._last_autosave >= AUTOSAVE_IDLE_SECONDS:
            self._autosave()
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    def _autosave(self) -> None:
        """
        Guarda el estado actual en self.autosave_path (separado del archivo
        que el usuario guarda explicitamente). El proyecto se serializa aqui,
        en el hilo principal (una foto consistente), y se ESCRIBE en un hilo
        aparte: una escritura lenta (disco de red, OneDrive) ya no congela la
        interfaz. Un contador de generaciones garantiza que una escritura
        vieja que termina tarde nunca pisa una mas nueva. Un error se
        registra y se avisa UNA sola vez por sesion.
        """
        try:
            self._sync_all()
            data = self._current_json()
        except Exception as exc:  # noqa: BLE001
            logger.exception("No se pudo preparar el autoguardado")
            self._autosave_errors.append(exc)
            self._report_autosave_errors()
            return
        self._autosave_gen += 1
        gen = self._autosave_gen
        path = self.autosave_path
        self._last_autosave = time.monotonic()

        def write() -> None:
            with self._autosave_lock:
                if gen <= self._autosave_written_gen or gen <= self._autosave_discarded_gen:
                    return  # ya se escribio algo mas nuevo, o se descarto
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    save_json_text(path, data)
                    self._autosave_written_gen = gen
                except Exception as exc:  # noqa: BLE001
                    logger.exception("No se pudo escribir el autoguardado en %s", path)
                    self._autosave_errors.append(exc)

        threading.Thread(target=write, daemon=True).start()
        self._report_autosave_errors()

    def _report_autosave_errors(self) -> None:
        if not self._autosave_errors:
            return
        exc = self._autosave_errors[-1]
        self._autosave_errors.clear()
        if getattr(self, "_autosave_error_reported", False):
            return
        self._autosave_error_reported = True
        messagebox.showwarning(
            APP_TITLE,
            f"No se pudo escribir el autoguardado en:\n{self.autosave_path}\n\n{exc}\n\n"
            "La app sigue normalmente, pero guarda el proyecto a mano de vez en cuando. "
            "(Este aviso no se repite en esta sesión.)",
        )

    def _discard_autosave(self) -> None:
        # Espera a que termine una escritura en curso y anula las pendientes.
        with self._autosave_lock:
            self._autosave_discarded_gen = self._autosave_gen
            for path in (self.autosave_path, self.autosave_path + ".bak"):
                try:
                    os.remove(path)
                except OSError:
                    pass

    # ---------------- sincronizacion general ----------------
    def _sync_all(self) -> None:
        if not hasattr(self, "chapters_scroll"):
            return  # todavia construyendo la ventana
        self.project.plot = self.plot_box.get()
        self.project.characters = self.characters_box.get()
        self.project.setting = self.setting_box.get()
        self.project.name = self.story_title_entry.get().strip() or DEFAULT_PROJECT_NAME
        self.project.author = self.author_entry.get().strip()
        self.project.author_note = self.project_note_entry.get().strip()
        heading_label = self.heading_menu.get()
        self.project.chapter_heading = next(
            (k for k, v in CHAPTER_HEADING_LABELS.items() if v == heading_label), "Chapter")
        self.project.writing_style = style_key(self.writing_style_menu.get())
        self._sync_sampling()
        for panel in self.outline_panels:
            panel.sync_to_model()
        for panel in self.chapter_panels:
            panel.sync_to_model()
        self._sync_lore_panels()

    def _load_into_ui(self, keep_selection: bool = False) -> None:
        self.plot_box.set(self.project.plot)
        self.characters_box.set(self.project.characters)
        self.setting_box.set(self.project.setting)
        self._load_project_meta_into_ui()
        self._load_sampling_into_ui()
        self.outline_count_entry.delete(0, "end")
        self.outline_count_entry.insert(0, str(len(self.project.chapters) or MAX_CHAPTERS))
        self.writing_style_menu.set(style_label(
            self.project.writing_style if self.project.writing_style in WRITING_STYLES else ""))
        if not keep_selection:
            # Los matches de la "ultima generacion" pertenecen al proyecto que se
            # acaba de dejar atras.
            self.last_lore_match_ids = set()
            self.last_lore_reasons = {}
            self._outline_requested = None
            self.lore_search_entry.delete(0, "end")
            self.selected_chapter_index = 0
        self._clear_lore_panels()
        self._render_lore_entries()
        self._render_outline_panels()
        self._render_chapters()
        self._refresh_complete_outline_btn()
        self._update_title()

    # ---------------- acciones de archivo ----------------
    def _confirm_discard_changes(self, action: str) -> bool:
        if not self.is_dirty():
            return True
        choice = messagebox.askyesnocancel(
            APP_TITLE, f"Hay cambios sin guardar. ¿Guardarlos antes de {action}?",
        )
        if choice is None:
            return False
        if choice:
            return self.save_project()
        return True

    def new_project(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, "Hay una generación en curso. Espera a que termine antes de cambiar de proyecto."
            )
            return
        if not self._confirm_discard_changes("crear un proyecto nuevo"):
            return
        self.project = Project()
        self.current_path = None
        self._load_into_ui()
        self._mark_clean()

    def open_project(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, "Hay una generación en curso. Espera a que termine antes de cambiar de proyecto."
            )
            return
        if not self._confirm_discard_changes("abrir otro proyecto"):
            return
        path = filedialog.askopenfilename(
            title="Abrir proyecto",
            filetypes=[("Proyecto StoryForge", "*.storyforge.json *.json"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return
        self.open_project_path(path)

    def open_project_path(self, path: str) -> bool:
        try:
            project = Project.load(path)
            from_backup = False
        except Exception as exc:  # noqa: BLE001
            logger.exception("No se pudo abrir el proyecto %s", path)
            backup = path + ".bak"
            if not os.path.isfile(backup) or not messagebox.askyesno(
                APP_TITLE,
                f"No se pudo abrir el proyecto:\n{exc}\n\nHay una copia de seguridad de la versión "
                f"anterior ({os.path.basename(backup)}). ¿Abrir esa copia?",
            ):
                messagebox.showerror(APP_TITLE, f"No se pudo abrir el proyecto: {exc}")
                return False
            try:
                project = Project.load(backup)
                from_backup = True
            except Exception as exc2:  # noqa: BLE001
                messagebox.showerror(APP_TITLE, f"Tampoco se pudo abrir la copia de seguridad: {exc2}")
                return False
        self.project = project
        # La copia .bak se abre sin destino: "Guardar" pregunta donde, para
        # no pisar el archivo danado sin querer.
        self.current_path = None if from_backup else path
        self._load_into_ui()
        self._mark_clean()
        if from_backup:
            self._clean_json = ""
            self._update_dirty_state()
            messagebox.showinfo(APP_TITLE, "Se abrió la copia de seguridad. Guárdala con \"Guardar proyecto como\".")
        self._restore_project_model()
        return True

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno(
            APP_TITLE,
            "Hay una generación en curso. Si sales ahora se perderá el progreso no guardado "
            "de ese capítulo/esquema. ¿Salir de todas formas?",
        ):
            return
        if self.is_dirty():
            choice = messagebox.askyesnocancel(APP_TITLE, "¿Guardar el proyecto antes de salir?")
            if choice is None:  # Cancelar: no salir
                return
            if choice:  # Si: guardar (si se cancela o falla, no salimos)
                if not self.save_project():
                    return
        # Sin cambios, guardado, o descartado a proposito: no ofrecer
        # "recuperar" en el proximo arranque.
        self._discard_autosave()
        self.destroy()

    def save_project(self) -> bool:
        """Devuelve True si el proyecto quedo guardado (False si se cancelo o fallo)."""
        if not self.current_path:
            return self.save_project_as()
        return self._save_to(self.current_path)

    def save_project_as(self) -> bool:
        self._sync_all()
        suggested = "".join(c for c in self.project.name if c not in '\\/:*?"<>|').strip() or "historia"
        path = filedialog.asksaveasfilename(
            title="Guardar proyecto como", defaultextension=".storyforge.json",
            initialfile=f"{suggested}.storyforge.json",
            filetypes=[("Proyecto StoryForge", "*.storyforge.json *.json")],
        )
        if not path:
            return False
        return self._save_to(path)

    def _save_to(self, path: str) -> bool:
        self._sync_all()
        problems = self.project.validate_inputs() + self.project.validate_warnings()
        if problems:
            messagebox.showwarning(APP_TITLE, "Se guardará con estas advertencias:\n\n" + "\n".join(problems))
        try:
            self.project.save(path)
        except Exception as exc:  # noqa: BLE001
            # Project.save() es atomico: el archivo anterior (si existia) sigue intacto.
            logger.exception("No se pudo guardar el proyecto en %s", path)
            messagebox.showerror(APP_TITLE, f"No se pudo guardar el proyecto en:\n{path}\n\n{exc}")
            return False
        self.current_path = path
        # La copia de autoguardado quedaria obsoleta.
        self._discard_autosave()
        self._mark_clean()
        messagebox.showinfo(APP_TITLE, "Proyecto guardado.")
        return True

    def _export(self, title: str, extension: str, label: str, exporter) -> None:
        self._sync_all()
        suggested = "".join(c for c in self.project.name if c not in '\\/:*?"<>|').strip() or "historia"
        path = filedialog.asksaveasfilename(
            title=title, defaultextension=extension, initialfile=f"{suggested}{extension}",
            filetypes=[(label, f"*{extension}")],
        )
        if not path:
            return
        try:
            exporter(self.project, path)
            messagebox.showinfo(APP_TITLE, f"Exportado a {path}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error al exportar a %s", path)
            messagebox.showerror(APP_TITLE, f"Error al exportar: {exc}")

    def export_word(self) -> None:
        self._export("Exportar a Word", ".docx", "Word", export_docx)

    def export_txt_file(self) -> None:
        self._export("Exportar a TXT", ".txt", "Texto", export_txt)

    def export_markdown_file(self) -> None:
        self._export("Exportar a Markdown", ".md", "Markdown", export_markdown)

    def export_epub_file(self) -> None:
        self._export("Exportar a EPUB", ".epub", "EPUB", export_epub)


def run() -> None:
    app = StoryForgeApp()
    # Errores no capturados en hilos de trabajo: se registran y se muestran.
    threading.excepthook = app._thread_excepthook
    app.mainloop()


# Nombres que las pruebas importan desde app.gui.
__all__ = [
    "StoryForgeApp", "run", "VersionHistoryDialog", "default_autosave_path", "_lore_entry_matches_search",
    "CHAPTER_PURPOSE_DEFAULT_LABEL", "WRITING_STYLE_DEFAULT_LABEL", "ContextOverflowError", "ModelNotLoadedError",
]
