"""
Pestana Capitulos: barra lateral, un ChapterPanel visible a la vez, modo
enfoque y buscar/reemplazar en todo el proyecto.
"""
from __future__ import annotations

from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from . import strings_es as S
from .project import (
    MAX_CHAPTERS,
    content_hash,
)
from .ui_chapter_editor import ChapterPanel
from .ui_common import (
    APP_TITLE,
    SELECTED_SIDEBAR_COLOR,
)
from .ui_dialogs import (
    COLOR_MUTED,
    ProjectSearchDialog,
    SearchHit,
    replace_in_text,
)
from .ui_focus import apply_tab_order


class ChaptersTabMixin:
    """Pestana Capitulos de StoryForgeApp."""

    # ---------------- Capitulos ----------------
    def _build_chapters_tab(self) -> None:
        tab = self.tab_chapters
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        self.chapters_top = ctk.CTkFrame(tab, fg_color="transparent")
        self.chapters_top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        self.add_chapter_btn = ctk.CTkButton(self.chapters_top, text=S.AGREGAR_CAPITULO, command=self.add_chapter)
        self.add_chapter_btn.pack(side="left")
        ctk.CTkLabel(self.chapters_top, text=S.MAXIMO_CAPITULOS.format(MAX_CHAPTERS=MAX_CHAPTERS)).pack(side="left", padx=8)
        self.focus_btn = ctk.CTkButton(self.chapters_top, text=S.MODO_ENFOQUE_F11, width=150,
                                       command=self.toggle_focus_mode)
        self.focus_btn.pack(side="right")

        # Lista de capitulos (numero, titulo, palabras/objetivo): elige cual
        # se muestra en el editor.
        self.chapter_sidebar = ctk.CTkScrollableFrame(tab, width=190, label_text=S.TAB_CAPITULOS)
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
            self.tabview.set(S.TAB_CAPITULOS)
            self.chapter_sidebar.grid_remove()
            self.focus_btn.configure(text=S.SALIR_DEL_MODO_ENFOQUE)
        else:
            self.chapter_sidebar.grid()
            self.focus_btn.configure(text=S.MODO_ENFOQUE_F11)
        for panel in self.chapter_panels:
            panel.set_focus_mode(self.focus_mode)

    def add_chapter(self) -> None:
        if not self.project.can_add_chapter():
            messagebox.showinfo(APP_TITLE, S.YA_HAY_CAPITULOS_EL_MAXIMO.format(MAX_CHAPTERS=MAX_CHAPTERS))
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
                text=S.AUN_NO_HAY_CAPITULOS_AGREGA,
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
        self.chapter_sidebar_buttons = []
        if not self.project.chapters:
            ctk.CTkLabel(self.chapter_sidebar, text=S.SIN_CAPITULOS, text_color=COLOR_MUTED).grid(
                row=0, column=0, sticky="w", padx=6, pady=6)
            self._refresh_word_totals()
            self._refresh_chapters_tab_focus_order()
            return
        for i, chapter in enumerate(self.project.chapters):
            title = chapter.title.strip() or S.CAPITULO_N.format(number=i + 1)
            words = chapter.word_count()
            label = S.CAPITULO_BARRA_LATERAL.format(number=i + 1, title=title, words=words,
                                                    target_words=chapter.target_words)
            selected = i == self.selected_chapter_index
            btn = ctk.CTkButton(
                self.chapter_sidebar, text=label, anchor="w",
                fg_color=(SELECTED_SIDEBAR_COLOR if selected else "transparent"),
                text_color=("#1a1a1a", "#e6e6e6"),
                hover_color=("#d0d0d0", "#2b2b2b"), command=lambda idx=i: self._jump_to_chapter(idx),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=4, pady=2)
            self.chapter_sidebar_buttons.append(btn)
        self._refresh_word_totals()
        self._refresh_chapters_tab_focus_order()

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

    def _refresh_chapters_tab_focus_order(self) -> None:
        apply_tab_order(
            self.tab_chapters,
            self.add_chapter_btn, self.focus_btn, getattr(self, "chapter_sidebar_buttons", []),
            [panel.focus_order_widgets() for panel in self.chapter_panels],
        )

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
        self.tabview.set(S.TAB_CAPITULOS)
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
            self.tabview.set(S.TAB_CAPITULOS)
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
            self.tabview.set(S.TAB_ESQUEMA)
        elif hit.field == "lore":
            self.tabview.set(S.TAB_LOREBOOK)
        else:
            self.tabview.set({"plot": S.TAB_PLOT, "characters": S.TAB_PERSONAJES, "setting": S.TAB_SETTING}[hit.field])

    def replace_in_project(self, query: str, replacement: str, case_sensitive: bool = False,
                           whole_word: bool = False) -> int:
        """Reemplazar en todo el proyecto. Cada capitulo cuyo texto cambia
        guarda antes una version ("Versiones anteriores")."""
        if self.busy:
            messagebox.showwarning(APP_TITLE, S.ESPERA_GENERACION_EN_CURSO)
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
