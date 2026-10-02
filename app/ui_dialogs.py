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

from .project import Project

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
        ctk.CTkLabel(self, text="Antes", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        ctk.CTkLabel(
            self, text=f"Después  (+{added} / -{removed} palabras)", font=ctk.CTkFont(weight="bold"),
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
        ctk.CTkButton(buttons, text="Descartar", width=110, fg_color="#8a3b3b", hover_color="#6e2f2f",
                      command=self.discard).pack(side="left", padx=4)
        if on_accept_continue is not None:
            ctk.CTkButton(buttons, text="Aceptar y seguir refinando", width=200,
                          command=self.accept_and_continue).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Aceptar", width=110, command=self.accept).pack(side="left", padx=4)
        self.protocol("WM_DELETE_WINDOW", self.discard)
        self.bind("<Escape>", lambda _e: self.discard())

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
        ctk.CTkButton(bar, text="Copiar", width=90, command=lambda: self._copy(text)).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Cerrar", width=90, command=self.destroy).pack(side="left", padx=4)

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)


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
    "plot": "Plot", "characters": "Personajes", "setting": "Setting",
    "chapter": "Capítulo", "outline": "Esquema", "summary": "Resumen", "lore": "Lorebook",
}


def _pattern(query: str, case_sensitive: bool, whole_word: bool) -> Optional[re.Pattern]:
    if not query:
        return None
    body = re.escape(query)
    if whole_word:
        body = rf"\b{body}\b"
    return re.compile(body, 0 if case_sensitive else re.IGNORECASE)


def _project_fields(project: Project):
    yield "plot", -1, "Plot", project.plot
    yield "characters", -1, "Personajes", project.characters
    yield "setting", -1, "Setting", project.setting
    for i, ch in enumerate(project.chapters):
        title = ch.title.strip() or f"Capítulo {i + 1}"
        yield "chapter", i, f"Capítulo {i + 1}: {title}", ch.content
        yield "outline", i, f"Esquema {i + 1}: {title}", ch.outline
        yield "summary", i, f"Resumen {i + 1}: {title}", ch.summary
    for i, entry in enumerate(project.lore_entries):
        yield "lore", i, f"Lorebook: {entry.name.strip() or f'entrada {i + 1}'}", entry.text


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
        self.title("Buscar en todo el proyecto")
        self.geometry("820x560")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text="Buscar:").grid(row=0, column=0, padx=(0, 6))
        self.query_entry = ctk.CTkEntry(top)
        self.query_entry.grid(row=0, column=1, sticky="ew")
        self.query_entry.insert(0, initial)
        ctk.CTkButton(top, text="Buscar", width=90, command=self.search).grid(row=0, column=2, padx=6)
        ctk.CTkLabel(top, text="Reemplazar con:").grid(row=1, column=0, padx=(0, 6), pady=(6, 0))
        self.replace_entry = ctk.CTkEntry(top)
        self.replace_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ctk.CTkButton(top, text="Reemplazar todo", width=130, command=self.replace_all).grid(row=1, column=2, padx=6, pady=(6, 0))

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.grid(row=1, column=0, sticky="ew", padx=10)
        self.case_var = ctk.BooleanVar(value=False)
        self.word_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts, text="Distinguir mayúsculas", variable=self.case_var).pack(side="left", padx=(0, 12))
        ctk.CTkCheckBox(opts, text="Palabra completa", variable=self.word_var).pack(side="left")
        self.summary_label = ctk.CTkLabel(opts, text="", text_color=COLOR_MUTED)
        self.summary_label.pack(side="left", padx=12)

        self.results = ctk.CTkScrollableFrame(self)
        self.results.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.results.grid_columnconfigure(0, weight=1)
        self.hits: List[SearchHit] = []
        self.query_entry.bind("<Return>", lambda _e: self.search())
        if initial:
            self.search()

    def _options(self):
        return self.case_var.get(), self.word_var.get()

    def search(self) -> List[SearchHit]:
        self.app._sync_all()
        case, word = self._options()
        self.hits = find_in_project(self.app.project, self.query_entry.get(), case, word)
        for child in self.results.winfo_children():
            child.destroy()
        for row, hit in enumerate(self.hits[:300]):
            ctk.CTkButton(
                self.results, text=f"{hit.label}\n{hit.snippet}", anchor="w", fg_color="transparent",
                text_color=("#1a1a1a", "#e6e6e6"), hover_color=("#d0d0d0", "#3a3a3a"),
                command=lambda h=hit: self.app.jump_to_search_hit(h, self.query_entry.get()),
            ).grid(row=row, column=0, sticky="ew", pady=1)
        more = " (se muestran 300)" if len(self.hits) > 300 else ""
        self.summary_label.configure(text=f"{len(self.hits)} resultados{more}")
        return self.hits

    def replace_all(self) -> int:
        case, word = self._options()
        count = self.app.replace_in_project(self.query_entry.get(), self.replace_entry.get(), case, word)
        self.summary_label.configure(text=f"{count} reemplazos")
        self.search()
        return count


