"""
Pestana Lorebook: LoreEntryPanel (una entrada), el filtro de busqueda y
LorebookTabMixin (alta/baja, filtrado sin reconstruir paneles, coincidencias
de la ultima generacion).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from typing import TYPE_CHECKING

from pathlib import Path

import customtkinter as ctk

from . import strings_es as S
from .project import (
    MAX_LORE_ENTRIES,
    LoreEntry,
    format_progressions,
    parse_progressions,
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
from .settings import get_pixelflow_settings, set_pixelflow_workflow
from .lore_tools import detect_new_names, format_relations, mention_counts, parse_relations
from .task_runner import call_supported
from .ui_focus import apply_tab_order

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
        self.enabled_check = ctk.CTkCheckBox(options, text=S.ACTIVA, variable=self.enabled_var)
        self.enabled_check.pack(side="left", padx=(0, 12))
        self.constant_check = ctk.CTkCheckBox(options, text=S.INCLUIR_SIEMPRE, variable=self.constant_var)
        self.constant_check.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(options, text=S.PRIORIDAD).pack(side="left", padx=(0, 4))
        self.priority_entry = ctk.CTkEntry(options, width=50)
        self.priority_entry.insert(0, str(entry.priority))
        self.priority_entry.pack(side="left")

        ctk.CTkLabel(self, text=S.TEXTO_ETIQUETA).grid(row=3, column=0, padx=8, pady=(2, 8), sticky="nw")
        self.text_box = ctk.CTkTextbox(self, height=80, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.text_box.insert("1.0", entry.text)
        self.text_box.edit_reset()
        self.text_box.grid(row=3, column=1, columnspan=2, padx=8, pady=(2, 8), sticky="ew")
        # Progresiones (F17): versiones desde un capitulo, editadas como texto.
        ctk.CTkLabel(self, text=S.PROGRESIONES_ETIQUETA).grid(row=4, column=0, padx=8, pady=(0, 8), sticky="nw")
        self.progressions_box = ctk.CTkTextbox(self, height=60, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.progressions_box.insert("1.0", format_progressions(entry.progressions))
        self.progressions_box.edit_reset()
        self.progressions_box.grid(row=4, column=1, columnspan=2, padx=8, pady=(0, 2), sticky="ew")
        ctk.CTkLabel(self, text=S.PROGRESIONES_AYUDA, text_color=COLOR_MUTED, wraplength=640, justify="left",
                     font=ctk.CTkFont(size=11)).grid(row=5, column=1, columnspan=2, padx=8, pady=(0, 8), sticky="w")
        # Alias y relaciones (F24).
        ctk.CTkLabel(self, text=S.ALIAS_ETIQUETA).grid(row=6, column=0, padx=8, pady=2, sticky="w")
        self.aliases_entry = ctk.CTkEntry(self, placeholder_text=S.P_EJ_ALIAS)
        self.aliases_entry.insert(0, entry.aliases)
        self.aliases_entry.grid(row=6, column=1, columnspan=2, padx=8, pady=2, sticky="ew")
        ctk.CTkLabel(self, text=S.RELACIONES_ETIQUETA).grid(row=7, column=0, padx=8, pady=2, sticky="nw")
        self.relations_box = ctk.CTkTextbox(self, height=48, wrap="word", **UNDO_TEXTBOX_OPTIONS)
        self.relations_box.insert("1.0", format_relations(entry.relations))
        self.relations_box.edit_reset()
        self.relations_box.grid(row=7, column=1, columnspan=2, padx=8, pady=2, sticky="ew")
        # Menciones (F24), visualizar (F25) y serie (F26).
        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=8, column=1, columnspan=3, sticky="w", padx=8, pady=(2, 8))
        self.mentions_btn = ctk.CTkButton(tools, text=S.VER_MENCIONES, width=110,
                                          command=lambda: app.show_lore_mentions(self))
        self.mentions_btn.pack(side="left", padx=(0, 6))
        self.visualize_btn = ctk.CTkButton(tools, text=S.VISUALIZAR, width=110,
                                           command=lambda: app.visualize_lore_entry(self))
        self.visualize_btn.pack(side="left", padx=(0, 6))
        self.shared_var = ctk.BooleanVar(value=entry.shared)
        self.shared_check = ctk.CTkCheckBox(tools, text=S.COMPARTIDA_EN_LA_SERIE, variable=self.shared_var,
                                            command=lambda: app.set_lore_entry_shared(self, bool(self.shared_var.get())))
        if app.project.series_path:
            self.shared_check.pack(side="left", padx=(0, 6))
        self.mentions_label = ctk.CTkLabel(self, text="", text_color=COLOR_MUTED, wraplength=640, justify="left",
                                           font=ctk.CTkFont(size=11))
        self.mentions_label.grid(row=9, column=1, columnspan=2, padx=8, pady=(0, 6), sticky="w")
        self.thumbnail_label = tk.Label(self, borderwidth=0)
        self._thumbnail_image = None
        self.show_thumbnail()
        apply_tab_order(self, self.focus_order_widgets())

    def show_thumbnail(self) -> None:
        """La miniatura de la entrada (F25), con el PNG de Tk (sin Pillow)."""
        if not self.entry.thumbnail:
            self.thumbnail_label.grid_remove()
            return
        try:
            self._thumbnail_image = tk.PhotoImage(master=self, data=self.entry.thumbnail)
        except tk.TclError:
            self.thumbnail_label.grid_remove()
            return
        factor = max(1, -(-max(self._thumbnail_image.width(), self._thumbnail_image.height()) // 128))
        if factor > 1:
            self._thumbnail_image = self._thumbnail_image.subsample(factor)
        self.thumbnail_label.configure(image=self._thumbnail_image)
        self.thumbnail_label.grid(row=3, column=3, rowspan=4, padx=8, pady=4, sticky="ne")

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
        self.entry.progressions = parse_progressions(self.progressions_box.get("1.0", "end-1c"))
        self.entry.aliases = self.aliases_entry.get().strip()
        self.entry.relations = parse_relations(self.relations_box.get("1.0", "end-1c"))
        try:
            self.entry.priority = max(-100, min(int(self.priority_entry.get()), 100))
        except ValueError:
            pass

    def _on_remove(self) -> None:
        label = self.entry.name.strip() or S.ENTRADA.format(number=self.index + 1)
        if messagebox.askyesno(APP_TITLE, S.ELIMINAR_LA_ENTRADA_DE_LOREBOOK.format(label=label)):
            self.app.remove_lore_entry(self.index)

    def focus_order_widgets(self):
        return [
            self.name_entry, self.remove_btn, self.keywords_entry,
            self.enabled_check, self.constant_check, self.priority_entry, self.text_box, self.progressions_box,
            self.aliases_entry, self.relations_box, self.mentions_btn, self.visualize_btn,
        ]


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
        # F22: nombres del capitulo actual que el lorebook no conoce.
        self.detect_btn = ctk.CTkButton(top, text=S.DETECTAR_PERSONAJES, width=170, command=self.detect_characters)
        self.detect_btn.pack(side="left", padx=8)
        # F26: un lorebook compartido por varios proyectos.
        self.series_btn = ctk.CTkButton(top, text=S.VINCULAR_SERIE, width=150, command=self.link_series)
        self.series_btn.pack(side="left", padx=8)
        self.unlink_series_btn = ctk.CTkButton(top, text=S.DESVINCULAR_SERIE, width=120, command=self.unlink_series)
        self.series_label = ctk.CTkLabel(top, text="", text_color=COLOR_MUTED)
        self.series_label.pack(side="left", padx=8)
        self._refresh_series_row()

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
        entry = self._displayed_lore_entries()[index]
        if entry in self.project.series_entries:
            self.project.series_entries.remove(entry)
        else:
            self.project.lore_entries.remove(entry)
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
        current = {id(e): (i, e) for i, e in enumerate(self._displayed_lore_entries())}
        for key in [k for k in self._lore_panel_cache if k not in current]:
            self._lore_panel_cache.pop(key).destroy()
        query = self.lore_search_entry.get().strip().lower() if hasattr(self, "lore_search_entry") else ""
        self.lore_panels = []
        row = 0
        for i, entry in enumerate(self._displayed_lore_entries()):
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
        if not self._displayed_lore_entries():
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
        apply_tab_order(
            self.tab_lorebook,
            self.add_lore_btn, self.lore_search_entry,
            [panel.focus_order_widgets() for panel in self.lore_panels],
        )

    # ---------------- serie, deteccion, menciones, visualizar (F22, F24-F26) ----------------
    def _displayed_lore_entries(self):
        """Las entradas del proyecto y, debajo, las de la serie (F26)."""
        return list(self.project.lore_entries) + list(self.project.series_entries)

    def _refresh_series_row(self) -> None:
        if self.project.series_path:
            self.series_label.configure(text=S.SERIE_VINCULADA.format(name=Path(self.project.series_path).name))
            self.unlink_series_btn.pack(side="left", padx=4, before=self.series_label)
        else:
            self.series_label.configure(text="")
            self.unlink_series_btn.pack_forget()

    def link_series(self) -> None:
        path = filedialog.asksaveasfilename(
            title=S.VINCULAR_SERIE, defaultextension=".sflore", confirmoverwrite=False,
            filetypes=[(S.LOREBOOK_DE_SERIE, "*.sflore"), (S.TODOS_LOS_ARCHIVOS, "*.*")],
        )
        if not path:
            return
        self._sync_lore_panels()
        try:
            self.project.link_series(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, S.NO_SE_PUDO_VINCULAR_SERIE.format(exc=exc))
            return
        self._clear_lore_panels()
        self._refresh_series_row()
        self._render_lore_entries()
        self.schedule_dirty_check()

    def unlink_series(self) -> None:
        if not messagebox.askyesno(APP_TITLE, S.DESVINCULAR_SERIE_PREGUNTA):
            return
        self._sync_lore_panels()
        self.project.unlink_series()
        self._clear_lore_panels()
        self._refresh_series_row()
        self._render_lore_entries()
        self.schedule_dirty_check()

    def set_lore_entry_shared(self, panel, shared: bool) -> None:
        panel.sync_to_model()
        self.project.set_entry_shared(panel.entry, shared)
        self._render_lore_entries()
        self.schedule_dirty_check()

    def show_lore_mentions(self, panel) -> None:
        panel.sync_to_model()
        counts = mention_counts(self.project.chapters, panel.entry)
        text = (S.MENCIONES_EN.format(lista=", ".join(S.CAP_N_VECES.format(n=n, veces=c) for n, c in counts))
                if counts else S.SIN_MENCIONES)
        panel.mentions_label.configure(text=text)

    def _current_chapter_index(self) -> int:
        index = getattr(self, "selected_chapter_index", None)
        if isinstance(index, int) and 0 <= index < len(self.project.chapters):
            return index
        return len(self.project.chapters) - 1

    def detect_characters(self) -> None:
        self._sync_lore_panels()
        index = self._current_chapter_index()
        if index < 0:
            messagebox.showinfo(APP_TITLE, S.NO_HAY_CAPITULOS_PARA_DETECTAR)
            return
        chapter = self.project.chapters[index]
        candidates = detect_new_names(chapter.content, self.project.all_lore_entries())
        if not candidates:
            messagebox.showinfo(APP_TITLE, S.NO_HAY_NOMBRES_NUEVOS.format(number=index + 1))
            return
        CharacterDetectionDialog(self, index, candidates)

    def create_lore_entries(self, picks, draft_with_model: bool) -> None:
        """Las entradas elegidas en la deteccion (F22); con el modelo, una descripcion breve de cada una."""
        created = []
        for candidate in picks:
            if not self.project.can_add_lore_entry():
                break
            created.append((self.project.add_lore_entry(name=candidate.name, keywords=candidate.name), candidate))
        self._render_lore_entries()
        self.schedule_dirty_check()
        if not draft_with_model or not created or not self.engine.is_loaded or self.busy:
            return
        engine, project = self.engine, self.project

        def work(cancel_check):
            drafts = []
            for entry, candidate in created:
                if cancel_check():
                    break
                drafts.append((entry, call_supported(engine.draft_lore_entry, project, candidate.name,
                                                      [candidate.example], cancel_check=cancel_check)))
            return drafts

        def on_success(drafts) -> None:
            for entry, text in drafts:
                if not entry.text.strip():
                    entry.text = text
                panel = self._lore_panel_cache.pop(id(entry), None)
                if panel is not None:
                    panel.destroy()
            self._render_lore_entries()
            self.schedule_dirty_check()

        self.task_runner.run(S.DETECTAR_PERSONAJES_OPERACION, work, on_success=on_success,
                             on_error=lambda exc: S.NO_SE_PUDIERON_DESCRIBIR.format(exc=exc))

    def visualize_lore_entry(self, panel) -> None:
        """F25: la descripcion de la entrada a un PixelFlow local; la imagen queda de miniatura."""
        from . import visualize

        panel.sync_to_model()
        entry = panel.entry
        if not entry.text.strip():
            messagebox.showinfo(APP_TITLE, S.ESCRIBE_UNA_DESCRIPCION_PRIMERO)
            return
        stored = get_pixelflow_settings()
        url = stored["url"]
        try:
            workflows = visualize.list_workflows(url)
        except visualize.VisualizeError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        if not workflows:
            messagebox.showinfo(APP_TITLE, S.PIXELFLOW_SIN_FLUJOS)
            return
        default = stored["workflow"] if stored["workflow"] in workflows else workflows[0]
        workflow = simpledialog.askstring(
            APP_TITLE, S.ELIGE_FLUJO_PIXELFLOW.format(lista=", ".join(workflows)), initialvalue=default, parent=self)
        if not workflow:
            return
        if workflow not in workflows:
            messagebox.showerror(APP_TITLE, S.FLUJO_NO_EXISTE.format(name=workflow))
            return
        set_pixelflow_workflow(workflow)
        prompt = visualize.portrait_prompt(entry.name, entry.text)

        def work(cancel_check):
            return visualize.generate_image(prompt, workflow, url, cancel_check=cancel_check)

        def on_success(image_bytes) -> None:
            entry.thumbnail = visualize.thumbnail_b64(image_bytes, master=self)
            panel.show_thumbnail()
            self.schedule_dirty_check()

        self.task_runner.run(S.VISUALIZAR, work, on_success=on_success, on_error=lambda exc: str(exc))

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
        matches = match_lore_entries(self.project.all_lore_entries(), scan_text)
        self.last_lore_match_ids = {id(m.entry) for m in matches}
        self.last_lore_reasons = {id(m.entry): m.reason_es() for m in matches}
        self._render_lore_entries()


class CharacterDetectionDialog(ctk.CTkToplevel):
    """F22: los nombres nuevos del capitulo, para crear sus entradas del lorebook."""

    def __init__(self, app, chapter_index: int, candidates):
        super().__init__(app)
        self.app = app
        self.candidates = candidates
        self.title(S.PERSONAJES_DETECTADOS.format(number=chapter_index + 1))
        self.geometry("560x460")
        ctk.CTkLabel(self, text=S.PERSONAJES_DETECTADOS_AYUDA, wraplength=520, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4))
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=4)
        self.vars = []
        for candidate in candidates:
            var = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(scroll, text=S.NOMBRE_Y_VECES.format(name=candidate.name, veces=candidate.count),
                            variable=var).pack(anchor="w", pady=(4, 0))
            ctk.CTkLabel(scroll, text=candidate.example, text_color=COLOR_MUTED, wraplength=480, justify="left",
                         font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24)
            self.vars.append(var)
        self.draft_var = ctk.BooleanVar(value=app.engine.is_loaded)
        draft = ctk.CTkCheckBox(self, text=S.DESCRIBIR_CON_EL_MODELO, variable=self.draft_var)
        if not app.engine.is_loaded:
            draft.configure(state="disabled")
        draft.pack(anchor="w", padx=10, pady=4)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(buttons, text=S.CREAR_ENTRADAS, command=self._create).pack(side="right")
        ctk.CTkButton(buttons, text=S.CANCELAR, command=self.destroy).pack(side="right", padx=6)

    def _create(self) -> None:
        picks = [c for c, var in zip(self.candidates, self.vars) if var.get()]
        self.destroy()
        self.app.create_lore_entries(picks, bool(self.draft_var.get()))
