"""
Ventana "Componentes de prompt" (F20, app/prompt_components.py): lista de
componentes a la izquierda, nombre y texto del elegido a la derecha; Nuevo,
Guardar, Borrar y copiar su marcador {@nombre} al portapapeles.
"""
from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from . import prompt_components as pc
from . import strings_es as S
from .ui_common import APP_TITLE, UNDO_TEXTBOX_OPTIONS


class ComponentsWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(S.COMPONENTES_TITULO)
        self.geometry("820x520")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=S.COMPONENTES_EXPLICACION, wraplength=780, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))
        self.list_frame = ctk.CTkScrollableFrame(self, width=220)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 6), pady=6)
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 10), pady=6)
        right.grid_columnconfigure(1, weight=1)
        right.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(right, text=S.COMPONENTE_NOMBRE).grid(row=0, column=0, sticky="w")
        self.name_entry = ctk.CTkEntry(right)
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkLabel(right, text=S.COMPONENTE_TEXTO).grid(row=1, column=0, sticky="nw", pady=(6, 0))
        self.text_box = ctk.CTkTextbox(right, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.text_box.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(6, 0))
        buttons = ctk.CTkFrame(right, fg_color="transparent")
        buttons.grid(row=2, column=1, sticky="e", pady=(8, 0))
        ctk.CTkButton(buttons, text=S.COMPONENTE_NUEVO, width=90, command=self.new).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text=S.COMPONENTE_COPIAR_MARCADOR, width=130, command=self.copy_marker).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text=S.COMPONENTE_BORRAR, width=90, fg_color="#8a3b3b", hover_color="#6e2f2f",
                      command=self.delete).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text=S.COMPONENTE_GUARDAR, width=90, command=self.save).pack(side="left", padx=4)
        self.status = ctk.CTkLabel(self, text="")
        self.status.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 8))
        self.selected = ""
        self.refresh()

    def refresh(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        components = pc.load_components()
        if not components:
            ctk.CTkLabel(self.list_frame, text=S.COMPONENTES_NINGUNO).pack(anchor="w")
        for name in sorted(components, key=str.lower):
            ctk.CTkButton(self.list_frame, text=f"{{@{name}}}", anchor="w", fg_color="transparent",
                          command=lambda n=name: self.select(n)).pack(fill="x", pady=1)

    def select(self, name: str) -> None:
        text = pc.load_components().get(name, "")
        self.selected = name
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, name)
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)

    def new(self) -> None:
        self.selected = ""
        self.name_entry.delete(0, "end")
        self.text_box.delete("1.0", "end")
        self.name_entry.focus_set()

    def save(self) -> bool:
        try:
            name = pc.save_component(self.name_entry.get(), self.text_box.get("1.0", "end-1c"))
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc), parent=self)
            return False
        if self.selected and self.selected != name:
            pc.delete_component(self.selected)  # renamed
        self.selected = name
        self.status.configure(text=S.COMPONENTE_GUARDADO.format(name=name))
        self.refresh()
        return True

    def delete(self) -> None:
        name = self.selected
        if name and messagebox.askyesno(APP_TITLE, S.COMPONENTE_BORRAR_CONFIRMAR.format(name=name), parent=self):
            pc.delete_component(name)
            self.new()
            self.refresh()

    def copy_marker(self) -> None:
        name = self.selected or self.name_entry.get().strip()
        if name:
            self.clipboard_clear()
            self.clipboard_append(f"{{@{name}}}")
