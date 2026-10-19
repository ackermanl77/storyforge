"""
Ventana "Matriz de la historia" (F18, app/story_matrix.py): una tabla de
capitulos x personajes/hilos con las menciones de cada uno, el aviso de quien
desaparece varios capitulos seguidos, Actualizar y Exportar CSV. Doble clic
en una fila abre ese capitulo.
"""
from __future__ import annotations

from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from . import strings_es as S
from .fileutil import atomic_write_text
from .story_matrix import build_story_matrix
from .ui_common import APP_TITLE


class StoryMatrixWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(S.MATRIZ_TITULO)
        self.geometry("980x520")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=S.MATRIZ_EXPLICACION, wraplength=940, justify="left").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        frame = ctk.CTkFrame(self)
        frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, show="headings", height=14)
        self.tree.grid(row=0, column=0, sticky="nsew")
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=x_scroll.set)
        self.tree.bind("<Double-1>", self._open_chapter)
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.gaps_label = ctk.CTkLabel(bottom, text="", justify="left", wraplength=700)
        self.gaps_label.pack(side="left")
        ctk.CTkButton(bottom, text=S.MATRIZ_EXPORTAR_CSV, width=120, command=self.export_csv).pack(side="right", padx=4)
        ctk.CTkButton(bottom, text=S.MATRIZ_ACTUALIZAR, width=110, command=self.refresh).pack(side="right", padx=4)
        self.matrix = None
        self.refresh()

    def refresh(self) -> None:
        if hasattr(self.app, "_sync_all"):
            self.app._sync_all()
        self.matrix = build_story_matrix(self.app.project)
        labels = [S.MATRIZ_CAPITULO] + [column.label for column in self.matrix.columns]
        ids = [f"c{i}" for i in range(len(labels))]
        self.tree.configure(columns=ids)
        for column_id, label in zip(ids, labels):
            self.tree.heading(column_id, text=label)
            self.tree.column(column_id, width=220 if column_id == "c0" else max(70, 9 * len(label)), anchor="w" if column_id == "c0" else "center",
                             stretch=column_id == "c0")
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.matrix.rows):
            title = row.title + (f" {S.MATRIZ_PLANEADO}" if row.planned else "")
            cells = [str(count) if count else "·" for count in row.counts]
            self.tree.insert("", "end", iid=str(index), values=[title, *cells])
        if not self.matrix.columns:
            self.gaps_label.configure(text=S.MATRIZ_SIN_COLUMNAS)
            return
        gaps = self.matrix.gaps()
        self.gaps_label.configure(text=S.MATRIZ_AUSENCIAS.format(items=", ".join(
            S.MATRIZ_AUSENCIA.format(label=label, chapters=streak) for label, streak in gaps.items())) if gaps else "")

    def _open_chapter(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection and hasattr(self.app, "select_chapter"):
            self.app.tabview.set(S.TAB_CAPITULOS)
            self.app.select_chapter(int(selection[0]))

    def export_csv(self) -> None:
        if self.matrix is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title=S.MATRIZ_EXPORTAR_CSV, defaultextension=".csv",
                                            filetypes=[(S.MATRIZ_CSV, "*.csv")])
        if path:
            try:
                atomic_write_text(path, "﻿" + self.matrix.to_csv())  # BOM: Excel opens it as UTF-8
            except OSError as exc:
                messagebox.showerror(APP_TITLE, str(exc), parent=self)
