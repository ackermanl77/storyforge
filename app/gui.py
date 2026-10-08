"""
Interfaz grafica de escritorio (CustomTkinter) para StoryForge Local: la
ventana principal (StoryForgeApp) con lo que es de toda la app --
preferencias, errores inesperados, exclusion mutua del motor, cambios sin
guardar, autoguardado, abrir/guardar/exportar -- y run().

Cada pestana y el menu son mixins en su propio modulo (F12):
app/ui_menu.py (menu y atajos), app/ui_model_tab.py (Modelo),
app/ui_story_tabs.py (Plot/Personajes/Setting), app/ui_lorebook_tab.py,
app/ui_outline_tab.py (Esquema), app/ui_chapters_tab.py (Capitulos) y
app/ui_chapter_editor.py (ChapterPanel, versiones anteriores); piezas
comunes en app/ui_common.py. Ademas: app/task_runner.py (tareas del modelo
en segundo plano), app/ui_status.py (barra de estado), app/ui_dialogs.py
(ventanas secundarias) y app/strings_es.py (todos los textos visibles).
"""
from __future__ import annotations

import logging
import os
import platform
import threading
import time
from tkinter import filedialog, messagebox
from typing import Dict, Optional

import customtkinter as ctk

from . import __version__
from . import strings_es as S
from .engine import (
    ContextOverflowError,  # noqa: F401 - reexportado para las pruebas
    LocalStoryEngine,
    ModelNotLoadedError,  # noqa: F401 - reexportado para las pruebas
    supports_gpu_offload,
)
from .export import export_docx, export_epub, export_markdown, export_txt
from .gguf import query_free_vram_bytes
from .paths import is_frozen, log_file_path, user_data_dir
from .project import (
    DEFAULT_PROJECT_NAME,
    MAX_CHAPTERS,
    WRITING_STYLES,
    Project,
    save_json_text,
)
from .settings import (
    get_ui_preferences,
    set_ui_preferences,
)
from .strings_es import (
    CHAPTER_HEADING_LABELS,
    CHAPTER_PURPOSE_DEFAULT_LABEL,
    WRITING_STYLE_DEFAULT_LABEL,
    style_key,
    style_label,
)
from .task_runner import EngineTaskRunner
from .ui_chapter_editor import ChapterPanel, VersionHistoryDialog
from .ui_chapters_tab import ChaptersTabMixin
from .ui_common import (
    APP_TITLE,
    MODELS_DIR,
)
from .ui_dialogs import (
    DiffPreviewDialog,
    PreferencesDialog,
    TextViewerDialog,
)
from .ui_lorebook_tab import LorebookTabMixin, LoreEntryPanel, _lore_entry_matches_search
from .ui_menu import MenuMixin
from .ui_model_tab import ModelTabMixin
from .ui_outline_tab import OutlinePanel, OutlineTabMixin
from .ui_status import StatusBar
from .ui_story_tabs import StoryTabsMixin

# Copia de autoguardado, separada del guardado explicito del usuario. Vive en
# user_data_dir() (%APPDATA%\StoryForge en el .exe) y se resuelve al crear la
# ventana (StoryForgeApp.autosave_path): asi STORYFORGE_USER_DATA_DIR
# redirige el autoguardado -- las pruebas lo usan para no tocar nunca el
# autoguardado real del usuario.


def log_location() -> str:
    """Donde quedan los errores registrados (ver app/main.py)."""
    if is_frozen():
        return log_file_path()
    return S.LOG_EN_CONSOLA


def window_icon_path() -> Optional[str]:
    """assets/icon.ico: dentro del build (sys._MEIPASS) o en el arbol del codigo."""
    import sys

    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "assets", "icon.ico")
    return path if os.path.isfile(path) else None


def default_autosave_path() -> str:
    return os.path.join(user_data_dir(), "autosave", "autosave.json")


# Cada cuanto se revisa si hay que autoguardar: siempre mientras el modelo
# trabaja, y cada AUTOSAVE_IDLE_SECONDS si hay cambios sin guardar (F10:
# antes solo se autoguardaba durante una generacion).
AUTOSAVE_INTERVAL_MS = 20_000
AUTOSAVE_IDLE_SECONDS = 60
# Espera tras la ultima tecla antes de recalcular "cambios sin guardar" (F10).
DIRTY_CHECK_DEBOUNCE_MS = 500

