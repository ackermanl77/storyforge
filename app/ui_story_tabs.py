"""
Pestanas Plot, Personajes y Setting, y las acciones de sus campos
(importar desde archivo, expandir con IA).
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import strings_es as S
from .project import (
    CHAPTER_HEADING_CHOICES,
    DEFAULT_PROJECT_NAME,
    MAX_AUTHOR_NOTE_WORDS,
    MAX_CHARACTERS_WORDS,
    MAX_PLOT_WORDS,
    MAX_SETTING_WORDS,
    count_words,
)
from .strings_es import CHAPTER_HEADING_LABELS
from .task_runner import call_supported
from .ui_common import (
    APP_TITLE,
    LimitedTextBox,
)


class StoryTabsMixin:
    """Pestanas Plot / Personajes / Setting de StoryForgeApp."""

    # ---------------- Plot / Personajes / Setting ----------------
    def _build_plot_tab(self) -> None:
        tab = self.tab_plot
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        meta = ctk.CTkFrame(tab, fg_color="transparent")
        meta.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        meta.grid_columnconfigure(1, weight=2)
        meta.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(meta, text=S.TITULO_DE_LA_HISTORIA).grid(row=0, column=0, padx=(0, 6))
        self.story_title_entry = ctk.CTkEntry(meta, placeholder_text=DEFAULT_PROJECT_NAME)
        self.story_title_entry.grid(row=0, column=1, sticky="ew")
        self.story_title_entry.bind("<KeyRelease>", lambda _e: self._update_title())
        ctk.CTkLabel(meta, text=S.AUTOR).grid(row=0, column=2, padx=(12, 6))
        self.author_entry = ctk.CTkEntry(meta)
        self.author_entry.grid(row=0, column=3, sticky="ew")
        ctk.CTkLabel(meta, text=S.ENCABEZADO_AL_EXPORTAR).grid(row=0, column=4, padx=(12, 6))
        self.heading_menu = ctk.CTkOptionMenu(meta, values=[CHAPTER_HEADING_LABELS[k] for k in CHAPTER_HEADING_CHOICES], width=170)
        self.heading_menu.grid(row=0, column=5)
        note_row = ctk.CTkFrame(tab, fg_color="transparent")
        note_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 0))
        note_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(note_row, text=S.NOTA_DEL_AUTOR_TODA_LA).grid(row=0, column=0, padx=(0, 6))
        self.project_note_entry = ctk.CTkEntry(
            note_row, placeholder_text=S.INSTRUCCION_CORTA_QUE_SE_APLICA.format(MAX_AUTHOR_NOTE_WORDS=MAX_AUTHOR_NOTE_WORDS),
        )
        self.project_note_entry.grid(row=0, column=1, sticky="ew")
        self.plot_box = LimitedTextBox(
            tab, S.STORY_PLOT_IDEA_DE_LA, MAX_PLOT_WORDS, height=460,
            on_expand=lambda: self._expand_field(self.plot_box, "plot", S.TAB_PLOT, MAX_PLOT_WORDS),
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
            self.tab_characters, S.PERSONAJES_DESCRIPCION_PERSONALIDAD_RELACIONES,
            MAX_CHARACTERS_WORDS, height=500,
            on_expand=lambda: self._expand_field(
                self.characters_box, "characters", S.TAB_PERSONAJES, MAX_CHARACTERS_WORDS
            ),
            on_import=lambda: self._import_field(self.characters_box),
        )
        self.characters_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def _build_setting_tab(self) -> None:
        self.tab_setting.grid_columnconfigure(0, weight=1)
        self.tab_setting.grid_rowconfigure(0, weight=1)
        self.setting_box = LimitedTextBox(
            self.tab_setting, S.SETTING_DONDE_Y_CUANDO_OCURRE,
            MAX_SETTING_WORDS, height=500,
            on_expand=lambda: self._expand_field(self.setting_box, "setting", S.TAB_SETTING, MAX_SETTING_WORDS),
            on_import=lambda: self._import_field(self.setting_box),
        )
        self.setting_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def _import_field(self, box: LimitedTextBox) -> None:
        """Reemplaza el contenido de `box` con el texto de un archivo elegido
        por el usuario. Sincrono, no toca el motor."""
        path = filedialog.askopenfilename(
            title=S.IMPORTAR_TEXTO_DESDE_ARCHIVO,
            filetypes=[(S.TIPO_TEXTO, "*.txt"), (S.TODOS_LOS_ARCHIVOS, "*.*")],
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, S.NO_SE_PUDO_LEER_ARCHIVO.format(exc=exc))
            return
        if box.get().strip() and not messagebox.askyesno(
            APP_TITLE, S.ESTO_REEMPLAZARA_EL_CONTENIDO_ACTUAL
        ):
            return
        box.set(text)
        self.schedule_dirty_check()

    def _expand_field(self, box: LimitedTextBox, field_key: str, field_label: str, max_words: int) -> None:
        """Reemplaza la nota corta de `box` por una version mas desarrollada
        (LocalStoryEngine.expand_field()); Ctrl+Z vuelve a la nota."""
        if not self.engine.is_loaded:
            messagebox.showwarning(APP_TITLE, S.PRIMERO_CARGA_UN_MODELO_LOCAL)
            return
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, S.YA_HAY_GENERACION_EN_CURSO
            )
            return
        text = box.get().strip()
        if not text:
            messagebox.showwarning(APP_TITLE, S.ESCRIBE_UNA_IDEA_CORTA_EN.format(field_label=field_label))
            return
        if count_words(text) > 60 and not messagebox.askyesno(
            APP_TITLE,
            S.YA_TIENE_BASTANTE_TEXTO_ESCRITO.format(field_label=field_label),
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

        self.task_runner.run(S.EXPANDIR.format(field_label=field_label), work, on_success=on_success,
                             error_prefix=S.ERROR_EXPANDIENDO_EL_CAMPO)
