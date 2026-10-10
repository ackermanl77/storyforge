"""
Editor de un capitulo (ChapterPanel: metadatos, acciones, editor,
buscar/reemplazar, refinamiento y resumen) y la ventana de versiones
anteriores (VersionHistoryDialog).
"""
from __future__ import annotations

import logging
import time
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING, List, Optional

import customtkinter as ctk

from . import strings_es as S
from .engine import OperationCancelled
from .project import (
    CHAPTER_PURPOSES,
    MAX_WORDS_PER_CHAPTER,
    Chapter,
    content_hash,
    count_words,
)
from .prompts import CUSTOM_PROMPT_TEMPLATE, REWRITE_MODE_LABELS
from .repetition import reduce_repetition, repetition_report
from .strings_es import (
    history_source_label,
    purpose_key,
    purpose_label,
)
from .task_runner import call_supported
from .ui_common import (
    APP_TITLE,
    CHAPTER_PURPOSE_OPTIONS,
    GENERATING_BORDER_COLOR,
    UNDO_TEXTBOX_OPTIONS,
    _append_text,
    _set_text_readonly_content,
)
from .ui_focus import apply_tab_order
from .ui_dialogs import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_WARN,
    DiffPreviewDialog,
    replace_in_text,
)

if TYPE_CHECKING:
    from .gui import StoryForgeApp

# Un solo registrador para toda la ventana principal ("app.gui"), como
# antes de dividir gui.py en modulos.
logger = logging.getLogger("app.gui")