class PreferencesDialog(ctk.CTkToplevel):
    """Tema, escala, fuente/interlineado del editor y carpeta de modelos."""

    def __init__(self, app, prefs: dict, on_save: Callable[[dict], None]):
        super().__init__(app)
        self.title("Preferencias")
        self.geometry("560x380")
        self._on_save = on_save
        self.grid_columnconfigure(1, weight=1)
        row = 0

        def label(text):
            ctk.CTkLabel(self, text=text).grid(row=row, column=0, sticky="w", padx=10, pady=6)

        label("Tema:")
        self.theme_menu = ctk.CTkOptionMenu(self, values=["Oscuro", "Claro", "Sistema"])
        self.theme_menu.set({"dark": "Oscuro", "light": "Claro", "system": "Sistema"}.get(prefs.get("appearance"), "Oscuro"))
        self.theme_menu.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label("Escala de la interfaz:")
        self.scale_menu = ctk.CTkOptionMenu(self, values=["90%", "100%", "110%", "125%", "150%"])
        self.scale_menu.set(f"{int(round(float(prefs.get('ui_scale', 1.0)) * 100))}%")
        self.scale_menu.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label("Fuente del editor (vacío = por defecto):")
        self.font_entry = ctk.CTkEntry(self)
        self.font_entry.insert(0, prefs.get("editor_font_family", ""))
        self.font_entry.grid(row=row, column=1, sticky="ew", padx=10)
        row += 1
        label("Tamaño de fuente del editor:")
        self.size_entry = ctk.CTkEntry(self, width=60)
        self.size_entry.insert(0, str(prefs.get("editor_font_size", 14)))
        self.size_entry.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label("Interlineado (píxeles):")
        self.spacing_entry = ctk.CTkEntry(self, width=60)
        self.spacing_entry.insert(0, str(prefs.get("editor_line_spacing", 4)))
        self.spacing_entry.grid(row=row, column=1, sticky="w", padx=10)
        row += 1
        label("Carpeta de modelos adicional:")
        self.models_entry = ctk.CTkEntry(self)
        self.models_entry.insert(0, prefs.get("models_dir", ""))
        self.models_entry.grid(row=row, column=1, sticky="ew", padx=10)
        row += 1
        ctk.CTkLabel(
            self, text="Consejo: guarda los modelos .gguf fuera de OneDrive (p.ej. C:\\Modelos) para que "
                       "no se sincronicen ni queden \"solo en línea\".",
            wraplength=520, justify="left", text_color=COLOR_MUTED,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 6))
        row += 1
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=row, column=0, columnspan=2, sticky="e", padx=10, pady=10)
        ctk.CTkButton(bar, text="Cancelar", width=90, command=self.destroy).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Guardar", width=90, command=self.save).pack(side="left", padx=4)

    def values(self) -> dict:
        def as_int(entry, default, lo, hi):
            try:
                return max(lo, min(int(entry.get()), hi))
            except ValueError:
                return default
        return {
            "appearance": {"Oscuro": "dark", "Claro": "light", "Sistema": "system"}[self.theme_menu.get()],
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