logger = logging.getLogger(__name__)


def about_text(engine) -> str:
    """Texto de Ayuda > Acerca de (K3)."""
    try:
        from importlib.metadata import version as pkg_version
        llama_version = pkg_version("llama-cpp-python")
    except Exception:  # noqa: BLE001
        llama_version = S.NO_INSTALADO
    free = query_free_vram_bytes()
    gpu = S.SI if supports_gpu_offload() else S.NO_SOLO_CPU
    vram = S.ABOUT_VRAM_GB.format(gb=free / 1024**3) if free is not None else S.NO_DISPONIBLE
    model = os.path.basename(engine.model_path) if getattr(engine, "model_path", None) else S.NINGUNO
    lines = [
        f"{APP_TITLE} {__version__}",
        "",
        S.ABOUT_PYTHON.format(python_version=platform.python_version(), architecture=platform.architecture()[0],
                              system=platform.system(), release=platform.release()),
        S.ABOUT_LLAMA_CPP.format(llama_version=llama_version),
        S.ABOUT_GPU.format(gpu=gpu),
        S.ABOUT_VRAM.format(vram=vram),
        S.ABOUT_MODELO.format(model=model),
        "",
        S.ABOUT_CARPETA_MODELOS.format(folder=MODELS_DIR),
        S.ABOUT_DATOS_USUARIO.format(folder=user_data_dir()),
        S.ABOUT_REGISTRO.format(location=log_location()),
    ]
    return "\n".join(lines)