# Intervalo minimo entre refrescos de pantalla durante el streaming token a
# token (la actualizacion final nunca pasa por este throttle).
CHAPTER_STREAM_UI_INTERVAL_SECONDS = 0.15


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
        # Las alternativas viven en el capitulo (Chapter.alternatives), asi se
        # guardan con el proyecto; ver las propiedades de abajo.
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=S.CAPITULO_N.format(number=index + 1), font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )
        self.title_entry = ctk.CTkEntry(self, placeholder_text=S.TITULO_DEL_CAPITULO)
        self.title_entry.insert(0, chapter.title)
        self.title_entry.grid(row=0, column=1, padx=8, pady=(8, 2), sticky="ew")
        ctk.CTkLabel(self, text=S.PALABRAS_OBJETIVO).grid(row=0, column=2, padx=(8, 2), sticky="e")
        self.target_entry = ctk.CTkEntry(self, width=80)
        self.target_entry.insert(0, str(chapter.target_words))
        self.target_entry.grid(row=0, column=3, padx=(0, 8), sticky="e")

        # Proposito narrativo + Nota del autor (F7) de este capitulo.
        purpose_row = ctk.CTkFrame(self, fg_color="transparent")
        purpose_row.grid(row=1, column=0, columnspan=4, sticky="ew", padx=8, pady=(2, 0))
        purpose_row.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(purpose_row, text=S.PROPOSITO).grid(row=0, column=0, padx=(0, 6))
        self.purpose_menu = ctk.CTkOptionMenu(purpose_row, values=CHAPTER_PURPOSE_OPTIONS, width=170)
        self.purpose_menu.set(purpose_label(chapter.purpose if chapter.purpose in CHAPTER_PURPOSES else ""))
        self.purpose_menu.grid(row=0, column=1)
        ctk.CTkLabel(purpose_row, text=S.NOTA_DEL_AUTOR).grid(row=0, column=2, padx=(14, 6))
        self.author_note_entry = ctk.CTkEntry(
            purpose_row,
            placeholder_text=S.INSTRUCCION_CORTA_QUE_EL_MODELO,
        )
        self.author_note_entry.insert(0, chapter.author_note)
        self.author_note_entry.grid(row=0, column=3, sticky="ew")

        # Prompt propio: reemplaza el prompt automatico de este capitulo
        # (prompts.build_custom_chapter_chat). Oculto hasta que se pide; el
        # boton lleva un punto mientras hay uno escrito.
        self.custom_prompt_btn = ctk.CTkButton(purpose_row, text=S.PROMPT_PROPIO, width=130,
                                               command=self._toggle_custom_prompt)
        self.custom_prompt_btn.grid(row=0, column=4, padx=(8, 0))
        self.custom_prompt_frame = ctk.CTkFrame(purpose_row, fg_color="transparent")
        self.custom_prompt_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.custom_prompt_frame, text=S.PROMPT_PROPIO_AYUDA, text_color=COLOR_MUTED,
                     wraplength=760, justify="left").grid(row=0, column=0, sticky="w", pady=(4, 2))
        self.insert_template_btn = ctk.CTkButton(self.custom_prompt_frame, text=S.INSERTAR_PLANTILLA, width=140,
                                                 command=self._insert_prompt_template)
        self.insert_template_btn.grid(row=0, column=1, sticky="ne", padx=(8, 0), pady=(4, 2))
        self.custom_prompt_box = ctk.CTkTextbox(self.custom_prompt_frame, height=140, wrap="word",
                                                **UNDO_TEXTBOX_OPTIONS)
        self.custom_prompt_box.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.custom_prompt_box.insert("1.0", chapter.custom_prompt)
        self.custom_prompt_box.edit_reset()
        self.custom_prompt_box.bind("<KeyRelease>", lambda _e=None: self._refresh_custom_prompt_btn())
        self.custom_prompt_visible = False
        self._refresh_custom_prompt_btn()

        # Barra de acciones compacta: las acciones principales a la vista y
        # las demas en "Más herramientas" (se despliega debajo).
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=8)
        self.generate_btn = ctk.CTkButton(btn_frame, text=S.GENERAR, width=80, command=self._on_generate)
        self.generate_btn.pack(side="left", padx=(0, 4), pady=4)
        self.continue_btn = ctk.CTkButton(btn_frame, text=S.CONTINUAR, width=80, command=self._on_continue)
        self.continue_btn.pack(side="left", padx=4, pady=4)
        self.continue_cursor_btn = ctk.CTkButton(
            btn_frame, text=S.DESDE_EL_CURSOR, width=110,
            command=lambda: self._on_continue(from_cursor=True),
        )
        self.continue_cursor_btn.pack(side="left", padx=4, pady=4)
        self.retry_btn = ctk.CTkButton(btn_frame, text=S.REINTENTAR, width=85, state="disabled", command=self._on_retry)
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
            btn_frame, text=S.CANCELAR, width=80, state="disabled",
            fg_color="#8a6a2f", hover_color="#6e5526", command=self._on_cancel,
        )
        self.cancel_btn.pack(side="left", padx=4, pady=4)
        self.history_btn = ctk.CTkButton(btn_frame, text=S.VERSIONES_ANTERIORES_0, width=170, command=self._on_show_history)
        self.history_btn.pack(side="left", padx=4, pady=4)
        self.more_btn = ctk.CTkButton(btn_frame, text=S.MAS_HERRAMIENTAS, width=140, command=self._toggle_tools)
        self.more_btn.pack(side="left", padx=4, pady=4)

        self.tools_row = ctk.CTkFrame(self, fg_color="transparent")
        self.reduce_btn = ctk.CTkButton(self.tools_row, text=S.REDUCIR_REPETICION, width=140, command=self._on_reduce)
        self.reduce_btn.pack(side="left", padx=(0, 6), pady=2)
        self.report_btn = ctk.CTkButton(self.tools_row, text=S.REPORTE_DE_REPETICION, width=150, command=self._on_report)
        self.report_btn.pack(side="left", padx=6, pady=2)
        self.find_btn = ctk.CTkButton(self.tools_row, text=S.BUSCAR_Y_REEMPLAZAR_CTRL_F, width=190, command=self.show_find_bar)
        self.find_btn.pack(side="left", padx=6, pady=2)
        self.remove_btn = ctk.CTkButton(
            self.tools_row, text=S.ELIMINAR_CAPITULO, width=130, fg_color="#8a3b3b",
            hover_color="#6e2f2f", command=self._on_remove,
        )
        self.remove_btn.pack(side="right", padx=(6, 0), pady=2)
        self.tools_visible = False

        # Buscar / reemplazar en este capitulo (F5), oculto hasta Ctrl+F.
        self.find_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.find_bar.grid_columnconfigure((1, 3), weight=1)
        ctk.CTkLabel(self.find_bar, text=S.BUSCAR_ETIQUETA).grid(row=0, column=0, padx=(0, 4))
        self.find_entry = ctk.CTkEntry(self.find_bar)
        self.find_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(self.find_bar, text=S.REEMPLAZAR_ETIQUETA).grid(row=0, column=2, padx=(8, 4))
        self.replace_entry = ctk.CTkEntry(self.find_bar)
        self.replace_entry.grid(row=0, column=3, sticky="ew")
        self.find_prev_btn = ctk.CTkButton(self.find_bar, text="<", width=28, command=lambda: self.find_next(backwards=True))
        self.find_prev_btn.grid(row=0, column=4, padx=2)
        self.find_next_btn = ctk.CTkButton(self.find_bar, text=">", width=28, command=self.find_next)
        self.find_next_btn.grid(row=0, column=5, padx=2)
        self.replace_current_btn = ctk.CTkButton(self.find_bar, text=S.REEMPLAZAR, width=90, command=self.replace_current)
        self.replace_current_btn.grid(row=0, column=6, padx=2)
        self.replace_all_btn = ctk.CTkButton(self.find_bar, text=S.REEMPLAZAR_TODO, width=90, command=self.replace_all)
        self.replace_all_btn.grid(row=0, column=7, padx=2)
        self.find_close_btn = ctk.CTkButton(self.find_bar, text=S.CERRAR, width=90, command=self.hide_find_bar)
        self.find_close_btn.grid(row=0, column=8, padx=2)
        self.find_count_label = ctk.CTkLabel(self.find_bar, text="", text_color=COLOR_MUTED)
        self.find_count_label.grid(row=0, column=9, padx=6)
        self.find_entry.bind("<Return>", lambda _e: (self.find_next(), "break")[1])
        # e=None: una corrida de CI llamo a uno de estos handlers de <KeyRelease> sin evento
        # (TypeError en el callback de Tk); sin evento se trata como una tecla comun.
        self.find_entry.bind("<KeyRelease>", lambda e=None: None if getattr(e, "keysym", "") == "Return" else self.highlight_matches())
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
        self.content_box.bind("<KeyRelease>", lambda _e=None: self._on_content_edited())
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
            placeholder_text=S.INSTRUCCION_DE_REFINAMIENTO_EJ_HAZLO,
        )
        self.refine_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.refine_btn = ctk.CTkButton(self.refine_row, text=S.APLICAR_REFINAMIENTO, width=160, command=self._on_refine)
        self.refine_btn.grid(row=0, column=1)

        # Resumen: la "memoria" que recibe el capitulo siguiente.
        self.summary_header = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_header.grid(row=9, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 4))
        self.summary_toggle_btn = ctk.CTkButton(
            self.summary_header, text=S.MOSTRAR_RESUMEN, width=140, command=self._toggle_summary,
        )
        self.summary_toggle_btn.pack(side="left")
        self.regen_summary_btn = ctk.CTkButton(
            self.summary_header, text=S.REGENERAR_RESUMEN, width=150, command=self._on_regenerate_summary,
        )
        self.regen_summary_btn.pack(side="left", padx=6)
        self.summary_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_frame.grid_columnconfigure(0, weight=1)
        self.summary_box = ctk.CTkTextbox(self.summary_frame, height=90, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.summary_box.grid(row=0, column=0, sticky="ew")
        self.summary_box.insert("1.0", chapter.summary)
        self.summary_box.edit_reset()
        self.summary_box.bind("<KeyRelease>", lambda _e=None: self._refresh_summary_status())
        self.summary_visible = False

        self._refresh_word_count()
        self._refresh_summary_status()
        self._refresh_history_btn()
        # Alternativas guardadas con el proyecto: < > disponibles al reabrirlo.
        self._refresh_retry_controls(app.busy)
        apply_tab_order(self, self.focus_order_widgets())

    # ---- sincronizacion con el modelo de datos ----
    def sync_to_model(self) -> None:
        self.chapter.title = self.title_entry.get().strip() or S.CAPITULO_N.format(number=self.index + 1)
        try:
            target = int(self.target_entry.get())
        except ValueError:
            target = self.chapter.target_words
        self.chapter.target_words = max(1, min(target, MAX_WORDS_PER_CHAPTER))
        self.chapter.content = self.content_box.get("1.0", "end-1c")
        self.chapter.purpose = purpose_key(self.purpose_menu.get())
        self.chapter.author_note = self.author_note_entry.get().strip()
        self.chapter.custom_prompt = self.custom_prompt_box.get("1.0", "end-1c").strip()
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
            self.summary_toggle_btn.configure(text=S.OCULTAR_RESUMEN)
        else:
            self.summary_frame.grid_remove()
            self.summary_toggle_btn.configure(text=S.MOSTRAR_RESUMEN)

    def custom_prompt_text(self) -> str:
        return self.custom_prompt_box.get("1.0", "end-1c").strip()

    def _refresh_custom_prompt_btn(self) -> None:
        self.custom_prompt_btn.configure(
            text=S.PROMPT_PROPIO_ACTIVO if self.custom_prompt_text() else S.PROMPT_PROPIO,
        )

    def _toggle_custom_prompt(self) -> None:
        self.custom_prompt_visible = not self.custom_prompt_visible
        if self.custom_prompt_visible:
            self.custom_prompt_frame.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(4, 2))
            self.custom_prompt_box.focus_set()
        else:
            self.custom_prompt_frame.grid_remove()

    def _insert_prompt_template(self) -> None:
        if self.custom_prompt_text() and not messagebox.askyesno(APP_TITLE, S.REEMPLAZAR_PROMPT_CON_PLANTILLA):
            return
        self.custom_prompt_box.delete("1.0", "end")
        self.custom_prompt_box.insert("1.0", CUSTOM_PROMPT_TEMPLATE)
        self._refresh_custom_prompt_btn()

    def _toggle_tools(self) -> None:
        self.tools_visible = not self.tools_visible
        if self.tools_visible:
            self.tools_row.grid(row=3, column=0, columnspan=4, sticky="ew", padx=8)
            self.more_btn.configure(text=S.MENOS_HERRAMIENTAS)
        else:
            self.tools_row.grid_remove()
            self.more_btn.configure(text=S.MAS_HERRAMIENTAS)

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

    def focus_order_widgets(self):
        return [
            self.title_entry, self.target_entry, self.purpose_menu, self.author_note_entry,
            self.custom_prompt_btn, self.insert_template_btn, self.custom_prompt_box,
            self.generate_btn, self.continue_btn, self.continue_cursor_btn, self.retry_btn,
            self.prev_alt_btn, self.next_alt_btn, self.cancel_btn, self.history_btn, self.more_btn,
            self.reduce_btn, self.report_btn, self.find_btn, self.remove_btn,
            self.find_entry, self.replace_entry, self.find_prev_btn, self.find_next_btn,
            self.replace_current_btn, self.replace_all_btn, self.find_close_btn,
            self.content_box, self.refine_entry, self.refine_btn,
            self.summary_toggle_btn, self.regen_summary_btn, self.summary_box,
        ]

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
            "ok": (S.RESUMEN_AL_DIA, COLOR_MUTED),
            "stale": (S.RESUMEN_DESACTUALIZADO, COLOR_WARN),
            "missing": (S.SIN_RESUMEN, COLOR_WARN),
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
        self.history_btn.configure(text=S.VERSIONES_ANTERIORES.format(count=len(self.chapter.history)))

    def _refresh_word_count(self) -> None:
        words = count_words(self.content_box.get("1.0", "end-1c"))
        over = words > MAX_WORDS_PER_CHAPTER
        self.word_count_label.configure(
            text=S.CONTADOR_PALABRAS_CAPITULO.format(words=words, MAX_WORDS_PER_CHAPTER=MAX_WORDS_PER_CHAPTER,
                                                     target_words=self.chapter.target_words),
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
            self.status_label.configure(text=S.CANCELANDO_SE_DETENDRA_EN_BREVE)
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
            messagebox.showwarning(APP_TITLE, S.PRIMERO_CARGA_UN_MODELO_LOCAL)
            return False
        if self.app.busy:
            messagebox.showwarning(
                APP_TITLE,
                S.YA_HAY_GENERACION_EN_CURSO_CAPITULO,
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
            S.EL_RESUMEN_DE_LOS_CAPITULOS.format(numbers=numbers),
        ):
            return stale
        return []

    def _validate_before_generation(self) -> bool:
        self.app._sync_all()
        errors = self.app.project.validate_inputs()
        if errors:
            messagebox.showwarning(APP_TITLE, S.CORRIGE_ANTES_DE_GENERAR + "\n".join(errors))
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
            S.EL_CAPITULO_YA_TIENE_TEXTO.format(number=self.index + 1),
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
                S.SE_CONTINUARA_DESDE_EL_CURSOR.format(words=count_words(after)),
            ):
                return
            text = before
        if not text.strip():
            self._on_generate()
            return
        self._start_generation(resume_from=text, regenerate=self._ask_regenerate_summaries())

    # ---- Reintentar / alternativas (F4) ----
    @property
    def alternatives(self) -> List[str]:
        return self.chapter.alternatives

    @alternatives.setter
    def alternatives(self, texts: List[str]) -> None:
        self.chapter.alternatives = list(texts)

    @property
    def alt_index(self) -> int:
        return self.chapter.alt_index

    @alt_index.setter
    def alt_index(self, index: int) -> None:
        self.chapter.alt_index = index

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
        mode = S.CONTINUANDO if resume_from else S.GENERANDO
        self._set_busy(True, S.ESTO_PUEDE_TARDAR_VARIOS_MINUTOS.format(mode=mode))
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
                self.status_label.configure(text=S.PROGRESO_PALABRAS.format(mode=mode, words=words, target=target))
            app.after(0, apply)

        def set_status(text: str) -> None:
            app.after(0, lambda: self.status_label.configure(text=text))

        def cancelled() -> bool:
            return cancel_flag["cancel"] or app.task_runner.cancel_requested

        def work(_cancel_check):
            final_status = S.LISTO
            # Primero, los resumenes desactualizados que el usuario pidio
            # regenerar: son el contexto de este capitulo.
            for i in regenerate:
                if cancelled():
                    break
                ch = project.chapters[i]
                set_status(S.REGENERANDO_EL_RESUMEN_DEL_CAPITULO.format(number=i + 1))
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
                set_status(S.GENERANDO_RESUMEN_PARA_CONTINUIDAD_ENTRE)
                try:
                    summary_text = call_supported(engine.summarize, result, cancel_check=cancelled)
                    self.chapter.set_summary(summary_text, source_text=result)
                except OperationCancelled:
                    final_status = S.CANCELADO_ANTES_DEL_RESUMEN_USA
                except Exception:  # noqa: BLE001
                    # El capitulo no se pierde; el resumen queda marcado
                    # como faltante/desactualizado y se puede regenerar.
                    logger.exception("No se pudo generar el resumen del capítulo %d", self.index + 1)
                    final_status = (
                        S.LISTO_PERO_NO_SE_PUDO
                    )
            elif cancelled():
                final_status = S.CANCELADO_PUEDES_SEGUIR_CON_CONTINUAR
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
            texts = previous_alternatives + [result]
            self.chapter.set_alternatives(texts, len(texts) - 1)
            if result.strip() and not cancelled():
                app._record_lore_matches(self.index)
            seed = getattr(engine, "last_seed", None)
            if seed is not None and final_status == S.LISTO:
                final_status = S.LISTO_SEMILLA.format(seed=seed)
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
            S.CAPITULO_N.format(number=self.index + 1), work, on_success=on_success, on_finally=on_finally,
            error_prefix=S.ERROR_GENERANDO_CAPITULO,
        )

    def _on_regenerate_summary(self) -> None:
        if not self._can_start_engine_task():
            return
        self.sync_to_model()
        content = self.chapter.content
        if not content.strip():
            messagebox.showwarning(APP_TITLE, S.SIN_TEXTO_PARA_RESUMIR)
            return
        self._set_busy(True, S.GENERANDO_RESUMEN)
        engine = self.app.engine
        status = {"text": ""}

        def work(cancel_check):
            return call_supported(engine.summarize, content, cancel_check=cancel_check)

        def on_success(summary) -> None:
            self.chapter.set_summary(summary, source_text=content)
            self._show_summary_text(self.chapter.summary)
            status["text"] = S.RESUMEN_ACTUALIZADO

        def on_cancel() -> None:
            status["text"] = S.RESUMEN_CANCELADO

        def on_error(exc) -> Optional[str]:
            logger.exception("No se pudo regenerar el resumen del capítulo %d", self.index + 1, exc_info=exc)
            return S.NO_SE_PUDO_GENERAR_RESUMEN.format(exc=exc)

        self.app.task_runner.run(
            S.RESUMEN, work, on_success=on_success, on_cancel=on_cancel, on_error=on_error,
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
        messagebox.showinfo(S.REPETICION_CAPITULO.format(number=self.index + 1), report)

    def _on_remove(self) -> None:
        if messagebox.askyesno(APP_TITLE, S.ELIMINAR_EL_CAPITULO.format(number=self.index + 1)):
            self.app.remove_chapter(self.index)

    # ---- refinamiento con vista previa (F4) ----
    def _on_refine(self) -> None:
        if not self._can_start_engine_task():
            return
        self.sync_to_model()
        if not self.chapter.content.strip():
            messagebox.showwarning(
                APP_TITLE, S.SIN_TEXTO_PARA_REFINAR
            )
            return
        instruction = self.refine_entry.get().strip()
        if not instruction:
            messagebox.showwarning(
                APP_TITLE, S.ESCRIBE_UNA_INSTRUCCION_DE_REFINAMIENTO
            )
            return
        original = self.chapter.content
        self._set_busy(True, S.REFINANDO_CAPITULO_VERAS_UNA_VISTA)
        self._set_generating(True)
        engine = self.app.engine
        project = self.app.project

        def progress(part: int, total: int) -> None:
            if total > 1:
                self.app.after(0, lambda: self.status_label.configure(
                    text=S.REFINANDO_LA_PARTE_DE.format(part=part, total=total)))

        def work(cancel_check):
            return call_supported(
                engine.refine_chapter, project, self.index, instruction,
                cancel_check=cancel_check, progress_callback=progress,
            )

        status = {"text": ""}

        def on_success(revised: str) -> None:
            status["text"] = S.REVISA_LA_VISTA_PREVIA_ACEPTAR
            self.app.show_diff_preview(
                S.REFINAR_CAPITULO_INSTRUCCION.format(number=self.index + 1, instruction=instruction), original, revised,
                on_accept=lambda text: self._apply_revision(text, f"refine: {instruction}"),
                on_accept_continue=lambda text: self._apply_revision(
                    text, f"refine: {instruction}", keep_refining=True),
                on_discard=lambda: self.status_label.configure(text=S.REFINAMIENTO_DESCARTADO),
            )

        def on_cancel() -> None:
            status["text"] = S.REFINAMIENTO_CANCELADO_EL_CAPITULO_NO

        def on_finally() -> None:
            self._set_generating(False)
            self._set_busy(False, status["text"])

        self.app.task_runner.run(
            S.REFINAR_CAPITULO_N.format(number=self.index + 1), work, on_success=on_success, on_cancel=on_cancel,
            on_finally=on_finally, error_prefix=S.ERROR_REFINANDO_EL_CAPITULO,
        )

    def _apply_revision(self, text: str, source: str, keep_refining: bool = False) -> None:
        self.sync_to_model()
        self.push_history(source)
        self.chapter.content = text
        _set_text_readonly_content(self.content_box, text)
        self.content_box.edit_reset()
        self._on_content_edited()
        self.status_label.configure(text=S.CAMBIO_APLICADO_LA_VERSION_ANTERIOR)
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
            menu.add_command(label=S.SELECCION.format(label=label), state=state,
                             command=lambda m=mode: self.rewrite_selection(m))
        menu.add_command(label=S.REESCRIBIR_SELECCION_CON_INSTRUCCION, state=state,
                         command=lambda: self.rewrite_selection("rewrite", ask_instruction=True))
        menu.add_separator()
        menu.add_command(label=S.BUSCAR_Y_REEMPLAZAR_CTRL_F, command=self.show_find_bar)
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
            messagebox.showinfo(APP_TITLE, S.SELECCIONA_PRIMERO_EL_FRAGMENTO_DEL)
            return
        if not self._can_start_engine_task():
            return
        if ask_instruction:
            dialog = ctk.CTkInputDialog(text=S.INSTRUCCION_PARA_ESTE_FRAGMENTO, title=S.REESCRIBIR_SELECCION)
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
        self._set_busy(True, S.TRABAJANDO_SOBRE_LA_SELECCION.format(mode=REWRITE_MODE_LABELS.get(mode, mode)))
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
                S.SELECCION_CAPITULO.format(label=label, number=self.index + 1), selection, new_passage.strip(),
                on_accept=lambda _t: self._apply_revision(new_full, f"rewrite: {label.lower()}"),
            )

        self.app.task_runner.run(
            S.REESCRIBIR_SELECCION, work, on_success=on_success,
            on_finally=lambda: (self._set_generating(False), self._set_busy(False, "")),
            error_prefix=S.ERROR_REESCRIBIENDO_LA_SELECCION,
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
        self.find_count_label.configure(text=S.COINCIDENCIAS.format(count=len(positions)) if self.find_entry.get() else "")
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
        self.find_count_label.configure(text=S.REEMPLAZOS.format(count=count))
        return count

    # ---- versiones anteriores ----
    def _on_show_history(self) -> None:
        if not self.chapter.history:
            messagebox.showinfo(APP_TITLE, S.ESTE_CAPITULO_NO_TIENE_VERSIONES)
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
        self.title(S.VERSIONES_ANTERIORES_CAPITULO.format(number=panel.index + 1))
        self.geometry("760x520")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # El menu muestra la version mas reciente primero; chapter.history
        # guarda la mas vieja primero (ver _selected_history_index()).
        entries = panel.chapter.history_entries()
        total = len(entries)
        self._labels = []
        for i, entry in enumerate(entries):
            label = S.VERSION_DE_PALABRAS.format(number=i + 1, total=total, words=count_words(entry['text']))
            at = entry.get("at", "")
            if at:
                label += f" - {at.replace('T', ' ')}"
            self._labels.append(label)
        self._labels.reverse()

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(top, text=S.VERSION_ETIQUETA).pack(side="left", padx=(0, 6))
        self.version_menu = ctk.CTkOptionMenu(top, values=self._labels, command=self._on_select, width=360)
        self.version_menu.pack(side="left", padx=(0, 12))
        self.restore_btn = ctk.CTkButton(top, text=S.RESTAURAR_ESTA_VERSION, command=self._on_restore)
        self.restore_btn.pack(side="left")
        self.diff_btn = ctk.CTkButton(top, text=S.COMPARAR_CON_LA_ACTUAL, command=self._on_compare)
        self.diff_btn.pack(side="left", padx=6)
        self.source_label = ctk.CTkLabel(self, text="", text_color=COLOR_MUTED, anchor="w")
        self.source_label.grid(row=1, column=0, sticky="ew", padx=10)

        self.preview_box = ctk.CTkTextbox(self, wrap="word")
        self.preview_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.preview_box.configure(state="disabled")

        self._on_select(self._labels[0])
        apply_tab_order(self, self.version_menu, self.restore_btn, self.diff_btn, self.preview_box)

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
        self.source_label.configure(text=S.GUARDADA_ANTES_DE.format(source=source) if source else "")

    def _on_compare(self) -> None:
        self.panel.sync_to_model()
        text = self.panel.chapter.history[self._selected_history_index()]
        DiffPreviewDialog(
            self, S.VERSION_ANTERIOR_IZQUIERDA_FRENTE_A, text,
            self.panel.chapter.content, on_accept=lambda _t: None,
        )

    def _on_restore(self) -> None:
        text = self.panel.chapter.history[self._selected_history_index()]
        if not messagebox.askyesno(
            APP_TITLE,
            S.ESTO_REEMPLAZA_EL_CONTENIDO_ACTUAL,
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
