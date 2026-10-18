"""Lluvia de ideas y entrevistas (F14): una conversacion al costado de la historia.

Una ventana aparte (Editar > Lluvia de ideas y entrevistas…) donde el autor conversa con el modelo
sobre la historia -- ideas para la proxima escena, consecuencias, contradicciones -- o entrevista a un
personaje, que contesta en primera persona. El modelo ve la premisa, los personajes, la ambientacion,
el esquema, los capitulos anteriores resumidos y el final del capitulo seleccionado
(prompts.build_side_chat / engine.side_chat). Nada se escribe en el capitulo salvo que el autor
inserte una respuesta (en el cursor del capitulo seleccionado, con su entrada en el historial). La
conversacion vive mientras la ventana esta abierta; no se guarda con el proyecto.
"""
from __future__ import annotations

from tkinter import messagebox
from typing import List, Optional, Tuple

import customtkinter as ctk

from . import strings_es as S
from .prompts import SIDE_CHAT_BRAINSTORM, SIDE_CHAT_CHARACTER
from .ui_common import APP_TITLE
from .ui_focus import apply_tab_order


class SideChatWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(S.CONVERSACION_TITULO)
        self.geometry("760x640")
        self.history: List[Tuple[str, str]] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text=S.CONVERSACION_AYUDA, justify="left", wraplength=720).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=10)
        self.mode = ctk.CTkSegmentedButton(top, values=[S.CONVERSACION_MODO_IDEAS, S.CONVERSACION_MODO_PERSONAJE],
                                           command=self._on_mode)
        self.mode.set(S.CONVERSACION_MODO_IDEAS)
        self.mode.pack(side="left")
        self.character_label = ctk.CTkLabel(top, text=S.CONVERSACION_PERSONAJE)
        self.character_entry = ctk.CTkEntry(top, width=180, placeholder_text=S.CONVERSACION_PERSONAJE_EJEMPLO)

        self.transcript = ctk.CTkTextbox(self, wrap="word")
        self.transcript.grid(row=2, column=0, sticky="nsew", padx=10, pady=6)
        self.transcript.configure(state="disabled")

        self.input = ctk.CTkTextbox(self, height=70, wrap="word")
        self.input.grid(row=3, column=0, sticky="ew", padx=10)
        self.input.bind("<Control-Return>", lambda _e: (self.send(), "break")[1])

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="ew", padx=10, pady=(6, 10))
        self.send_btn = ctk.CTkButton(bar, text=S.CONVERSACION_ENVIAR, command=self.send)
        self.send_btn.pack(side="right", padx=4)
        self.insert_btn = ctk.CTkButton(bar, text=S.CONVERSACION_INSERTAR, command=self.insert_last_reply)
        self.insert_btn.pack(side="left", padx=4)
        self.copy_btn = ctk.CTkButton(bar, text=S.CONVERSACION_COPIAR, width=120, command=self.copy_last_reply)
        self.copy_btn.pack(side="left", padx=4)
        self.new_btn = ctk.CTkButton(bar, text=S.CONVERSACION_NUEVA, width=120, command=self.new_conversation)
        self.new_btn.pack(side="left", padx=4)
        apply_tab_order(self, self.character_entry, self.input, self.send_btn, self.insert_btn,
                        self.copy_btn, self.new_btn)
        self.input.focus_set()

    # ---- modo ----
    @property
    def chat_mode(self) -> str:
        return SIDE_CHAT_CHARACTER if self.mode.get() == S.CONVERSACION_MODO_PERSONAJE else SIDE_CHAT_BRAINSTORM

    def _on_mode(self, _value=None) -> None:
        if self.chat_mode == SIDE_CHAT_CHARACTER:
            self.character_label.pack(side="left", padx=(12, 4))
            self.character_entry.pack(side="left")
            self.character_entry.focus_set()
        else:
            self.character_label.pack_forget()
            self.character_entry.pack_forget()

    def set_mode(self, mode: str, character: str = "") -> None:
        self.mode.set(S.CONVERSACION_MODO_PERSONAJE if mode == SIDE_CHAT_CHARACTER else S.CONVERSACION_MODO_IDEAS)
        self.character_entry.delete(0, "end")
        if character:
            self.character_entry.insert(0, character)
        self._on_mode()

    # ---- transcripcion ----
    def _speaker(self, role: str) -> str:
        if role == "user":
            return S.CONVERSACION_TU
        if self.chat_mode == SIDE_CHAT_CHARACTER:
            return self.character_entry.get().strip() or S.CONVERSACION_MODO_PERSONAJE
        return S.CONVERSACION_IDEAS

    def _append(self, text: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", text)
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def transcript_text(self) -> str:
        return self.transcript.get("1.0", "end-1c")

    # ---- acciones ----
    def send(self, message: Optional[str] = None) -> bool:
        message = (message if message is not None else self.input.get("1.0", "end-1c")).strip()
        if not message:
            messagebox.showinfo(APP_TITLE, S.CONVERSACION_ESCRIBE_UN_MENSAJE, parent=self)
            return False
        character = self.character_entry.get().strip()
        if self.chat_mode == SIDE_CHAT_CHARACTER and not character:
            messagebox.showinfo(APP_TITLE, S.CONVERSACION_FALTA_PERSONAJE, parent=self)
            return False
        if not self.app.engine.is_loaded:
            messagebox.showwarning(APP_TITLE, S.PRIMERO_CARGA_UN_MODELO_LOCAL, parent=self)
            return False
        if self.app.busy:
            messagebox.showwarning(APP_TITLE, S.YA_HAY_GENERACION_EN_CURSO, parent=self)
            return False
        self.app._sync_all()
        project, engine = self.app.project, self.app.engine
        chapter_index = self.app.selected_chapter_index if project.chapters else None
        history = list(self.history)
        mode = self.chat_mode
        self.input.delete("1.0", "end")
        self._append(f"{S.CONVERSACION_TU}: {message}\n\n{self._speaker('assistant')}: ")
        self.send_btn.configure(state="disabled")

        def on_token(delta: str) -> None:
            self.after(0, lambda d=delta: self._append(d))

        def work(cancel_check):
            return engine.side_chat(project, chapter_index, history, message, mode, character,
                                    cancel_check=cancel_check, on_token=on_token)

        def on_success(reply: str) -> None:
            self.history += [("user", message), ("assistant", reply.strip())]
            self.transcript.configure(state="normal")
            # el texto transmitido puede tener espacios de mas: se deja la respuesta final limpia
            start = self.transcript.search(f"{self._speaker('assistant')}: ", "end", backwards=True)
            if start:
                self.transcript.delete(f"{start}+{len(self._speaker('assistant')) + 2}c", "end")
            self.transcript.insert("end", reply.strip() + "\n\n")
            self.transcript.see("end")
            self.transcript.configure(state="disabled")

        self.app.task_runner.run(
            S.CONVERSACION_OPERACION, work, on_success=on_success,
            on_finally=lambda: self.send_btn.configure(state="normal") if self.winfo_exists() else None,
            error_prefix=S.ERROR_EN_LA_CONVERSACION, autosave=False,
        )
        return True

    def last_reply(self) -> str:
        return next((text for role, text in reversed(self.history) if role == "assistant"), "")

    def copy_last_reply(self) -> None:
        reply = self.last_reply()
        if reply:
            self.clipboard_clear()
            self.clipboard_append(reply)

    def insert_last_reply(self) -> bool:
        """Inserta la ultima respuesta en el cursor del capitulo seleccionado (con su entrada en el
        historial de versiones del capitulo)."""
        reply = self.last_reply()
        if not reply:
            messagebox.showinfo(APP_TITLE, S.CONVERSACION_SIN_RESPUESTA, parent=self)
            return False
        panels = self.app.chapter_panels
        index = self.app.selected_chapter_index
        if not panels or not 0 <= index < len(panels):
            return False
        panel = panels[index]
        panel.sync_to_model()
        panel.push_history(S.CONVERSACION_ORIGEN)
        box = panel.content_box
        before = box.get("insert-1c", "insert") if box.compare("insert", ">", "1.0") else ""
        joiner = "" if not before or before.isspace() else " "
        box.insert("insert", joiner + reply)
        panel._on_content_edited()
        panel.sync_to_model()
        self.app.schedule_dirty_check()
        panel.status_label.configure(text=S.CONVERSACION_INSERTADA.format(number=index + 1))
        return True

    def new_conversation(self) -> None:
        self.history = []
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self.input.focus_set()
