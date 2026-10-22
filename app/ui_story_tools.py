"""
Herramientas del editor de capitulo: comentarios del editor (F21), escenas y
tramos privados (F23). Mixin de ChapterPanel; los botones van en la fila de
"Mas herramientas".
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import List, Optional

import customtkinter as ctk

from . import strings_es as S
from .error_text import describe_exception
from .lore_tools import FeedbackNote, locate_quote
from .scenes import PRIVATE_CLOSE, PRIVATE_OPEN, scene_header, split_scenes
from .task_runner import call_supported
from .ui_common import APP_TITLE

logger = logging.getLogger(__name__)


class StoryToolsMixin:
    """Necesita de ChapterPanel: app, index, chapter, content_box, sync_to_model,
    _can_start_engine_task, _set_busy, _on_content_edited, tools_row."""

    def _build_story_tools(self) -> None:
        self.feedback_btn = ctk.CTkButton(self.tools_row, text=S.COMENTARIOS_DEL_EDITOR, width=170,
                                          command=self._on_feedback)
        self.feedback_btn.pack(side="left", padx=6, pady=2)
        self.scenes_btn = ctk.CTkButton(self.tools_row, text=S.ESCENAS_MENU, width=100, command=self._show_scenes_menu)
        self.scenes_btn.pack(side="left", padx=6, pady=2)
        self.new_scene_btn = ctk.CTkButton(self.tools_row, text=S.NUEVA_ESCENA, width=110, command=self._on_new_scene)
        self.new_scene_btn.pack(side="left", padx=6, pady=2)
        self.private_btn = ctk.CTkButton(self.tools_row, text=S.MARCAR_PRIVADO, width=140, command=self._on_mark_private)
        self.private_btn.pack(side="left", padx=6, pady=2)

    # ---------------- escenas (F23) ----------------
    def _show_scenes_menu(self) -> None:
        self.sync_to_model()
        text = self.chapter.content
        menu = tk.Menu(self, tearoff=False)
        scenes = [s for s in split_scenes(text) if s.has_header]
        if not scenes:
            menu.add_command(label=S.SIN_ESCENAS, state="disabled")
        for number, scene in enumerate(scenes, start=1):
            menu.add_command(label=scene.display(number), command=lambda s=scene: self._jump_to_offset(s.start))
        x = self.scenes_btn.winfo_rootx()
        y = self.scenes_btn.winfo_rooty() + self.scenes_btn.winfo_height()
        menu.tk_popup(x, y)

    def _jump_to_offset(self, offset: int) -> None:
        index = f"1.0+{offset}c"
        self.content_box.mark_set("insert", index)
        self.content_box.see(index)
        self.content_box.focus_set()

    def _on_new_scene(self) -> None:
        label = simpledialog.askstring(APP_TITLE, S.NOMBRE_DE_LA_ESCENA, parent=self)
        if label is None:
            return
        pov = simpledialog.askstring(APP_TITLE, S.POV_DE_LA_ESCENA, parent=self) or ""
        box = self.content_box
        line_start = box.index("insert").split(".")[0] + ".0"
        prefix = "" if box.get(f"{line_start}-1c", line_start) in ("", "\n") else "\n"
        box.edit_separator()
        box.insert(line_start, f"{prefix}{scene_header(label, pov)}\n")
        box.edit_separator()
        self._on_content_edited()

    def _on_mark_private(self) -> None:
        box = self.content_box
        try:
            start, end = box.index("sel.first"), box.index("sel.last")
        except tk.TclError:
            messagebox.showinfo(APP_TITLE, S.SELECCIONA_TEXTO_PRIVADO)
            return
        box.edit_separator()
        box.insert(end, PRIVATE_CLOSE)
        box.insert(start, PRIVATE_OPEN)
        box.edit_separator()
        self._on_content_edited()

    # ---------------- comentarios del editor (F21) ----------------
    def _on_feedback(self) -> None:
        if not self._can_start_engine_task():
            return
        self.sync_to_model()
        engine, project, index = self.app.engine, self.app.project, self.index
        self._set_busy(True, S.LEYENDO_EL_CAPITULO)
        status = {"text": ""}

        def work(cancel_check):
            return call_supported(engine.feedback, project, index, cancel_check=cancel_check)

        def on_success(notes) -> None:
            status["text"] = S.COMENTARIOS_LISTOS.format(n=len(notes))
            FeedbackDialog(self, notes)

        def on_error(exc) -> Optional[str]:
            if isinstance(exc, ValueError):
                return str(exc)
            logger.exception("No se pudieron generar los comentarios del capitulo %d", index + 1, exc_info=exc)
            return S.NO_SE_PUDIERON_GENERAR_COMENTARIOS.format(exc=describe_exception(exc))

        self.app.task_runner.run(S.COMENTARIOS_OPERACION, work, on_success=on_success,
                                 on_cancel=lambda: status.update(text=S.CANCELADO),
                                 on_error=on_error, on_finally=lambda: self._set_busy(False, status["text"]))

    def select_quote(self, quote: str) -> bool:
        span = locate_quote(self.content_box.get("1.0", "end-1c"), quote)
        if span is None:
            return False
        start, end = f"1.0+{span[0]}c", f"1.0+{span[1]}c"
        self.content_box.tag_remove("sel", "1.0", "end")
        self.content_box.tag_add("sel", start, end)
        self.content_box.mark_set("insert", start)
        self.content_box.see(start)
        self.content_box.focus_set()
        return True


class FeedbackDialog(ctk.CTkToplevel):
    """Las notas del editor; "Ir al pasaje" selecciona la cita en el capitulo."""

    def __init__(self, panel, notes: List[FeedbackNote]):
        super().__init__(panel)
        self.panel = panel
        self.title(S.COMENTARIOS_DEL_CAPITULO.format(number=panel.index + 1))
        self.geometry("640x480")
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        scroll.grid_columnconfigure(0, weight=1)
        if not notes:
            ctk.CTkLabel(scroll, text=S.SIN_COMENTARIOS, wraplength=580, justify="left").grid(row=0, column=0, sticky="w")
        for row, note in enumerate(notes):
            card = ctk.CTkFrame(scroll, border_width=1, corner_radius=8)
            card.grid(row=row, column=0, sticky="ew", pady=4)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=note.area.capitalize(), font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=0, sticky="w", padx=8, pady=(6, 0))
            if note.quote:
                ctk.CTkLabel(card, text=f"«{note.quote}»", wraplength=560, justify="left",
                             font=ctk.CTkFont(slant="italic")).grid(row=1, column=0, sticky="w", padx=8)
            ctk.CTkLabel(card, text=note.note, wraplength=560, justify="left").grid(row=2, column=0, sticky="w",
                                                                                    padx=8, pady=(0, 6))
            if note.quote:
                ctk.CTkButton(card, text=S.IR_AL_PASAJE, width=110,
                              command=lambda q=note.quote: self._go(q)).grid(row=0, column=1, rowspan=3, padx=8)
        ctk.CTkButton(self, text=S.CERRAR, command=self.destroy).pack(pady=(0, 10))

    def _go(self, quote: str) -> None:
        if not self.panel.select_quote(quote):
            messagebox.showinfo(APP_TITLE, S.CITA_NO_ENCONTRADA, parent=self)
