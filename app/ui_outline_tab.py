"""
Pestana Esquema: OutlinePanel (un capitulo del esquema) y
OutlineTabMixin (generar / completar el esquema y mostrarlo).
"""
from __future__ import annotations

from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from . import strings_es as S
from .project import (
    MAX_CHAPTERS,
    MAX_OUTLINE_WORDS_PER_CHAPTER,
    WRITING_STYLES,
    Chapter,
    count_words,
)
from .prompts import OutlineParseError
from .strings_es import style_label
from .task_runner import call_supported
from .ui_common import (
    APP_TITLE,
    UNDO_TEXTBOX_OPTIONS,
    WRITING_STYLE_OPTIONS,
)
from .ui_dialogs import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_WARN,
)


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
        title_text = chapter.title or S.CAPITULO_N.format(number=index + 1)
        ctk.CTkLabel(header, text=S.CAPITULO_N_TITULO.format(number=index + 1, title=title_text), font=ctk.CTkFont(weight="bold")).grid(
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
            text=S.CONTADOR_PALABRAS_ESQUEMA.format(words=words,
                                                    MAX_OUTLINE_WORDS_PER_CHAPTER=MAX_OUTLINE_WORDS_PER_CHAPTER),
            text_color=COLOR_ERROR if over else COLOR_MUTED,
        )

    def sync_to_model(self) -> None:
        self.chapter.outline = self.outline_box.get("1.0", "end-1c")


class OutlineTabMixin:
    """Pestana Esquema de StoryForgeApp."""

    # ---------------- Esquema ----------------
    def _build_outline_tab(self) -> None:
        tab = self.tab_outline
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                S.GENERA_PRIMERO_UN_ESQUEMA_BEAT
            ),
            wraplength=900, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(controls, text=S.NUMERO_DE_CAPITULOS).pack(side="left", padx=(0, 6))
        self.outline_count_entry = ctk.CTkEntry(controls, width=50)
        self.outline_count_entry.insert(0, str(len(self.project.chapters) or MAX_CHAPTERS))
        self.outline_count_entry.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(controls, text=S.TIPO_DE_ESCRITURA).pack(side="left", padx=(0, 6))
        self.writing_style_menu = ctk.CTkOptionMenu(controls, values=WRITING_STYLE_OPTIONS, width=160)
        self.writing_style_menu.set(style_label(self.project.writing_style if self.project.writing_style in WRITING_STYLES else ""))
        self.writing_style_menu.pack(side="left", padx=(0, 12))
        self.generate_outline_btn = ctk.CTkButton(
            controls, text=S.GENERAR_ESQUEMA_COMPLETO, command=self._on_generate_outline
        )
        self.generate_outline_btn.pack(side="left")
        self.complete_outline_btn = ctk.CTkButton(
            controls, text=S.COMPLETAR_CAPITULOS_FALTANTES, state="disabled", command=self._on_complete_outline,
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
            messagebox.showwarning(APP_TITLE, S.PRIMERO_CARGA_UN_MODELO_LOCAL)
            return False
        if self.busy:
            messagebox.showwarning(APP_TITLE, message_when_busy)
            return False
        self._sync_all()
        errors = self.project.validate_inputs()
        if errors:
            messagebox.showwarning(APP_TITLE, S.CORRIGE_ANTES_DE_GENERAR_EL + "\n".join(errors))
            return False
        return True

    def _on_generate_outline(self) -> None:
        if not self._outline_preconditions(
            S.YA_HAY_GENERACION_EN_CURSO_ESQUEMA
        ):
            return
        try:
            num_chapters = int(self.outline_count_entry.get())
        except ValueError:
            messagebox.showwarning(APP_TITLE, S.NUMERO_DE_CAPITULOS_INVALIDO)
            return
        num_chapters = max(1, min(num_chapters, MAX_CHAPTERS))

        if self.project.chapters and not messagebox.askyesno(
            APP_TITLE,
            S.ESTO_REEMPLAZARA_EL_TITULO_Y,
        ):
            return

        self.outline_status.configure(text=S.GENERANDO_ESQUEMA, text_color=COLOR_MUTED)
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
            S.TAB_ESQUEMA, work, on_success=on_success, on_error=self._outline_error,
            on_cancel=lambda: self.outline_status.configure(text=S.ESQUEMA_DETENIDO_NO_SE_CAMBIO,
                                                            text_color=COLOR_WARN),
            error_prefix=S.ERROR_GENERANDO_EL_ESQUEMA,
        )

    def _report_outline_state(self, have: int, wanted: int, truncated: bool) -> None:
        if have < wanted or truncated:
            cause = S.LA_RESPUESTA_DEL_MODELO_SE if truncated else ""
            self._outline_requested = wanted if have < wanted else None
            self.outline_status.configure(
                text=(S.ESQUEMA_INCOMPLETO_DE_CAPITULOS_USA.format(have=have, wanted=wanted, cause=cause)),
                text_color=COLOR_WARN,
            )
        else:
            self._outline_requested = None
            self.outline_status.configure(text=S.ESQUEMA_GENERADO_CAPITULOS.format(have=have), text_color=COLOR_OK)
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
        if not self._outline_preconditions(S.YA_HAY_GENERACION_EN_CURSO_CORTO):
            return
        existing = self._outlined_chapters()
        wanted = self._outline_requested
        engine = self.engine
        project = self.project
        self.outline_status.configure(text=S.COMPLETANDO_EL_ESQUEMA, text_color=COLOR_MUTED)

        def work(cancel_check):
            return call_supported(engine.complete_outline, project, wanted, existing, cancel_check=cancel_check)

        def on_success(new_items) -> None:
            combined = existing + list(new_items)
            self._apply_outline(combined)
            truncated = getattr(engine, "last_finish_reason", None) == "length"
            self._report_outline_state(len(combined), wanted, truncated and len(combined) < wanted)

        self.task_runner.run(S.COMPLETAR_ESQUEMA, work, on_success=on_success, on_error=self._outline_error,
                             error_prefix=S.ERROR_COMPLETANDO_EL_ESQUEMA)

    def _outline_error(self, exc) -> Optional[str]:
        if isinstance(exc, OutlineParseError):
            # Antes, una respuesta sin encabezados reconocibles se aplicaba
            # entera como esquema del capitulo 1.
            snippet = exc.raw_text.strip()
            if len(snippet) > 800:
                snippet = snippet[:800] + " [...]"
            self.after(0, lambda: self.outline_status.configure(text="", text_color=COLOR_MUTED))
            return (S.NO_SE_MODIFICO_EL_ESQUEMA.format(exc=exc, snippet=snippet))
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
                text=S.AUN_NO_HAY_CAPITULOS_GENERA,
                text_color=COLOR_MUTED, wraplength=800, justify="left",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return
        for i, chapter in enumerate(self.project.chapters):
            panel = OutlinePanel(self.outline_scroll, i, chapter)
            panel.grid(row=i, column=0, sticky="ew", pady=6)
            self.outline_panels.append(panel)