class StoryForgeApp(MenuMixin, ModelTabMixin, StoryTabsMixin, LorebookTabMixin, OutlineTabMixin,
                    ChaptersTabMixin, ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.prefs = get_ui_preferences()
        self._apply_global_preferences()
        self.geometry("1100x800")
        self._set_window_icon()

        self.project = Project()
        self.engine = LocalStoryEngine()
        self.current_path: Optional[str] = None
        self.chapter_panels: list[ChapterPanel] = []
        self.outline_panels: list[OutlinePanel] = []
        # Paneles del lorebook VISIBLES (filtrados por la busqueda) y todos
        # los creados, por id() de la entrada: filtrar ya no destruye y
        # recrea cada panel en cada tecla (F11).
        self.lore_panels: list[LoreEntryPanel] = []
        self._lore_panel_cache: Dict[int, LoreEntryPanel] = {}
        self._lore_filter_after = None
        # ids de las LoreEntry que coincidieron con la ULTIMA generacion de
        # capitulo (y por que, ver _record_lore_matches()).
        self.last_lore_match_ids: set[int] = set()
        self.last_lore_reasons: Dict[int, str] = {}
        # El motor local envuelve una sola instancia de Llama, que no es
        # segura para llamadas concurrentes: este flag evita dos tareas a la vez.
        self.busy = False
        self.selected_chapter_index = 0
        self.focus_mode = False
        self.last_preview: Optional[DiffPreviewDialog] = None
        self._model_paths: Dict[str, str] = {}
        self._gpu_available = supports_gpu_offload()
        self.task_runner = EngineTaskRunner(self)
        # Resuelto ahora (no al importar el modulo): ver default_autosave_path().
        self.autosave_path = default_autosave_path()
        # Autoguardado en segundo plano (ver _autosave): contador de
        # generaciones para que una escritura vieja nunca pise una nueva.
        self._autosave_lock = threading.Lock()
        self._autosave_gen = 0
        self._autosave_written_gen = 0
        self._autosave_discarded_gen = 0
        self._autosave_errors: list = []
        self._last_autosave = 0.0
        self._clean_json = ""
        self.dirty = False
        self._dirty_after = None
        # Errores inesperados en callbacks de Tk: sin esto, en el .exe
        # (console=False) se imprimian a un stderr inexistente y se perdian.
        self.report_callback_exception = self._report_callback_exception
        self._showing_unexpected_error = False

        self._build_menu()
        self.status_bar = StatusBar(self, self)
        self.status_bar.pack(side="bottom", fill="x", padx=10, pady=(0, 6))
        self._build_tabs()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._mark_clean()
        self._offer_autosave_recovery()
        self._restore_last_model_selection()
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    # ---------------- preferencias (F9) ----------------
    def _set_window_icon(self) -> None:
        """Icono de la ventana (barra de titulo y Alt+Tab): el mismo
        assets/icon.ico del .exe, incluido en el build (storyforge.spec). Si
        falta o Tk no lo acepta, queda el de CustomTkinter."""
        path = window_icon_path()
        if path is None:
            return
        try:
            self.iconbitmap(path)
        except Exception:  # noqa: BLE001 -- un icono nunca debe impedir abrir la app
            logger.debug("could not set the window icon from %s", path, exc_info=True)

    def _apply_global_preferences(self) -> None:
        ctk.set_appearance_mode(self.prefs.get("appearance", "dark"))
        ctk.set_default_color_theme("blue")
        try:
            ctk.set_widget_scaling(float(self.prefs.get("ui_scale", 1.0)))
        except Exception:  # noqa: BLE001
            pass

    def apply_editor_preferences(self, box) -> None:
        family = self.prefs.get("editor_font_family") or None
        size = int(self.prefs.get("editor_font_size", 14))
        spacing = int(self.prefs.get("editor_line_spacing", 4))
        try:
            box.configure(font=ctk.CTkFont(family=family, size=size) if family else ctk.CTkFont(size=size))
            box._textbox.configure(spacing1=spacing // 2, spacing3=spacing - spacing // 2)
        except Exception:  # noqa: BLE001
            pass

    def open_preferences(self) -> None:
        PreferencesDialog(self, self.prefs, self._save_preferences)

    def _save_preferences(self, values: dict) -> None:
        self.prefs.update(values)
        set_ui_preferences(values)
        self._apply_global_preferences()
        for panel in self.chapter_panels:
            self.apply_editor_preferences(panel.content_box)
        self._refresh_models()

    # ---------------- errores inesperados ----------------
    def _report_unexpected_error(self, exc_type, exc, tb, where: str = "") -> None:
        """Registra un error no capturado y se lo muestra al usuario (una
        ventana a la vez, para no apilar dialogos si se repite)."""
        logger.error("Error inesperado%s", where, exc_info=(exc_type, exc, tb))
        if self._showing_unexpected_error:
            return
        self._showing_unexpected_error = True
        try:
            messagebox.showerror(
                APP_TITLE,
                S.ERROR_INESPERADO.format(where=where, error_type=exc_type.__name__, exc=exc,
                                          log_location=log_location()),
            )
        finally:
            self._showing_unexpected_error = False

    def _report_callback_exception(self, exc_type, exc, tb) -> None:
        self._report_unexpected_error(exc_type, exc, tb)

    def _thread_excepthook(self, args) -> None:
        """Para threading.excepthook: un error no capturado en un hilo de
        trabajo se registra y se muestra desde el hilo principal."""
        if args.exc_type is SystemExit:
            return
        exc_type, exc, tb = args.exc_type, args.exc_value, args.exc_traceback
        try:
            self.after(0, lambda: self._report_unexpected_error(exc_type, exc, tb, S.EN_SEGUNDO_PLANO))
        except Exception:  # noqa: BLE001 - la ventana ya no existe
            logger.error("Error inesperado en segundo plano", exc_info=(exc_type, exc, tb))

    def _open_log_folder(self) -> None:
        folder = user_data_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)  # type: ignore[attr-defined]  # solo Windows
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo(APP_TITLE, S.LA_CARPETA_DE_REGISTROS_ES.format(folder=folder, exc=exc))

    def show_about(self) -> None:
        TextViewerDialog(self, S.ACERCA_DE.format(APP_TITLE=APP_TITLE), about_text(self.engine))

    def show_last_prompt(self) -> None:
        stats = getattr(self.engine, "stats", None)
        if stats is None or not stats.prompt_text:
            messagebox.showinfo(APP_TITLE, S.TODAVIA_NO_SE_ENVIO_NINGUN)
            return
        sampling = ", ".join(f"{k}={v}" for k, v in sorted(stats.sampling.items()))
        header = (
            S.OPERACION_TOKENS_DE_PROMPT_RESERVADOS.format(operation=stats.operation,
                                                           prompt_tokens=stats.prompt_tokens,
                                                           max_tokens=stats.max_tokens, n_ctx=stats.n_ctx,
                                                           budget_level=stats.budget_level, seed=stats.seed,
                                                           sampling=sampling)
        )
        TextViewerDialog(self, S.PROMPT_ENVIADO_AL_MODELO, stats.prompt_text, header)

    def show_diff_preview(self, title: str, old: str, new: str, on_accept, on_accept_continue=None,
                          on_discard=None) -> DiffPreviewDialog:
        self.last_preview = DiffPreviewDialog(self, title, old, new, on_accept, on_accept_continue, on_discard)
        return self.last_preview

    # ---------------- tabs ----------------
    def _build_tabs(self) -> None:
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        self.tab_model = self.tabview.add(S.TAB_MODELO)
        self.tab_plot = self.tabview.add(S.TAB_PLOT)
        self.tab_characters = self.tabview.add(S.TAB_PERSONAJES)
        self.tab_setting = self.tabview.add(S.TAB_SETTING)
        self.tab_lorebook = self.tabview.add(S.TAB_LOREBOOK)
        self.tab_outline = self.tabview.add(S.TAB_ESQUEMA)
        self.tab_chapters = self.tabview.add(S.TAB_CAPITULOS)

        self._build_model_tab()
        self._build_plot_tab()
        self._build_characters_tab()
        self._build_setting_tab()
        self._build_lorebook_tab()
        self._build_outline_tab()
        self._build_chapters_tab()

    # ---------------- exclusion mutua del motor ----------------
    def _set_engine_busy(self, busy: bool) -> None:
        """
        Deshabilita, a nivel de toda la app, todo lo que pueda disparar una
        llamada al modelo mientras alguna operacion ya esta en curso en otro
        hilo. self.engine envuelve una sola instancia de Llama, que no
        soporta llamadas concurrentes.
        """
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.generate_outline_btn.configure(state=state)
        self.load_model_btn.configure(state=state)
        self._refresh_complete_outline_btn()
        # Agregar/quitar capitulos durante una generacion desplazaria los
        # indices de project.chapters que el hilo en curso sigue usando.
        self.add_chapter_btn.configure(
            state="disabled" if busy else ("normal" if self.project.can_add_chapter() else "disabled")
        )
        for panel in self.chapter_panels:
            for btn in (panel.generate_btn, panel.continue_btn, panel.continue_cursor_btn,
                        panel.regen_summary_btn, panel.remove_btn, panel.refine_btn):
                btn.configure(state=state)
            panel._refresh_retry_controls(busy)
        for box in (self.plot_box, self.characters_box, self.setting_box):
            expand_btn = getattr(box, "expand_btn", None)
            if expand_btn is not None:
                expand_btn.configure(state=state)
        self.add_lore_btn.configure(
            state="disabled" if busy else ("normal" if self.project.can_add_lore_entry() else "disabled")
        )
        for panel in self._lore_panel_cache.values():
            panel.remove_btn.configure(state=state)
        if not busy:
            self._refresh_word_totals()

    # ---------------- cambios sin guardar (F10) ----------------
    def _current_json(self) -> str:
        return self.project.to_json()

    def _mark_clean(self) -> None:
        self._sync_all()
        self._clean_json = self._current_json()
        self.dirty = False
        self._update_title()

    def schedule_dirty_check(self) -> None:
        if self._dirty_after is not None:
            return
        try:
            self._dirty_after = self.after(DIRTY_CHECK_DEBOUNCE_MS, self._update_dirty_state)
        except Exception:  # noqa: BLE001 - ventana destruida
            self._dirty_after = None

    def _update_dirty_state(self) -> bool:
        self._dirty_after = None
        try:
            self._sync_all()
            self.dirty = self._current_json() != self._clean_json
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo comprobar si hay cambios sin guardar")
        self._update_title()
        return self.dirty

    def is_dirty(self) -> bool:
        return self._update_dirty_state()

    def _update_title(self) -> None:
        name = (self.story_title_entry.get().strip() if hasattr(self, "story_title_entry") else "") \
            or self.project.name or DEFAULT_PROJECT_NAME
        file_part = f" ({os.path.basename(self.current_path)})" if self.current_path else ""
        mark = " •" if self.dirty else ""
        self.title(f"{APP_TITLE} {__version__} — {name}{file_part}{mark}")

    # ---------------- autoguardado ----------------
    def _offer_autosave_recovery(self) -> None:
        if not os.path.isfile(self.autosave_path):
            return
        try:
            recovered = Project.load(self.autosave_path)
        except Exception:
            # autoguardado corrupto/ilegible: lo ignoramos en vez de fallar al abrir la app
            logger.exception("No se pudo leer el autoguardado %s", self.autosave_path)
            return
        if not messagebox.askyesno(
            APP_TITLE,
            S.SE_ENCONTRO_UNA_COPIA_DE,
        ):
            self._discard_autosave()
            return
        self.project = recovered
        self.current_path = None  # se recupera el contenido, pero se debe elegir donde guardarlo
        self._load_into_ui()
        self._clean_json = ""  # lo recuperado no esta guardado en ningun archivo
        self._update_dirty_state()

    def _autosave_tick(self) -> None:
        self._report_autosave_errors()
        if self.busy:
            self._autosave()
        elif self._update_dirty_state() and time.monotonic() - self._last_autosave >= AUTOSAVE_IDLE_SECONDS:
            self._autosave()
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    def _autosave(self) -> None:
        """
        Guarda el estado actual en self.autosave_path (separado del archivo
        que el usuario guarda explicitamente). El proyecto se serializa aqui,
        en el hilo principal (una foto consistente), y se ESCRIBE en un hilo
        aparte: una escritura lenta (disco de red, OneDrive) ya no congela la
        interfaz. Un contador de generaciones garantiza que una escritura
        vieja que termina tarde nunca pisa una mas nueva. Un error se
        registra y se avisa UNA sola vez por sesion.
        """
        try:
            self._sync_all()
            data = self._current_json()
        except Exception as exc:  # noqa: BLE001
            logger.exception("No se pudo preparar el autoguardado")
            self._autosave_errors.append(exc)
            self._report_autosave_errors()
            return
        self._autosave_gen += 1
        gen = self._autosave_gen
        path = self.autosave_path
        self._last_autosave = time.monotonic()

        def write() -> None:
            with self._autosave_lock:
                if gen <= self._autosave_written_gen or gen <= self._autosave_discarded_gen:
                    return  # ya se escribio algo mas nuevo, o se descarto
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    save_json_text(path, data)
                    self._autosave_written_gen = gen
                except Exception as exc:  # noqa: BLE001
                    logger.exception("No se pudo escribir el autoguardado en %s", path)
                    self._autosave_errors.append(exc)

        threading.Thread(target=write, daemon=True).start()
        self._report_autosave_errors()

    def _report_autosave_errors(self) -> None:
        if not self._autosave_errors:
            return
        exc = self._autosave_errors[-1]
        self._autosave_errors.clear()
        if getattr(self, "_autosave_error_reported", False):
            return
        self._autosave_error_reported = True
        messagebox.showwarning(
            APP_TITLE,
            S.NO_SE_PUDO_ESCRIBIR_EL.format(autosave_path=self.autosave_path, exc=exc),
        )

    def _discard_autosave(self) -> None:
        # Espera a que termine una escritura en curso y anula las pendientes.
        with self._autosave_lock:
            self._autosave_discarded_gen = self._autosave_gen
            for path in (self.autosave_path, self.autosave_path + ".bak"):
                try:
                    os.remove(path)
                except OSError:
                    pass

    # ---------------- sincronizacion general ----------------
    def _sync_all(self) -> None:
        if not hasattr(self, "chapters_scroll"):
            return  # todavia construyendo la ventana
        self.project.plot = self.plot_box.get()
        self.project.characters = self.characters_box.get()
        self.project.setting = self.setting_box.get()
        self.project.name = self.story_title_entry.get().strip() or DEFAULT_PROJECT_NAME
        self.project.author = self.author_entry.get().strip()
        self.project.author_note = self.project_note_entry.get().strip()
        heading_label = self.heading_menu.get()
        self.project.chapter_heading = next(
            (k for k, v in CHAPTER_HEADING_LABELS.items() if v == heading_label), "Chapter")
        self.project.writing_style = style_key(self.writing_style_menu.get())
        self.project.history_limit = self._history_limit_from_ui()
        self._sync_sampling()
        for panel in self.outline_panels:
            panel.sync_to_model()
        for panel in self.chapter_panels:
            panel.sync_to_model()
        self._sync_lore_panels()

    def _load_into_ui(self, keep_selection: bool = False) -> None:
        self.plot_box.set(self.project.plot)
        self.characters_box.set(self.project.characters)
        self.setting_box.set(self.project.setting)
        self._load_project_meta_into_ui()
        self._load_sampling_into_ui()
        self.outline_count_entry.delete(0, "end")
        self.outline_count_entry.insert(0, str(len(self.project.chapters) or MAX_CHAPTERS))
        self.writing_style_menu.set(style_label(
            self.project.writing_style if self.project.writing_style in WRITING_STYLES else ""))
        if not keep_selection:
            # Los matches de la "ultima generacion" pertenecen al proyecto que se
            # acaba de dejar atras.
            self.last_lore_match_ids = set()
            self.last_lore_reasons = {}
            self._outline_requested = None
            self.lore_search_entry.delete(0, "end")
            self.selected_chapter_index = 0
        self._clear_lore_panels()
        self._render_lore_entries()
        self._render_outline_panels()
        self._render_chapters()
        self._refresh_complete_outline_btn()
        self._update_title()

    # ---------------- acciones de archivo ----------------
    def _confirm_discard_changes(self, action: str) -> bool:
        if not self.is_dirty():
            return True
        choice = messagebox.askyesnocancel(
            APP_TITLE, S.HAY_CAMBIOS_SIN_GUARDAR_GUARDARLOS.format(action=action),
        )
        if choice is None:
            return False
        if choice:
            return self.save_project()
        return True

    def new_project(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, S.GENERACION_EN_CURSO_CAMBIAR_PROYECTO
            )
            return
        if not self._confirm_discard_changes(S.CREAR_UN_PROYECTO_NUEVO):
            return
        self.project = Project()
        self.current_path = None
        self._load_into_ui()
        self._mark_clean()

    def open_project(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, S.GENERACION_EN_CURSO_CAMBIAR_PROYECTO
            )
            return
        if not self._confirm_discard_changes(S.ABRIR_OTRO_PROYECTO):
            return
        path = filedialog.askopenfilename(
            title=S.ABRIR_PROYECTO,
            filetypes=[(S.PROYECTO_STORYFORGE, "*.storyforge.json *.json"), (S.TODOS_LOS_ARCHIVOS, "*.*")],
        )
        if not path:
            return
        self.open_project_path(path)

    def open_project_path(self, path: str) -> bool:
        try:
            project = Project.load(path)
            from_backup = False
        except Exception as exc:  # noqa: BLE001
            logger.exception("No se pudo abrir el proyecto %s", path)
            backup = path + ".bak"
            if not os.path.isfile(backup) or not messagebox.askyesno(
                APP_TITLE,
                S.NO_SE_PUDO_ABRIR_EL.format(exc=exc, backup=os.path.basename(backup)),
            ):
                messagebox.showerror(APP_TITLE, S.NO_SE_PUDO_ABRIR_PROYECTO.format(exc=exc))
                return False
            try:
                project = Project.load(backup)
                from_backup = True
            except Exception as exc2:  # noqa: BLE001
                messagebox.showerror(APP_TITLE, S.TAMPOCO_SE_PUDO_ABRIR_LA.format(exc2=exc2))
                return False
        self.project = project
        # La copia .bak se abre sin destino: "Guardar" pregunta donde, para
        # no pisar el archivo danado sin querer.
        self.current_path = None if from_backup else path
        self._load_into_ui()
        self._mark_clean()
        if from_backup:
            self._clean_json = ""
            self._update_dirty_state()
            messagebox.showinfo(APP_TITLE, S.SE_ABRIO_LA_COPIA_DE)
        self._restore_project_model()
        return True

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno(
            APP_TITLE,
            S.GENERACION_EN_CURSO_SALIR,
        ):
            return
        if self.is_dirty():
            choice = messagebox.askyesnocancel(APP_TITLE, S.GUARDAR_EL_PROYECTO_ANTES_DE)
            if choice is None:  # Cancelar: no salir
                return
            if choice:  # Si: guardar (si se cancela o falla, no salimos)
                if not self.save_project():
                    return
        # Sin cambios, guardado, o descartado a proposito: no ofrecer
        # "recuperar" en el proximo arranque.
        self._discard_autosave()
        self.destroy()

    def save_project(self) -> bool:
        """Devuelve True si el proyecto quedo guardado (False si se cancelo o fallo)."""
        if not self.current_path:
            return self.save_project_as()
        return self._save_to(self.current_path)

    def save_project_as(self) -> bool:
        self._sync_all()
        suggested = "".join(c for c in self.project.name if c not in '\\/:*?"<>|').strip() or S.NOMBRE_DE_ARCHIVO_SUGERIDO
        path = filedialog.asksaveasfilename(
            title=S.GUARDAR_PROYECTO_COMO, defaultextension=".storyforge.json",
            initialfile=f"{suggested}.storyforge.json",
            filetypes=[(S.PROYECTO_STORYFORGE, "*.storyforge.json *.json")],
        )
        if not path:
            return False
        return self._save_to(path)

    def _save_to(self, path: str) -> bool:
        self._sync_all()
        problems = self.project.validate_inputs() + self.project.validate_warnings()
        if problems:
            messagebox.showwarning(APP_TITLE, S.SE_GUARDARA_CON_ESTAS_ADVERTENCIAS + "\n".join(problems))
        try:
            self.project.save(path)
        except Exception as exc:  # noqa: BLE001
            # Project.save() es atomico: el archivo anterior (si existia) sigue intacto.
            logger.exception("No se pudo guardar el proyecto en %s", path)
            messagebox.showerror(APP_TITLE, S.NO_SE_PUDO_GUARDAR.format(path=path, exc=exc))
            return False
        self.current_path = path
        # La copia de autoguardado quedaria obsoleta.
        self._discard_autosave()
        self._mark_clean()
        messagebox.showinfo(APP_TITLE, S.PROYECTO_GUARDADO)
        return True

    def _export(self, title: str, extension: str, label: str, exporter) -> None:
        self._sync_all()
        suggested = "".join(c for c in self.project.name if c not in '\\/:*?"<>|').strip() or S.NOMBRE_DE_ARCHIVO_SUGERIDO
        path = filedialog.asksaveasfilename(
            title=title, defaultextension=extension, initialfile=f"{suggested}{extension}",
            filetypes=[(label, f"*{extension}")],
        )
        if not path:
            return
        try:
            exporter(self.project, path)
            messagebox.showinfo(APP_TITLE, S.EXPORTADO_A.format(path=path))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error al exportar a %s", path)
            messagebox.showerror(APP_TITLE, S.ERROR_AL_EXPORTAR.format(exc=exc))

    def export_word(self) -> None:
        self._export(S.EXPORTAR_A_WORD, ".docx", S.WORD, export_docx)

    def export_txt_file(self) -> None:
        self._export(S.EXPORTAR_A_TXT, ".txt", S.TIPO_TEXTO, export_txt)

    def export_markdown_file(self) -> None:
        self._export(S.EXPORTAR_A_MARKDOWN, ".md", S.MARKDOWN, export_markdown)

    def export_epub_file(self) -> None:
        self._export(S.EXPORTAR_A_EPUB, ".epub", S.EPUB, export_epub)


def run() -> None:
    app = StoryForgeApp()
    # Errores no capturados en hilos de trabajo: se registran y se muestran.
    threading.excepthook = app._thread_excepthook
    app.mainloop()


# Nombres que las pruebas importan desde app.gui.
__all__ = [
    "StoryForgeApp", "run", "VersionHistoryDialog", "default_autosave_path", "_lore_entry_matches_search",
    "CHAPTER_PURPOSE_DEFAULT_LABEL", "WRITING_STYLE_DEFAULT_LABEL", "ContextOverflowError", "ModelNotLoadedError",
]
