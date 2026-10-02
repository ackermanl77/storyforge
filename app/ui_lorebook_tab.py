"""
Pestana Lorebook: LoreEntryPanel (una entrada), el filtro de busqueda y
LorebookTabMixin (alta/baja, filtrado sin reconstruir paneles, coincidencias
de la ultima generacion).
"""
from __future__ import annotations

from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from . import strings_es as S
from .project import (
    MAX_LORE_ENTRIES,
    LoreEntry,
)
from .prompts import (
    build_lore_scan_text,
    build_previous_context,
    match_lore_entries,
)
from .ui_common import (
    APP_TITLE,
    LORE_FILTER_DEBOUNCE_MS,
    UNDO_TEXTBOX_OPTIONS,
)
from .ui_dialogs import (
    COLOR_MUTED,
    COLOR_OK,
)

if TYPE_CHECKING:
    from .gui import StoryForgeApp


class LoreEntryPanel(ctk.CTkFrame):
    """
    Una entrada del Lorebook / World Info: nombre, palabras clave, texto, y
    si esta activa, siempre incluida o su prioridad (B8). Se inyecta en el
    prompt de un capitulo solo cuando alguna palabra clave aparece en el
    texto cercano de esa generacion (ver prompts.match_lore_entries).
    """

    def __init__(
        self, master, app: "StoryForgeApp", index: int, entry: LoreEntry,
        matched_last_generation: bool = False, match_reason: str = "", **kwargs,
    ):
        super().__init__(master, border_width=1, corner_radius=8, **kwargs)
        self.app = app
        self.index = index
        self.entry = entry
        self.matched_last_generation = matched_last_generation
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=S.NOMBRE).grid(row=0, column=0, padx=8, pady=(8, 2), sticky="w")
        self.name_entry = ctk.CTkEntry(self, placeholder_text=S.P_EJ_ELENA_VASQUEZ)
        self.name_entry.insert(0, entry.name)
        self.name_entry.grid(row=0, column=1, padx=8, pady=(8, 2), sticky="ew")

        self.badge_label = ctk.CTkLabel(self, text="", text_color=COLOR_OK, font=ctk.CTkFont(size=11))
        self.badge_label.grid(row=0, column=2, padx=(8, 0), pady=(8, 2), sticky="e")
        self.set_match(matched_last_generation, match_reason)

        self.remove_btn = ctk.CTkButton(
            self, text=S.ELIMINAR, width=90, fg_color="#8a3b3b", hover_color="#6e2f2f",
            command=self._on_remove,
        )
        self.remove_btn.grid(row=0, column=3, padx=8, pady=(8, 2))

        ctk.CTkLabel(self, text=S.PALABRAS_CLAVE_SEPARADAS_POR_COMA).grid(
            row=1, column=0, padx=8, pady=2, sticky="w"
        )
        self.keywords_entry = ctk.CTkEntry(self, placeholder_text=S.P_EJ_ELENA_LA_REINA)
        self.keywords_entry.insert(0, entry.keywords)
        self.keywords_entry.grid(row=1, column=1, columnspan=2, padx=8, pady=2, sticky="ew")

        options = ctk.CTkFrame(self, fg_color="transparent")
        options.grid(row=2, column=1, columnspan=3, sticky="w", padx=8, pady=2)
        self.enabled_var = ctk.BooleanVar(value=entry.enabled)
        self.constant_var = ctk.BooleanVar(value=entry.constant)
        ctk.CTkCheckBox(options, text=S.ACTIVA, variable=self.enabled_var).pack(side="left", padx=(0, 12))
        ctk.CTkCheckBox(options, text=S.INCLUIR_SIEMPRE, variable=self.constant_var).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(options, text=S.PRIORIDAD).pack(side="left", padx=(0, 4))
        self.priority_entry = ctk.CTkEntry(options, width=50)
        self.priority_entry.insert(0, str(entry.priority))
        self.priority_entry.pack(side="left")

        ctk.CTkLabel(self, text=S.TEXTO_ETIQUETA).grid(row=3, column=0, padx=8, pady=(2, 8), sticky="nw")
        self.text_box = ctk.CTkTextbox(self, height=80, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.text_box.insert("1.0", entry.text)
        self.text_box.edit_reset()
        self.text_box.grid(row=3, column=1, columnspan=2, padx=8, pady=(2, 8), sticky="ew")

    def set_match(self, matched: bool, reason: str = "") -> None:
        self.matched_last_generation = matched
        text = ""
        if matched:
            text = S.USADA_EN_LA_ULTIMA_GENERACION + (f": {reason}" if reason else "")
        self.badge_label.configure(text=text)

    def sync_to_model(self) -> None:
        self.entry.name = self.name_entry.get().strip()
        self.entry.keywords = self.keywords_entry.get().strip()
        self.entry.text = self.text_box.get("1.0", "end-1c")
        self.entry.enabled = bool(self.enabled_var.get())
        self.entry.constant = bool(self.constant_var.get())
        try:
            self.entry.priority = max(-100, min(int(self.priority_entry.get()), 100))
        except ValueError:
            pass

    def _on_remove(self) -> None:
        label = self.entry.name.strip() or S.ENTRADA.format(number=self.index + 1)
        if messagebox.askyesno(APP_TITLE, S.ELIMINAR_LA_ENTRADA_DE_LOREBOOK.format(label=label)):
            self.app.remove_lore_entry(self.index)


def _lore_entry_matches_search(entry: LoreEntry, query: str) -> bool:
    """True si `entry` deberia mostrarse bajo `query` (ya en minusculas y sin
    espacios sobrantes): subcadena, sin distinguir mayusculas, contra el
    nombre o cualquiera de las palabras clave."""
    if not query:
        return True
    if query in entry.name.lower():
        return True
    return any(query in keyword.lower() for keyword in entry.keyword_list())


class LorebookTabMixin:
    """Pestana Lorebook de StoryForgeApp."""

    # ---------------- Lorebook ----------------
    def _build_lorebook_tab(self) -> None:
        tab = self.tab_lorebook
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                S.EL_LOREBOOK_GUARDA_PERSONAJES_SECUNDARIOS
            ),
            wraplength=900, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        self.add_lore_btn = ctk.CTkButton(top, text=S.AGREGAR_ENTRADA, command=self.add_lore_entry)
        self.add_lore_btn.pack(side="left")
        ctk.CTkLabel(top, text=S.MAXIMO_ENTRADAS.format(MAX_LORE_ENTRIES=MAX_LORE_ENTRIES)).pack(side="left", padx=8)

        search_row = ctk.CTkFrame(tab, fg_color="transparent")
        search_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        search_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search_row, text=S.BUSCAR_ETIQUETA).grid(row=0, column=0, padx=(0, 6))
        self.lore_search_entry = ctk.CTkEntry(search_row, placeholder_text=S.FILTRAR_POR_NOMBRE_O_PALABRA)
        self.lore_search_entry.grid(row=0, column=1, sticky="ew")
        # Filtra con una pequena espera tras la ultima tecla (F11).
        self.lore_search_entry.bind("<KeyRelease>", lambda _e: self._schedule_lore_filter())

        self.lorebook_scroll = ctk.CTkScrollableFrame(tab)
        self.lorebook_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.lorebook_scroll.grid_columnconfigure(0, weight=1)
        self._lore_placeholder = ctk.CTkLabel(self.lorebook_scroll, text="", text_color=COLOR_MUTED,
                                              wraplength=800, justify="left")
        self._render_lore_entries()

    def _schedule_lore_filter(self) -> None:
        if self._lore_filter_after is not None:
            try:
                self.after_cancel(self._lore_filter_after)
            except Exception:  # noqa: BLE001
                pass
        self._lore_filter_after = self.after(LORE_FILTER_DEBOUNCE_MS, self._render_lore_entries)

    def add_lore_entry(self) -> None:
        if not self.project.can_add_lore_entry():
            messagebox.showinfo(APP_TITLE, S.YA_HAY_ENTRADAS_EL_MAXIMO.format(MAX_LORE_ENTRIES=MAX_LORE_ENTRIES))
            return
        self.project.add_lore_entry()
        self._render_lore_entries()
        self.schedule_dirty_check()

    def remove_lore_entry(self, index: int) -> None:
        self._sync_lore_panels()
        entry = self.project.lore_entries.pop(index)
        panel = self._lore_panel_cache.pop(id(entry), None)
        if panel is not None:
            panel.destroy()
        self._render_lore_entries()
        self.schedule_dirty_check()

    def _sync_lore_panels(self) -> None:
        for panel in self._lore_panel_cache.values():
            panel.sync_to_model()

    def _clear_lore_panels(self) -> None:
        for panel in self._lore_panel_cache.values():
            panel.destroy()
        self._lore_panel_cache = {}
        self.lore_panels = []

    def _render_lore_entries(self) -> None:
        """Muestra las entradas que pasan el filtro de busqueda. Reutiliza los
        paneles existentes (solo los oculta/muestra) en vez de destruir y
        recrear todos en cada tecla (F11); crea solo los que faltan."""
        self._lore_filter_after = None
        self._sync_lore_panels()
        current = {id(e): (i, e) for i, e in enumerate(self.project.lore_entries)}
        for key in [k for k in self._lore_panel_cache if k not in current]:
            self._lore_panel_cache.pop(key).destroy()
        query = self.lore_search_entry.get().strip().lower() if hasattr(self, "lore_search_entry") else ""
        self.lore_panels = []
        row = 0
        for i, entry in enumerate(self.project.lore_entries):
            panel = self._lore_panel_cache.get(id(entry))
            matched = id(entry) in self.last_lore_match_ids
            reason = self.last_lore_reasons.get(id(entry), "")
            if panel is None:
                panel = LoreEntryPanel(self.lorebook_scroll, self, i, entry,
                                       matched_last_generation=matched, match_reason=reason)
                self._lore_panel_cache[id(entry)] = panel
            else:
                panel.index = i
                panel.set_match(matched, reason)
            if _lore_entry_matches_search(entry, query):
                panel.grid(row=row, column=0, sticky="ew", pady=6)
                self.lore_panels.append(panel)
                row += 1
            else:
                panel.grid_remove()
        if not self.project.lore_entries:
            self._lore_placeholder.configure(text=S.AUN_NO_HAY_ENTRADAS_DE)
            self._lore_placeholder.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        elif not self.lore_panels:
            self._lore_placeholder.configure(text=S.NINGUNA_ENTRADA_COINCIDE_CON_LA)
            self._lore_placeholder.grid(row=0, column=0, sticky="w", padx=8, pady=8)
        else:
            self._lore_placeholder.grid_remove()
        self.add_lore_btn.configure(state="normal" if self.project.can_add_lore_entry() else "disabled")
        if self.busy:
            self._set_engine_busy(True)

    def _record_lore_matches(self, chapter_index: int) -> None:
        """
        Recalcula que entradas del lorebook coincidieron con el texto de
        escaneo de la generacion que acaba de terminar (esquema + capitulos
        previos + final del capitulo) y por que (palabra clave, siempre
        incluida, o mencionada en otra entrada), para la marca "usada en la
        ultima generacion" de la pestana Lorebook.
        """
        if not (0 <= chapter_index < len(self.project.chapters)):
            return
        chapter = self.project.chapters[chapter_index]
        previous = build_previous_context(self.project, chapter_index)
        scan_text = build_lore_scan_text(chapter, previous, chapter.content)
        matches = match_lore_entries(self.project.lore_entries, scan_text)
        self.last_lore_match_ids = {id(m.entry) for m in matches}
        self.last_lore_reasons = {id(m.entry): m.reason_es() for m in matches}
        self._render_lore_entries()
