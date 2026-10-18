"""
Pestanas Plot, Personajes y Setting, y las acciones de sus campos
(importar desde archivo, expandir con IA).
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from . import story_settings
from . import strings_es as S
from .error_text import describe_exception
from .project import (
    CHAPTER_HEADING_CHOICES,
    DEFAULT_PROJECT_NAME,
    MAX_AUTHOR_NOTE_WORDS,
    MAX_CHARACTERS_WORDS,
    MAX_PLOT_WORDS,
    HISTORY_LIMIT_RANGE,
    MAX_SETTING_WORDS,
    WRITING_STYLES,
    count_words,
)
from .strings_es import CHAPTER_HEADING_LABELS, style_key, style_label
from .task_runner import call_supported
from .ui_common import (
    APP_TITLE,
    LimitedTextBox,
)
from .ui_dialogs import COLOR_MUTED
from .ui_focus import apply_tab_order

#: Opciones del menu "Versiones guardadas por capitulo" (Project.history_limit).
HISTORY_LIMIT_CHOICES = ("5", "10", "20", "50", "100")


class StoryTabsMixin:
    """Pestanas Plot / Personajes / Setting de StoryForgeApp."""

    # ---------------- Plot / Personajes / Setting ----------------
    def _build_plot_tab(self) -> None:
        tab = self.tab_plot
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)
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
        # Project.history_limit (antes solo editable a mano en el archivo del proyecto).
        ctk.CTkLabel(note_row, text=S.VERSIONES_POR_CAPITULO).grid(row=0, column=2, padx=(12, 6))
        self.history_limit_menu = ctk.CTkOptionMenu(note_row, values=list(HISTORY_LIMIT_CHOICES), width=80)
        self.history_limit_menu.grid(row=0, column=3)
        self.plot_box = LimitedTextBox(
            tab, S.STORY_PLOT_IDEA_DE_LA, MAX_PLOT_WORDS, height=460,
            on_expand=lambda: self._expand_field(self.plot_box, "plot", S.TAB_PLOT, MAX_PLOT_WORDS),
            on_import=lambda: self._import_field(self.plot_box),
        )
        self.plot_box.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        self._build_story_settings_row(tab)
        apply_tab_order(
            tab,
            self.story_title_entry, self.author_entry, self.heading_menu, self.project_note_entry,
            self.history_limit_menu, *self.story_setting_widgets(), self.preset_menu, self.apply_preset_btn,
            self.save_preset_btn, self.delete_preset_btn, self.plot_box.focus_order_widgets(),
        )
        self._load_project_meta_into_ui()

    # ---- ajustes de la historia y presets (app/story_settings.py) ----
    def _build_story_settings_row(self, tab) -> None:
        box = ctk.CTkFrame(tab)
        box.grid(row=2, column=0, sticky="ew", padx=10, pady=(8, 0))
        for column in (1, 3, 5, 7):
            box.grid_columnconfigure(column, weight=1)
        self.story_setting_boxes = {}
        fields = (
            ("genre", S.GENERO), ("theme", S.TEMA), ("tone", S.TONO), ("point_of_view", S.PUNTO_DE_VISTA),
        )
        for i, (field, label) in enumerate(fields):
            ctk.CTkLabel(box, text=label).grid(row=0, column=2 * i, padx=(8, 4), pady=6, sticky="e")
            combo = ctk.CTkComboBox(box, values=list(story_settings.SUGGESTIONS[field]), width=150)
            combo.set("")
            combo.grid(row=0, column=2 * i + 1, padx=(0, 4), pady=6, sticky="ew")
            self.story_setting_boxes[field] = combo
        presets = ctk.CTkFrame(box, fg_color="transparent")
        presets.grid(row=1, column=0, columnspan=8, sticky="ew", padx=4, pady=(0, 6))
        ctk.CTkLabel(presets, text=S.DIALOGO_EQUILIBRIO).pack(side="left", padx=(4, 4))
        self.dialogue_menu = ctk.CTkOptionMenu(presets, values=list(S.DIALOGUE_LABELS.values()), width=170)
        self.dialogue_menu.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(presets, text=S.PRESET).pack(side="left", padx=(0, 4))
        self.preset_menu = ctk.CTkOptionMenu(presets, values=self._preset_names() or [""], width=170)
        self.preset_menu.pack(side="left", padx=(0, 4))
        self.apply_preset_btn = ctk.CTkButton(presets, text=S.APLICAR_PRESET, width=70, command=self.apply_selected_preset)
        self.apply_preset_btn.pack(side="left", padx=2)
        self.save_preset_btn = ctk.CTkButton(presets, text=S.GUARDAR_PRESET, width=110, command=self.save_story_preset)
        self.save_preset_btn.pack(side="left", padx=2)
        self.delete_preset_btn = ctk.CTkButton(presets, text=S.BORRAR_PRESET, width=70, command=self.delete_story_preset)
        self.delete_preset_btn.pack(side="left", padx=2)
        self.preset_status = ctk.CTkLabel(presets, text="", text_color=COLOR_MUTED)
        self.preset_status.pack(side="left", padx=(8, 0))
        # Frases a evitar (app/phrase_guard.py, B15).
        cliches = ctk.CTkFrame(box, fg_color="transparent")
        cliches.grid(row=2, column=0, columnspan=8, sticky="ew", padx=4, pady=(0, 6))
        self.avoid_cliches_var = ctk.BooleanVar(value=True)
        self.avoid_cliches_check = ctk.CTkCheckBox(cliches, text=S.EVITAR_CLICHES, variable=self.avoid_cliches_var,
                                                   command=self._on_avoid_cliches_changed)
        self.avoid_cliches_check.pack(side="left", padx=(4, 8))
        self.banned_phrases_btn = ctk.CTkButton(cliches, text=S.FRASES_A_EVITAR, width=130,
                                                command=self.edit_banned_phrases)
        self.banned_phrases_btn.pack(side="left", padx=2)
        self.banned_phrases_status = ctk.CTkLabel(cliches, text=S.EVITAR_CLICHES_AYUDA, text_color=COLOR_MUTED,
                                                  justify="left", wraplength=620)
        self.banned_phrases_status.pack(side="left", padx=(8, 0))
        # Pasajes anteriores relevantes (app/retrieval.py, B16).
        recall = ctk.CTkFrame(box, fg_color="transparent")
        recall.grid(row=3, column=0, columnspan=8, sticky="ew", padx=4, pady=(0, 6))
        self.recall_passages_var = ctk.BooleanVar(value=False)
        self.recall_passages_check = ctk.CTkCheckBox(recall, text=S.RECORDAR_PASAJES,
                                                     variable=self.recall_passages_var,
                                                     command=self._on_recall_passages_changed)
        self.recall_passages_check.pack(side="left", padx=(4, 8))
        self.embedding_model_btn = ctk.CTkButton(recall, text=S.MODELO_DE_EMBEDDINGS, width=150,
                                                 command=self.choose_embedding_model)
        self.embedding_model_btn.pack(side="left", padx=2)
        self.embedding_status = ctk.CTkLabel(recall, text=S.EMBEDDINGS_BM25, text_color=COLOR_MUTED)
        self.embedding_status.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(recall, text=S.RECORDAR_PASAJES_AYUDA, text_color=COLOR_MUTED, justify="left",
                     wraplength=520).pack(side="left", padx=(8, 0))

    def _on_recall_passages_changed(self) -> None:
        self.project.recall_passages = bool(self.recall_passages_var.get())
        self.schedule_dirty_check()

    def load_embedding_model(self, path: str, remember: bool = True) -> None:
        """Carga el GGUF de embeddings en segundo plano (CPU) y lo activa para la busqueda."""
        import os
        import threading

        from . import retrieval
        from .settings import set_embedding_model

        name = os.path.basename(path)
        self.embedding_status.configure(text=S.EMBEDDINGS_CARGANDO.format(name=name))

        def work() -> None:
            try:
                embedder = retrieval.GGUFEmbedder(path)
            except Exception as exc:  # noqa: BLE001 - se informa
                self.after(0, lambda e=exc: (self.embedding_status.configure(text=S.EMBEDDINGS_BM25),
                                             messagebox.showerror(APP_TITLE, S.EMBEDDINGS_ERROR.format(exc=e))))
                return
            retrieval.set_embedder(embedder)
            if remember:
                set_embedding_model(path)
            self.after(0, lambda: self.embedding_status.configure(text=S.EMBEDDINGS_ACTIVO.format(name=name)))

        threading.Thread(target=work, daemon=True).start()

    def choose_embedding_model(self) -> None:
        from tkinter import filedialog

        from . import retrieval
        from .settings import set_embedding_model

        if retrieval.embedder_active() and messagebox.askyesno(APP_TITLE, S.EMBEDDINGS_QUITAR):
            retrieval.set_embedder(None)
            set_embedding_model("")
            self.embedding_status.configure(text=S.EMBEDDINGS_BM25)
            return
        path = filedialog.askopenfilename(title=S.EMBEDDINGS_TITULO, filetypes=[(S.GGUF, "*.gguf")])
        if path:
            self.load_embedding_model(path)

    def story_setting_widgets(self) -> list:
        return [*self.story_setting_boxes.values(), self.dialogue_menu]

    def _on_avoid_cliches_changed(self) -> None:
        self.project.avoid_cliches = bool(self.avoid_cliches_var.get())
        self.schedule_dirty_check()

    def edit_banned_phrases(self) -> None:
        from .phrase_guard import DEFAULT_BANNED_PHRASES
        from .ui_dialogs import PhraseListDialog

        def save(phrases):
            self.project.banned_phrases = phrases
            self.banned_phrases_status.configure(text=S.FRASES_GUARDADAS.format(count=len(phrases)))
            self.schedule_dirty_check()

        self.banned_phrases_dialog = PhraseListDialog(self, self.project.banned_phrases, DEFAULT_BANNED_PHRASES, save)

    @staticmethod
    def _preset_names() -> list:
        return list(story_settings.all_presets())

    def _refresh_preset_menu(self, select: str = "") -> None:
        names = self._preset_names()
        self.preset_menu.configure(values=names or [""])
        self.preset_menu.set(select if select in names else (names[0] if names else ""))

    def _load_story_settings_into_ui(self) -> None:
        for field, combo in self.story_setting_boxes.items():
            combo.set(getattr(self.project, field, ""))
        self.dialogue_menu.set(story_settings.dialogue_label(self.project.dialogue_balance))
        self.avoid_cliches_var.set(bool(self.project.avoid_cliches))
        self.recall_passages_var.set(bool(self.project.recall_passages))

    def sync_story_settings(self) -> None:
        for field, combo in self.story_setting_boxes.items():
            setattr(self.project, field, combo.get().strip()[: story_settings.MAX_SETTING_CHARS])
        self.project.dialogue_balance = story_settings.dialogue_key(self.dialogue_menu.get())
        self.project.avoid_cliches = bool(self.avoid_cliches_var.get())
        self.project.recall_passages = bool(self.recall_passages_var.get())

    def apply_selected_preset(self, name: str = "") -> bool:
        name = name or self.preset_menu.get()
        preset = story_settings.all_presets().get(name)
        if preset is None:
            return False
        story_settings.apply_preset(self.project, preset)
        self.preset_menu.set(name)
        self._load_story_settings_into_ui()
        self.writing_style_menu.set(style_label(
            self.project.writing_style if self.project.writing_style in WRITING_STYLES else ""))
        self.preset_status.configure(text=S.PRESET_APLICADO.format(name=name))
        self.schedule_dirty_check()
        return True

    def save_story_preset(self, name: Optional[str] = None) -> Optional[str]:
        if name is None:
            dialog = ctk.CTkInputDialog(text=S.NOMBRE_DEL_PRESET, title=S.AJUSTES_DE_LA_HISTORIA)
            name = (dialog.get_input() or "").strip()
            if not name:
                return None
        self.sync_story_settings()
        self.project.writing_style = style_key(self.writing_style_menu.get())
        try:
            saved = story_settings.save_user_preset(name, story_settings.preset_from_project(self.project))
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return None
        self._refresh_preset_menu(saved)
        self.preset_status.configure(text=S.PRESET_GUARDADO.format(name=saved))
        return saved

    def delete_story_preset(self) -> bool:
        name = self.preset_menu.get()
        if not story_settings.delete_user_preset(name):
            self.preset_status.configure(text=S.PRESET_INCORPORADO_NO_SE_BORRA)
            return False
        self._refresh_preset_menu()
        self.preset_status.configure(text=S.PRESET_BORRADO.format(name=name))
        return True

    def _load_project_meta_into_ui(self) -> None:
        self._set_entry(self.story_title_entry, self.project.name if self.project.name != DEFAULT_PROJECT_NAME else "")
        self._set_entry(self.author_entry, self.project.author)
        self._set_entry(self.project_note_entry, self.project.author_note)
        heading = self.project.chapter_heading if self.project.chapter_heading in CHAPTER_HEADING_LABELS else "Chapter"
        self.heading_menu.set(CHAPTER_HEADING_LABELS[heading])
        # Un valor del archivo que no esta en la lista (cualquiera entre 1 y 100) se agrega a ella.
        limit = str(self.project.history_limit)
        if limit not in HISTORY_LIMIT_CHOICES:
            self.history_limit_menu.configure(values=sorted({*HISTORY_LIMIT_CHOICES, limit}, key=int))
        self.history_limit_menu.set(limit)
        self._load_story_settings_into_ui()

    def _history_limit_from_ui(self) -> int:
        lo, hi = HISTORY_LIMIT_RANGE
        try:
            return max(lo, min(int(self.history_limit_menu.get()), hi))
        except ValueError:
            return self.project.history_limit

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
        apply_tab_order(self.tab_characters, self.characters_box.focus_order_widgets())

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
        apply_tab_order(self.tab_setting, self.setting_box.focus_order_widgets())

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
            messagebox.showerror(APP_TITLE, S.NO_SE_PUDO_LEER_ARCHIVO.format(exc=describe_exception(exc)))
            return
        if box.get().strip() and not messagebox.askyesno(
            APP_TITLE, S.ESTO_REEMPLAZARA_EL_CONTENIDO_ACTUAL
        ):
            return
        box.set(text, undoable=True)  # Ctrl+Z vuelve al texto anterior, como "Expandir con IA"
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
