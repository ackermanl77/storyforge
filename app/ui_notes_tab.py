"""
Pestana Notas (F19): apuntes del proyecto. Cada nota tiene titulo, texto y
"Incluir en el prompt" (se envia con cada capitulo, ver
prompts.build_snippets_block); las demas son solo para el autor.
"""
from __future__ import annotations

from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from . import strings_es as S
from .project import MAX_SNIPPETS, Snippet
from .ui_common import APP_TITLE, UNDO_TEXTBOX_OPTIONS
from .ui_dialogs import COLOR_MUTED
from .ui_focus import apply_tab_order

if TYPE_CHECKING:
    from .gui import StoryForgeApp


class SnippetPanel(ctk.CTkFrame):
    def __init__(self, master, app: "StoryForgeApp", index: int, snippet: Snippet, **kwargs):
        super().__init__(master, border_width=1, corner_radius=8, **kwargs)
        self.app, self.index, self.snippet = app, index, snippet
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text=S.TITULO_ETIQUETA).grid(row=0, column=0, padx=8, pady=(8, 2), sticky="w")
        self.title_entry = ctk.CTkEntry(self)
        self.title_entry.insert(0, snippet.title)
        self.title_entry.grid(row=0, column=1, padx=8, pady=(8, 2), sticky="ew")
        self.in_prompt_var = ctk.BooleanVar(value=snippet.in_prompt)
        self.in_prompt_check = ctk.CTkCheckBox(self, text=S.INCLUIR_EN_EL_PROMPT, variable=self.in_prompt_var,
                                               command=self.app.schedule_dirty_check)
        self.in_prompt_check.grid(row=0, column=2, padx=8, pady=(8, 2))
        self.remove_btn = ctk.CTkButton(self, text=S.ELIMINAR, width=90, fg_color="#8a3b3b", hover_color="#6e2f2f",
                                        command=self._on_remove)
        self.remove_btn.grid(row=0, column=3, padx=8, pady=(8, 2))
        self.text_box = ctk.CTkTextbox(self, height=110, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.text_box.insert("1.0", snippet.text)
        self.text_box.edit_reset()
        self.text_box.grid(row=1, column=0, columnspan=4, padx=8, pady=(2, 8), sticky="ew")
        apply_tab_order(self, self.focus_order_widgets())

    def sync_to_model(self) -> None:
        self.snippet.title = self.title_entry.get().strip()
        self.snippet.text = self.text_box.get("1.0", "end-1c")
        self.snippet.in_prompt = bool(self.in_prompt_var.get())

    def _on_remove(self) -> None:
        label = self.title_entry.get().strip() or S.NOTA_SIN_TITULO.format(number=self.index + 1)
        if messagebox.askyesno(APP_TITLE, S.ELIMINAR_LA_NOTA.format(label=label)):
            self.app.remove_snippet(self.index)

    def focus_order_widgets(self):
        return [self.title_entry, self.in_prompt_check, self.remove_btn, self.text_box]


class NotesTabMixin:
    """Pestana Notas de StoryForgeApp."""

    def _build_notes_tab(self) -> None:
        tab = self.tab_notes
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(tab, text=S.NOTAS_EXPLICACION, wraplength=900, justify="left").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        self.add_snippet_btn = ctk.CTkButton(top, text=S.AGREGAR_NOTA, command=self.add_snippet)
        self.add_snippet_btn.pack(side="left")
        self.notes_scroll = ctk.CTkScrollableFrame(tab)
        self.notes_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.notes_scroll.grid_columnconfigure(0, weight=1)
        self._notes_placeholder = ctk.CTkLabel(self.notes_scroll, text=S.AUN_NO_HAY_NOTAS, text_color=COLOR_MUTED)
        self.snippet_panels = []
        self._render_snippets()

    def _sync_snippet_panels(self) -> None:
        for panel in getattr(self, "snippet_panels", []):
            panel.sync_to_model()

    def _render_snippets(self) -> None:
        for panel in getattr(self, "snippet_panels", []):
            panel.destroy()
        self.snippet_panels = []
        for i, snippet in enumerate(self.project.snippets):
            panel = SnippetPanel(self.notes_scroll, self, i, snippet)
            panel.grid(row=i, column=0, sticky="ew", pady=6)
            self.snippet_panels.append(panel)
        if self.project.snippets:
            self._notes_placeholder.grid_remove()
        else:
            self._notes_placeholder.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.add_snippet_btn.configure(state="normal" if self.project.can_add_snippet() else "disabled")
        apply_tab_order(self.tab_notes, self.add_snippet_btn, [panel.focus_order_widgets() for panel in self.snippet_panels])

    def add_snippet(self) -> None:
        if not self.project.can_add_snippet():
            messagebox.showinfo(APP_TITLE, S.YA_HAY_NOTAS_EL_MAXIMO.format(maximum=MAX_SNIPPETS))
            return
        self._sync_snippet_panels()
        self.project.add_snippet()
        self._render_snippets()
        self.snippet_panels[-1].title_entry.focus_set()
        self.schedule_dirty_check()

    def remove_snippet(self, index: int) -> None:
        self._sync_snippet_panels()
        self.project.snippets.pop(index)
        self._render_snippets()
        self.schedule_dirty_check()
