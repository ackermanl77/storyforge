"""
Ventanas secundarias de la interfaz (F4/F5/F2/F9/K3):

- DiffPreviewDialog: vista previa lado a lado con diferencias palabra por
  palabra antes de aplicar un refinado o una reescritura de seleccion
  (Aceptar / Descartar / Aceptar y seguir refinando).
- PromptViewerDialog: el prompt exacto enviado al modelo ("Ver prompt").
- ProjectSearchDialog: buscar (y reemplazar) en todo el proyecto.
- AboutDialog: version, llama-cpp-python, GPU, carpeta de registros.
- PreferencesDialog: tema, escala, fuente del editor, interlineado,
  carpeta de modelos adicional, limite de versiones.

Las funciones puras (word_diff, find_in_project) se prueban sin ventana.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import customtkinter as ctk

from . import strings_es as S
from .project import Project
from .ui_focus import apply_tab_order

# Colores con variante clara/oscura (CustomTkinter acepta tuplas).
COLOR_INSERT_BG = ("#c8efc8", "#1f4d2a")
COLOR_DELETE_BG = ("#f6c6c6", "#5a2323")
COLOR_MUTED = ("#555555", "#b0b0b0")
COLOR_OK = ("#2e7d32", "#66bb6a")
COLOR_WARN = ("#9a6200", "#e0a030")
COLOR_ERROR = ("#b3261e", "#ef6b6b")

_TOKEN_RE = re.compile(r"\s+|[^\s]+")


def word_diff(old: str, new: str) -> List[Tuple[str, str]]:
    """Diferencias por palabras: lista de (etiqueta, texto) con etiqueta
    "equal", "delete" (solo en el viejo) o "insert" (solo en el nuevo)."""
    a = _TOKEN_RE.findall(old or "")
    b = _TOKEN_RE.findall(new or "")
    out: List[Tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.append(("equal", "".join(a[i1:i2])))
            continue
        if tag in ("delete", "replace"):
            out.append(("delete", "".join(a[i1:i2])))
        if tag in ("insert", "replace"):
            out.append(("insert", "".join(b[j1:j2])))
    return out


def diff_stats(ops: List[Tuple[str, str]]) -> Tuple[int, int]:
    """(palabras agregadas, palabras quitadas)."""
    added = sum(len(t.split()) for tag, t in ops if tag == "insert")
    removed = sum(len(t.split()) for tag, t in ops if tag == "delete")
    return added, removed


class DiffPreviewDialog(ctk.CTkToplevel):
    """Muestra `old` (izquierda, lo quitado en rojo) y `new` (derecha, lo
    agregado en verde). Nada cambia hasta que el usuario acepta."""

    def __init__(self, master, title: str, old: str, new: str,
                 on_accept: Callable[[str], None],
                 on_accept_continue: Optional[Callable[[str], None]] = None,
                 on_discard: Optional[Callable[[], None]] = None):
        super().__init__(master)
        self.title(title)
        self.geometry("1100x650")
        self.new_text = new
        self._on_accept = on_accept
        self._on_accept_continue = on_accept_continue
        self._on_discard = on_discard
        self.decided = False
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(1, weight=1)

        ops = word_diff(old, new)
        added, removed = diff_stats(ops)
        ctk.CTkLabel(self, text=S.ANTES, font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        ctk.CTkLabel(
            self, text=S.DESPUES_PALABRAS.format(added=added, removed=removed), font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=1, sticky="w", padx=10, pady=(10, 0))
        self.old_box = ctk.CTkTextbox(self, wrap="word")
        self.new_box = ctk.CTkTextbox(self, wrap="word")
        self.old_box.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=6)
        self.new_box.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=6)
        mode = 1 if ctk.get_appearance_mode() == "Dark" else 0
        self.old_box.tag_config("delete", background=COLOR_DELETE_BG[mode], overstrike=True)
        self.new_box.tag_config("insert", background=COLOR_INSERT_BG[mode])
        for tag, text in ops:
            if tag in ("equal", "delete"):
                self.old_box.insert("end", text, tag if tag == "delete" else ())
            if tag in ("equal", "insert"):
                self.new_box.insert("end", text, tag if tag == "insert" else ())
        self.old_box.configure(state="disabled")
        self.new_box.configure(state="disabled")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))
        self.discard_btn = ctk.CTkButton(
            buttons, text=S.DESCARTAR, width=110, fg_color="#8a3b3b", hover_color="#6e2f2f",
            command=self.discard,
        )
        self.discard_btn.pack(side="left", padx=4)
        self.accept_continue_btn = None
        if on_accept_continue is not None:
            self.accept_continue_btn = ctk.CTkButton(
                buttons, text=S.ACEPTAR_Y_SEGUIR_REFINANDO, width=200, command=self.accept_and_continue,
            )
            self.accept_continue_btn.pack(side="left", padx=4)
        self.accept_btn = ctk.CTkButton(buttons, text=S.ACEPTAR, width=110, command=self.accept)
        self.accept_btn.pack(side="left", padx=4)
        self.protocol("WM_DELETE_WINDOW", self.discard)
        self.bind("<Escape>", lambda _e: self.discard())
        apply_tab_order(self, self.old_box, self.new_box, self.discard_btn, self.accept_continue_btn, self.accept_btn)

    def _close(self) -> None:
        self.decided = True
        try:
            self.destroy()
        except Exception:  # noqa: BLE001
            pass

    def accept(self) -> None:
        if self.decided:
            return
        self._close()
        self._on_accept(self.new_text)

    def accept_and_continue(self) -> None:
        if self.decided or self._on_accept_continue is None:
            return
        self._close()
        self._on_accept_continue(self.new_text)

    def discard(self) -> None:
        if self.decided:
            return
        self._close()
        if self._on_discard is not None:
            self._on_discard()


class TextViewerDialog(ctk.CTkToplevel):
    """Texto de solo lectura con boton Copiar (p.ej. "Ver prompt")."""

    def __init__(self, master, title: str, text: str, header: str = ""):
        super().__init__(master)
        self.title(title)
        self.geometry("900x650")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=header, justify="left", wraplength=860).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.box = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.box.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        self.box.insert("1.0", text)
        self.box.configure(state="disabled")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="e", padx=10, pady=(0, 10))
        self.copy_btn = ctk.CTkButton(bar, text=S.COPIAR, width=90, command=lambda: self._copy(text))
        self.copy_btn.pack(side="left", padx=4)
        self.close_btn = ctk.CTkButton(bar, text=S.CERRAR, width=90, command=self.destroy)
        self.close_btn.pack(side="left", padx=4)
        apply_tab_order(self, self.box, self.copy_btn, self.close_btn)

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)


class PhraseListDialog(ctk.CTkToplevel):
    """Editor de las frases a evitar propias del proyecto (una por linea)."""

    def __init__(self, master, phrases: List[str], defaults, on_save: Callable[[List[str]], None]):
        super().__init__(master)
        self.title(S.FRASES_A_EVITAR_TITULO)
        self.geometry("720x520")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._on_save = on_save
        ctk.CTkLabel(self, text=S.FRASES_A_EVITAR_AYUDA, justify="left", wraplength=680).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.box = ctk.CTkTextbox(self, wrap="none")
        self.box.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        self.box.insert("1.0", "\n".join(phrases))
        ctk.CTkLabel(self, text=S.FRASES_INCORPORADAS.format(phrases=" · ".join(defaults)), justify="left",
                     wraplength=680, text_color="gray").grid(row=2, column=0, sticky="w", padx=10)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="e", padx=10, pady=(4, 10))
        self.save_btn = ctk.CTkButton(bar, text=S.GUARDAR, width=90, command=self.save)
        self.save_btn.pack(side="left", padx=4)
        self.cancel_btn = ctk.CTkButton(bar, text=S.CANCELAR, width=90, command=self.destroy)
        self.cancel_btn.pack(side="left", padx=4)
        apply_tab_order(self, self.box, self.save_btn, self.cancel_btn)

    def phrases(self) -> List[str]:
        from .phrase_guard import clean_phrases

        return clean_phrases(self.box.get("1.0", "end").splitlines())

    def save(self) -> None:
        self._on_save(self.phrases())
        self.destroy()


# ---------------------------------------------------------------- busqueda en el proyecto
@dataclass
class SearchHit:
    field: str  # "plot", "characters", "setting", "chapter", "outline", "summary", "lore"
    index: int  # capitulo o entrada de lorebook (-1 si no aplica)
    label: str
    start: int
    end: int
    snippet: str


FIELD_LABELS = {
    "plot": S.TAB_PLOT, "characters": S.TAB_PERSONAJES, "setting": S.TAB_SETTING,
    "chapter": S.CAPITULO, "outline": S.TAB_ESQUEMA, "summary": S.RESUMEN, "lore": S.TAB_LOREBOOK,
}


def _pattern(query: str, case_sensitive: bool, whole_word: bool) -> Optional[re.Pattern]:
    if not query:
        return None
    body = re.escape(query)
    if whole_word:
        body = rf"\b{body}\b"
    return re.compile(body, 0 if case_sensitive else re.IGNORECASE)


def _project_fields(project: Project):
    yield "plot", -1, S.TAB_PLOT, project.plot
    yield "characters", -1, S.TAB_PERSONAJES, project.characters
    yield "setting", -1, S.TAB_SETTING, project.setting
    for i, ch in enumerate(project.chapters):
        title = ch.title.strip() or S.CAPITULO_N.format(number=i + 1)
        yield "chapter", i, S.CAPITULO_N_TITULO.format(number=i + 1, title=title), ch.content
        yield "outline", i, S.ESQUEMA_N_TITULO.format(number=i + 1, title=title), ch.outline
        yield "summary", i, S.RESUMEN_N_TITULO.format(number=i + 1, title=title), ch.summary
    for i, entry in enumerate(project.all_lore_entries()):
        yield "lore", i, S.LOREBOOK_ENTRADA.format(name=entry.name.strip() or S.ENTRADA.format(number=i + 1)), entry.text


def find_in_project(project: Project, query: str, case_sensitive: bool = False,
                    whole_word: bool = False) -> List[SearchHit]:
    pattern = _pattern(query, case_sensitive, whole_word)
    if pattern is None:
        return []
    hits: List[SearchHit] = []
    for field, index, label, text in _project_fields(project):
        for m in pattern.finditer(text or ""):
            a, b = max(0, m.start() - 40), min(len(text), m.end() + 40)
            snippet = ("..." if a else "") + text[a:b].replace("\n", " ") + ("..." if b < len(text) else "")
            hits.append(SearchHit(field, index, label, m.start(), m.end(), snippet))
    return hits


def replace_in_text(text: str, query: str, replacement: str, case_sensitive: bool = False,
                    whole_word: bool = False) -> Tuple[str, int]:
    pattern = _pattern(query, case_sensitive, whole_word)
    if pattern is None:
        return text, 0
    return pattern.subn(lambda _m: replacement, text)


class ProjectSearchDialog(ctk.CTkToplevel):
    """Buscar en todo el proyecto (capitulos, esquema, resumenes, plot,
    personajes, setting, lorebook), con salto al resultado y reemplazar
    todo (cada capitulo modificado guarda una version en el historial)."""

    def __init__(self, app, initial: str = ""):
        super().__init__(app)
        self.app = app
        self.title(S.BUSCAR_EN_PROYECTO_TITULO)
        self.geometry("820x560")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text=S.BUSCAR_ETIQUETA).grid(row=0, column=0, padx=(0, 6))
        self.query_entry = ctk.CTkEntry(top)
        self.query_entry.grid(row=0, column=1, sticky="ew")
        self.query_entry.insert(0, initial)
        self.search_btn = ctk.CTkButton(top, text=S.BUSCAR, width=90, command=self.search)
        self.search_btn.grid(row=0, column=2, padx=6)
        ctk.CTkLabel(top, text=S.REEMPLAZAR_CON).grid(row=1, column=0, padx=(0, 6), pady=(6, 0))
        self.replace_entry = ctk.CTkEntry(top)
        self.replace_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.replace_all_btn = ctk.CTkButton(top, text=S.REEMPLAZAR_TODO, width=130, command=self.replace_all)
        self.replace_all_btn.grid(row=1, column=2, padx=6, pady=(6, 0))

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.grid(row=1, column=0, sticky="ew", padx=10)
        self.case_var = ctk.BooleanVar(value=False)
        self.word_var = ctk.BooleanVar(value=False)
        self.case_check = ctk.CTkCheckBox(opts, text=S.DISTINGUIR_MAYUSCULAS, variable=self.case_var)
        self.case_check.pack(side="left", padx=(0, 12))
        self.word_check = ctk.CTkCheckBox(opts, text=S.PALABRA_COMPLETA, variable=self.word_var)
        self.word_check.pack(side="left")
        self.summary_label = ctk.CTkLabel(opts, text="", text_color=COLOR_MUTED)
        self.summary_label.pack(side="left", padx=12)

        self.results = ctk.CTkScrollableFrame(self)
        self.results.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.results.grid_columnconfigure(0, weight=1)
        self.hits: List[SearchHit] = []
        self.result_buttons: List[ctk.CTkButton] = []
        self.query_entry.bind("<Return>", lambda _e: self.search())
        if initial:
            self.search()
        else:
            self._bind_tab_order()

    def _options(self):
        return self.case_var.get(), self.word_var.get()

    def search(self) -> List[SearchHit]:
        self.app._sync_all()
        case, word = self._options()
        self.hits = find_in_project(self.app.project, self.query_entry.get(), case, word)
        for child in self.results.winfo_children():
            child.destroy()
        self.result_buttons = []
        for row, hit in enumerate(self.hits[:300]):
            btn = ctk.CTkButton(
                self.results, text=f"{hit.label}\n{hit.snippet}", anchor="w", fg_color="transparent",
                text_color=("#1a1a1a", "#e6e6e6"), hover_color=("#d0d0d0", "#3a3a3a"),
                command=lambda h=hit: self.app.jump_to_search_hit(h, self.query_entry.get()),
            )
            btn.grid(row=row, column=0, sticky="ew", pady=1)
            self.result_buttons.append(btn)
        more = S.SE_MUESTRAN_300 if len(self.hits) > 300 else ""
        self.summary_label.configure(text=S.RESULTADOS.format(count=len(self.hits), more=more))
        self._bind_tab_order()
        return self.hits

    def replace_all(self) -> int:
        case, word = self._options()
        count = self.app.replace_in_project(self.query_entry.get(), self.replace_entry.get(), case, word)
        self.summary_label.configure(text=S.REEMPLAZOS.format(count=count))
        self.search()
        return count

    def _bind_tab_order(self) -> None:
        apply_tab_order(
            self,
            self.query_entry, self.search_btn, self.replace_entry, self.replace_all_btn,
            self.case_check, self.word_check, self.result_buttons,
        )


class PreferencesDialog(ctk.CTkToplevel):
    """Tema, escala, fuente/interlineado del editor y carpeta de modelos."""

    def __init__(self, app, prefs: dict, on_save: Callable[[dict], None]):
        super().__init__(app)
        self.title(S.PREFERENCIAS)
        self.geometry("560x380")
        self._on_save = on_save
        self.grid_columnconfigure(1, weight=1)
        row = 0

        def label(text):
            ctk.CTkLabel(self, text=text).grid(row=row, column=0, sticky="w", padx=10, pady=6)

        label(S.TEMA)
        self.theme_menu = ctk.CTkOptionMenu(self, values=[S.OSCURO, S.CLARO, S.SISTEMA])
        self.theme_menu.set({"dark": S.OSCURO, "light": S.CLARO, "system": S.SISTEMA}.get(prefs.get("appearance"), S.OSCURO))
        self.theme_menu.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label(S.ESCALA_DE_LA_INTERFAZ)
        self.scale_menu = ctk.CTkOptionMenu(self, values=["90%", "100%", "110%", "125%", "150%"])
        self.scale_menu.set(f"{int(round(float(prefs.get('ui_scale', 1.0)) * 100))}%")
        self.scale_menu.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label(S.FUENTE_DEL_EDITOR_VACIO_POR)
        self.font_entry = ctk.CTkEntry(self)
        self.font_entry.insert(0, prefs.get("editor_font_family", ""))
        self.font_entry.grid(row=row, column=1, sticky="ew", padx=10)
        row += 1
        label(S.TAMANO_DE_FUENTE_DEL_EDITOR)
        self.size_entry = ctk.CTkEntry(self, width=60)
        self.size_entry.insert(0, str(prefs.get("editor_font_size", 14)))
        self.size_entry.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label(S.INTERLINEADO_PIXELES)
        self.spacing_entry = ctk.CTkEntry(self, width=60)
        self.spacing_entry.insert(0, str(prefs.get("editor_line_spacing", 4)))
        self.spacing_entry.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label(S.CARPETA_DE_MODELOS_ADICIONAL)
        self.models_entry = ctk.CTkEntry(self)
        self.models_entry.insert(0, prefs.get("models_dir", ""))
        self.models_entry.grid(row=row, column=1, sticky="ew", padx=10)
        row += 1
        ctk.CTkLabel(
            self, text=S.CONSEJO_GUARDA_LOS_MODELOS_GGUF,
            wraplength=520, justify="left", text_color=COLOR_MUTED,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 6))
        row += 1
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=row, column=0, columnspan=2, sticky="e", padx=10, pady=10)
        self.cancel_btn = ctk.CTkButton(bar, text=S.CANCELAR, width=90, command=self.destroy)
        self.cancel_btn.pack(side="left", padx=4)
        self.save_btn = ctk.CTkButton(bar, text=S.GUARDAR, width=90, command=self.save)
        self.save_btn.pack(side="left", padx=4)
        apply_tab_order(
            self,
            self.theme_menu, self.scale_menu, self.font_entry,
            self.size_entry, self.spacing_entry, self.models_entry,
            self.cancel_btn, self.save_btn,
        )

    def values(self) -> dict:
        def as_int(entry, default, lo, hi):
            try:
                return max(lo, min(int(entry.get()), hi))
            except ValueError:
                return default
        return {
            "appearance": {S.OSCURO: "dark", S.CLARO: "light", S.SISTEMA: "system"}[self.theme_menu.get()],
            "ui_scale": int(self.scale_menu.get().rstrip("%")) / 100,
            "editor_font_family": self.font_entry.get().strip(),
            "editor_font_size": as_int(self.size_entry, 14, 8, 40),
            "editor_line_spacing": as_int(self.spacing_entry, 4, 0, 30),
            "models_dir": self.models_entry.get().strip(),
        }

    def save(self) -> None:
        values = self.values()
        self.destroy()
        self._on_save(values)
