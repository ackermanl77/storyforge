"""
Interfaz grafica de escritorio (CustomTkinter) para StoryForge Local.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from .engine import ContextOverflowError, LocalStoryEngine, ModelNotLoadedError, find_local_models
from .export import export_docx, export_txt
from .project import (
    MAX_CHAPTERS,
    MAX_CHARACTERS_WORDS,
    MAX_OUTLINE_WORDS_PER_CHAPTER,
    MAX_PLOT_WORDS,
    MAX_SETTING_WORDS,
    MAX_WORDS_PER_CHAPTER,
    WRITING_STYLES,
    Chapter,
    Project,
    count_words,
)
from .repetition import reduce_repetition, repetition_report

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "StoryForge Local"
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(APP_ROOT, "models")
WRITING_STYLE_DEFAULT_LABEL = "(Por defecto)"
WRITING_STYLE_OPTIONS = [WRITING_STYLE_DEFAULT_LABEL] + WRITING_STYLES
# Copia de autoguardado, separada del guardado explicito del usuario: un
# capitulo puede tardar 15-40 minutos en generarse, asi que sin esto un
# cierre inesperado (crash, corte de luz) a mitad de una generacion larga
# perderia todo ese progreso.
AUTOSAVE_PATH = os.path.join(APP_ROOT, "autosave", "autosave.json")
AUTOSAVE_INTERVAL_MS = 20_000  # cada cuanto se reintenta el autoguardado mientras hay una generacion en curso


class LimitedTextBox(ctk.CTkFrame):
    """Textbox con contador de palabras en vivo y limite maximo visible."""

    def __init__(self, master, label: str, max_words: int, height: int = 160, **kwargs):
        super().__init__(master, **kwargs)
        self.max_words = max_words
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text=label, font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w")
        self.counter_label = ctk.CTkLabel(header, text=f"0 / {max_words:,} palabras")
        self.counter_label.grid(row=0, column=1, sticky="e")

        self.textbox = ctk.CTkTextbox(self, height=height, wrap="word")
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.grid_rowconfigure(1, weight=1)
        self.textbox.bind("<KeyRelease>", self._on_change)

    def _on_change(self, _event=None) -> None:
        words = count_words(self.get())
        over = words > self.max_words
        color = "#e05555" if over else ("#9fd39f" if words > 0 else "gray")
        self.counter_label.configure(text=f"{words:,} / {self.max_words:,} palabras", text_color=color)

    def get(self) -> str:
        return self.textbox.get("1.0", "end-1c")

    def set(self, text: str) -> None:
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text or "")
        self._on_change()


class ChapterPanel(ctk.CTkFrame):
    """Panel para un capitulo: metadata + generacion + contenido + reduccion de repeticion."""

    def __init__(self, master, app: "StoryForgeApp", index: int, chapter: Chapter, **kwargs):
        super().__init__(master, border_width=1, corner_radius=8, **kwargs)
        self.app = app
        self.index = index
        self.chapter = chapter
        self._cancel_flag: Optional[dict] = None
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=f"Capitulo {index + 1}", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )

        self.title_entry = ctk.CTkEntry(self, placeholder_text="Titulo del capitulo")
        self.title_entry.insert(0, chapter.title)
        self.title_entry.grid(row=0, column=1, padx=8, pady=(8, 2), sticky="ew")

        ctk.CTkLabel(self, text="Palabras objetivo:").grid(row=0, column=2, padx=(8, 2), sticky="e")
        self.target_entry = ctk.CTkEntry(self, width=80)
        self.target_entry.insert(0, str(chapter.target_words))
        self.target_entry.grid(row=0, column=3, padx=(0, 8), sticky="e")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=8)
        self.generate_btn = ctk.CTkButton(btn_frame, text="Generar", width=100, command=self._on_generate)
        self.generate_btn.pack(side="left", padx=(0, 6), pady=4)
        self.cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancelar", width=90, state="disabled",
            fg_color="#8a6a2f", hover_color="#6e5526", command=self._on_cancel,
        )
        self.cancel_btn.pack(side="left", padx=6, pady=4)
        self.reduce_btn = ctk.CTkButton(btn_frame, text="Reducir repeticion", width=140, command=self._on_reduce)
        self.reduce_btn.pack(side="left", padx=6, pady=4)
        self.report_btn = ctk.CTkButton(btn_frame, text="Reporte de repeticion", width=150, command=self._on_report)
        self.report_btn.pack(side="left", padx=6, pady=4)
        self.remove_btn = ctk.CTkButton(
            btn_frame, text="Eliminar capitulo", width=130, fg_color="#8a3b3b",
            hover_color="#6e2f2f", command=self._on_remove,
        )
        self.remove_btn.pack(side="right", padx=(6, 0), pady=4)

        self.status_label = ctk.CTkLabel(self, text="", text_color="gray")
        self.status_label.grid(row=2, column=0, columnspan=4, sticky="w", padx=8)

        self.content_box = ctk.CTkTextbox(self, height=220, wrap="word")
        self.content_box.grid(row=3, column=0, columnspan=4, sticky="nsew", padx=8, pady=(4, 8))
        self.content_box.insert("1.0", chapter.content)
        self.grid_rowconfigure(3, weight=1)

        self.word_count_label = ctk.CTkLabel(self, text="")
        self.word_count_label.grid(row=4, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))
        self._refresh_word_count()
        self.content_box.bind("<KeyRelease>", lambda e: self._refresh_word_count())

    # ---- sincronizacion con el modelo de datos ----
    def sync_to_model(self) -> None:
        self.chapter.title = self.title_entry.get().strip() or f"Capitulo {self.index + 1}"
        try:
            target = int(self.target_entry.get())
        except ValueError:
            target = self.chapter.target_words
        self.chapter.target_words = max(1, min(target, MAX_WORDS_PER_CHAPTER))
        self.chapter.content = self.content_box.get("1.0", "end-1c")

    def _refresh_word_count(self) -> None:
        words = count_words(self.content_box.get("1.0", "end-1c"))
        over = words > MAX_WORDS_PER_CHAPTER
        color = "#e05555" if over else "gray"
        self.word_count_label.configure(
            text=f"{words:,} / {MAX_WORDS_PER_CHAPTER:,} palabras generadas", text_color=color
        )

    def _set_busy(self, busy: bool, status: str = "") -> None:
        state = "disabled" if busy else "normal"
        self.generate_btn.configure(state=state)
        self.reduce_btn.configure(state=state)
        self.remove_btn.configure(state=state)
        self.cancel_btn.configure(state=("normal" if busy else "disabled"))
        self.status_label.configure(text=status)

    def _on_cancel(self) -> None:
        if self._cancel_flag is not None:
            self._cancel_flag["cancel"] = True
            self.cancel_btn.configure(state="disabled")
            self.status_label.configure(text="Cancelando... se detendra al terminar la seccion actual.")

    def _on_generate(self) -> None:
        if not self.app.engine.is_loaded:
            messagebox.showwarning(APP_TITLE, "Primero carga un modelo local (.gguf) en la pestana 'Modelo'.")
            return
        if self.app.busy:
            messagebox.showwarning(
                APP_TITLE,
                "Ya hay una generacion en curso (otro capitulo, el esquema, o cargando un "
                "modelo). Espera a que termine antes de iniciar otra.",
            )
            return
        # Sincronizamos TODO (plot/personajes/setting/esquema/capitulos), no
        # solo este panel: la generacion depende de esos datos y antes solo
        # se actualizaban al guardar/exportar, asi que podian estar
        # desactualizados (o vacios) al generar sin haber guardado primero.
        self.app._sync_all()
        errors = self.app.project.validate_inputs()
        if errors:
            messagebox.showwarning(APP_TITLE, "Corrige antes de generar:\n\n" + "\n".join(errors))
            return
        if self.chapter.content.strip() and not messagebox.askyesno(
            APP_TITLE,
            f"El capitulo {self.index + 1} ya tiene texto generado. Generar de nuevo "
            "reemplazara ese contenido por completo y no se puede deshacer. ¿Continuar?",
        ):
            return

        self.app._set_engine_busy(True)
        self._set_busy(True, "Generando... esto puede tardar varios minutos en CPU.")
        cancel_flag = {"cancel": False}
        self._cancel_flag = cancel_flag

        def progress(text: str, words: int, target: int) -> None:
            def apply():
                self.content_box.delete("1.0", "end")
                self.content_box.insert("1.0", text)
                self._refresh_word_count()
                self.status_label.configure(text=f"Generando... {words:,} / {target:,} palabras")
            self.app.after(0, apply)

        def worker():
            try:
                result = self.app.engine.generate_chapter(
                    self.app.project, self.index, progress_callback=progress,
                    cancel_check=lambda: cancel_flag["cancel"],
                )
                self.chapter.content = result

                if result.strip() and not cancel_flag["cancel"]:
                    # Resumimos el capitulo para dar continuidad al siguiente
                    # (en vez de pasarle solo un recorte del texto crudo).
                    self.app.after(0, lambda: self.status_label.configure(
                        text="Generando resumen para continuidad entre capitulos..."
                    ))
                    try:
                        self.chapter.summary = self.app.engine.summarize(result)
                    except Exception:
                        # Si el resumen falla no perdemos el capitulo generado;
                        # el siguiente capitulo simplemente usara un recorte
                        # del texto en su lugar (ver prompts.build_previous_context).
                        pass
            except ModelNotLoadedError as exc:
                self.app.after(0, lambda: messagebox.showerror(APP_TITLE, str(exc)))
            except ContextOverflowError as exc:
                self.app.after(0, lambda: messagebox.showerror(
                    APP_TITLE, f"El contexto es demasiado grande para este modelo:\n\n{exc}"
                ))
            except Exception as exc:  # noqa: BLE001
                self.app.after(0, lambda: messagebox.showerror(APP_TITLE, f"Error generando capitulo: {exc}"))
            finally:
                self._cancel_flag = None
                self.app.after(0, lambda: self._set_busy(False, "Listo."))
                self.app.after(0, self.app._autosave)
                self.app.after(0, lambda: self.app._set_engine_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _on_reduce(self) -> None:
        self.sync_to_model()
        if not self.chapter.content.strip():
            return
        reduced = reduce_repetition(self.chapter.content)
        self.content_box.delete("1.0", "end")
        self.content_box.insert("1.0", reduced)
        self.chapter.content = reduced
        self._refresh_word_count()

    def _on_report(self) -> None:
        self.sync_to_model()
        report = repetition_report(self.chapter.content)
        messagebox.showinfo(f"Repeticion - Capitulo {self.index + 1}", report)

    def _on_remove(self) -> None:
        if messagebox.askyesno(APP_TITLE, f"¿Eliminar el capitulo {self.index + 1}?"):
            self.app.remove_chapter(self.index)


class OutlinePanel(ctk.CTkFrame):
    """
    Panel de esquema (beat sheet) de un capitulo: titulo + beats principales.
    Vive en la pestana 'Esquema', separado de ChapterPanel (que es donde se
    genera y edita la prosa), para poder revisar la estructura completa de
    la historia de un vistazo antes de escribir un solo capitulo.
    """

    def __init__(self, master, index: int, chapter: Chapter, **kwargs):
        super().__init__(master, border_width=1, corner_radius=8, **kwargs)
        self.index = index
        self.chapter = chapter
        self.grid_columnconfigure(0, weight=1)

        # El titulo se edita solo en la pestana 'Capitulos' (ChapterPanel);
        # aqui solo se muestra, para no tener dos campos editables separados
        # escribiendo al mismo chapter.title y desincronizandose entre si.
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)
        title_text = chapter.title or f"Capitulo {index + 1}"
        ctk.CTkLabel(header, text=f"Capitulo {index + 1}: {title_text}", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.counter_label = ctk.CTkLabel(header, text="")
        self.counter_label.grid(row=0, column=1, sticky="e")

        self.outline_box = ctk.CTkTextbox(self, height=90, wrap="word")
        self.outline_box.insert("1.0", chapter.outline)
        self.outline_box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.outline_box.bind("<KeyRelease>", self._on_change)
        self._on_change()

    def _on_change(self, _event=None) -> None:
        words = count_words(self.outline_box.get("1.0", "end-1c"))
        over = words > MAX_OUTLINE_WORDS_PER_CHAPTER
        color = "#e05555" if over else "gray"
        self.counter_label.configure(
            text=f"{words:,} / {MAX_OUTLINE_WORDS_PER_CHAPTER:,} palabras", text_color=color
        )

    def sync_to_model(self) -> None:
        self.chapter.outline = self.outline_box.get("1.0", "end-1c")


class StoryForgeApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x750")

        self.project = Project()
        self.engine = LocalStoryEngine()
        self.current_path: Optional[str] = None
        self.chapter_panels: list[ChapterPanel] = []
        self.outline_panels: list[OutlinePanel] = []
        # El motor local envuelve una sola instancia de Llama, que no es segura
        # para llamadas concurrentes: este flag evita que se generen dos
        # capitulos a la vez, o que se cargue un modelo nuevo mientras el
        # actual sigue generando texto en otro hilo.
        self.busy = False

        self._build_menu()
        self._build_tabs()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._offer_autosave_recovery()
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    # ---------------- menu ----------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Nuevo proyecto", command=self.new_project)
        file_menu.add_command(label="Abrir proyecto...", command=self.open_project)
        file_menu.add_command(label="Guardar proyecto", command=self.save_project)
        file_menu.add_command(label="Guardar proyecto como...", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exportar a Word (.docx)", command=self.export_word)
        file_menu.add_command(label="Exportar a TXT", command=self.export_txt_file)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self._on_close)
        menubar.add_cascade(label="Archivo", menu=file_menu)
        self.configure(menu=menubar)

    # ---------------- tabs ----------------
    def _build_tabs(self) -> None:
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_model = self.tabview.add("Modelo")
        self.tab_plot = self.tabview.add("Plot")
        self.tab_characters = self.tabview.add("Personajes")
        self.tab_setting = self.tabview.add("Setting")
        self.tab_outline = self.tabview.add("Esquema")
        self.tab_chapters = self.tabview.add("Capitulos")

        self._build_model_tab()
        self._build_plot_tab()
        self._build_characters_tab()
        self._build_setting_tab()
        self._build_outline_tab()
        self._build_chapters_tab()

    def _build_model_tab(self) -> None:
        tab = self.tab_model
        tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Coloca un archivo de modelo .gguf en la carpeta 'models/' junto al programa "
                "(ver README.md para recomendaciones de modelos) y cargalo aqui."
            ),
            wraplength=800, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=10)

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=10)
        row.grid_columnconfigure(0, weight=1)

        self.model_combo = ctk.CTkComboBox(row, values=self._list_models() or ["(sin modelos en models/)"])
        self.model_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(row, text="Actualizar lista", command=self._refresh_models).grid(row=0, column=1, padx=4)
        ctk.CTkButton(row, text="Elegir archivo...", command=self._browse_model).grid(row=0, column=2, padx=4)
        self.load_model_btn = ctk.CTkButton(row, text="Cargar modelo", command=self._load_model)
        self.load_model_btn.grid(row=0, column=3, padx=4)

        self.model_status = ctk.CTkLabel(tab, text="Ningun modelo cargado.", text_color="gray")
        self.model_status.grid(row=2, column=0, sticky="w", padx=10, pady=10)

    def _list_models(self) -> list[str]:
        return find_local_models(MODELS_DIR)

    def _refresh_models(self) -> None:
        values = self._list_models() or ["(sin modelos en models/)"]
        self.model_combo.configure(values=values)
        self.model_combo.set(values[0])

    def _browse_model(self) -> None:
        path = filedialog.askopenfilename(title="Selecciona un modelo .gguf", filetypes=[("GGUF", "*.gguf")])
        if path:
            self.model_combo.set(path)

    def _load_model(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE,
                "Espera a que termine la generacion en curso antes de cargar otro modelo.",
            )
            return
        selected = self.model_combo.get()
        if not selected or selected.startswith("("):
            messagebox.showwarning(APP_TITLE, "Selecciona un archivo .gguf valido.")
            return
        path = selected if os.path.isabs(selected) else os.path.join(MODELS_DIR, selected)
        self.model_status.configure(text=f"Cargando {os.path.basename(path)}...", text_color="gray")
        self.update_idletasks()
        self._set_engine_busy(True)

        def worker():
            try:
                self.engine.load(path)
                self.project.model_path = path
                self.after(0, lambda: self.model_status.configure(
                    text=f"Modelo cargado: {os.path.basename(path)}", text_color="#9fd39f"
                ))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self.model_status.configure(text=f"Error: {exc}", text_color="#e05555"))
            finally:
                self.after(0, lambda: self._set_engine_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _build_plot_tab(self) -> None:
        self.tab_plot.grid_columnconfigure(0, weight=1)
        self.tab_plot.grid_rowconfigure(0, weight=1)
        self.plot_box = LimitedTextBox(self.tab_plot, "Story Plot (idea de la historia)", MAX_PLOT_WORDS, height=500)
        self.plot_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def _build_characters_tab(self) -> None:
        self.tab_characters.grid_columnconfigure(0, weight=1)
        self.tab_characters.grid_rowconfigure(0, weight=1)
        self.characters_box = LimitedTextBox(
            self.tab_characters, "Personajes (descripcion, personalidad, relaciones)",
            MAX_CHARACTERS_WORDS, height=500,
        )
        self.characters_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def _build_setting_tab(self) -> None:
        self.tab_setting.grid_columnconfigure(0, weight=1)
        self.tab_setting.grid_rowconfigure(0, weight=1)
        self.setting_box = LimitedTextBox(
            self.tab_setting, "Setting (donde y cuando ocurre la historia)",
            MAX_SETTING_WORDS, height=500,
        )
        self.setting_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    def _build_outline_tab(self) -> None:
        tab = self.tab_outline
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Genera primero un esquema (beat sheet) de todos los capitulos a partir "
                "del plot, personajes y setting. Escribir la historia siguiendo un esquema "
                "acordado de antemano ayuda mucho a que se mantenga consistente de principio "
                "a fin. Puedes editar el resultado aqui antes de generar la prosa en la "
                "pestana 'Capitulos'."
            ),
            wraplength=850, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(controls, text="Numero de capitulos:").pack(side="left", padx=(0, 6))
        self.outline_count_entry = ctk.CTkEntry(controls, width=50)
        self.outline_count_entry.insert(0, str(len(self.project.chapters) or MAX_CHAPTERS))
        self.outline_count_entry.pack(side="left", padx=(0, 12))
        # Tipo de escritura: aplica a toda la historia (esquema y prosa de
        # cada capitulo), no por capitulo individual -- ver
        # prompts.build_writing_style_instruction().
        ctk.CTkLabel(controls, text="Tipo de escritura:").pack(side="left", padx=(0, 6))
        self.writing_style_menu = ctk.CTkOptionMenu(controls, values=WRITING_STYLE_OPTIONS, width=160)
        self.writing_style_menu.set(
            self.project.writing_style if self.project.writing_style in WRITING_STYLES
            else WRITING_STYLE_DEFAULT_LABEL
        )
        self.writing_style_menu.pack(side="left", padx=(0, 12))
        self.generate_outline_btn = ctk.CTkButton(
            controls, text="Generar esquema completo", command=self._on_generate_outline
        )
        self.generate_outline_btn.pack(side="left")
        self.outline_status = ctk.CTkLabel(controls, text="", text_color="gray")
        self.outline_status.pack(side="left", padx=12)

        self.outline_scroll = ctk.CTkScrollableFrame(tab)
        self.outline_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.outline_scroll.grid_columnconfigure(0, weight=1)
        self._render_outline_panels()

    def _on_generate_outline(self) -> None:
        if not self.engine.is_loaded:
            messagebox.showwarning(APP_TITLE, "Primero carga un modelo local (.gguf) en la pestana 'Modelo'.")
            return
        if self.busy:
            messagebox.showwarning(
                APP_TITLE,
                "Ya hay una generacion en curso (un capitulo u otra operacion). Espera a que termine.",
            )
            return

        self._sync_all()
        errors = self.project.validate_inputs()
        if errors:
            messagebox.showwarning(APP_TITLE, "Corrige antes de generar el esquema:\n\n" + "\n".join(errors))
            return

        try:
            num_chapters = int(self.outline_count_entry.get())
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Numero de capitulos invalido.")
            return
        num_chapters = max(1, min(num_chapters, MAX_CHAPTERS))

        if self.project.chapters and not messagebox.askyesno(
            APP_TITLE,
            "Esto reemplazara el titulo y esquema de los capitulos existentes "
            "(la prosa ya generada de cada capitulo se conserva). ¿Continuar?",
        ):
            return

        self.outline_status.configure(text="Generando esquema...", text_color="gray")
        self._set_engine_busy(True)

        def worker():
            try:
                outline_items = self.engine.generate_outline(self.project, num_chapters)

                def apply():
                    self._apply_outline(outline_items)
                    self.outline_status.configure(
                        text=f"Esquema generado: {len(outline_items)} capitulos.", text_color="#9fd39f"
                    )
                self.after(0, apply)
            except ModelNotLoadedError as exc:
                self.after(0, lambda: messagebox.showerror(APP_TITLE, str(exc)))
            except ContextOverflowError as exc:
                self.after(0, lambda: messagebox.showerror(
                    APP_TITLE, f"El contexto es demasiado grande para este modelo:\n\n{exc}"
                ))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror(APP_TITLE, f"Error generando el esquema: {exc}"))
            finally:
                self.after(0, self._autosave)
                self.after(0, lambda: self._set_engine_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_outline(self, outline_items: list[tuple[str, str]]) -> None:
        for i, (title, outline) in enumerate(outline_items):
            if i < len(self.project.chapters):
                self.project.chapters[i].title = title or self.project.chapters[i].title
                self.project.chapters[i].outline = outline
            elif self.project.can_add_chapter():
                self.project.add_chapter(title=title, outline=outline)
        self._render_outline_panels()
        self._render_chapters()

    def _render_outline_panels(self) -> None:
        for child in self.outline_scroll.winfo_children():
            child.destroy()
        self.outline_panels = []
        if not self.project.chapters:
            ctk.CTkLabel(
                self.outline_scroll,
                text="Aun no hay capitulos. Genera un esquema completo arriba, o agrega "
                     "capitulos manualmente en la pestana 'Capitulos'.",
                text_color="gray", wraplength=800, justify="left",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return
        for i, chapter in enumerate(self.project.chapters):
            panel = OutlinePanel(self.outline_scroll, i, chapter)
            panel.grid(row=i, column=0, sticky="ew", pady=6)
            self.outline_panels.append(panel)

    def _build_chapters_tab(self) -> None:
        tab = self.tab_chapters
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.add_chapter_btn = ctk.CTkButton(top, text="+ Agregar capitulo", command=self.add_chapter)
        self.add_chapter_btn.pack(side="left")
        ctk.CTkLabel(top, text=f"(maximo {MAX_CHAPTERS} capitulos)").pack(side="left", padx=8)

        self.chapters_scroll = ctk.CTkScrollableFrame(tab)
        self.chapters_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.chapters_scroll.grid_columnconfigure(0, weight=1)

    # ---------------- gestion de capitulos ----------------
    def add_chapter(self) -> None:
        if not self.project.can_add_chapter():
            messagebox.showinfo(APP_TITLE, f"Ya hay {MAX_CHAPTERS} capitulos (el maximo).")
            return
        self.project.add_chapter()
        self._render_chapters()
        self._render_outline_panels()

    def remove_chapter(self, index: int) -> None:
        del self.project.chapters[index]
        self._render_chapters()
        self._render_outline_panels()

    def _render_chapters(self) -> None:
        for child in self.chapters_scroll.winfo_children():
            child.destroy()
        self.chapter_panels = []
        for i, chapter in enumerate(self.project.chapters):
            panel = ChapterPanel(self.chapters_scroll, self, i, chapter)
            panel.grid(row=i, column=0, sticky="ew", pady=6)
            self.chapter_panels.append(panel)
        self.add_chapter_btn.configure(
            state="normal" if self.project.can_add_chapter() else "disabled"
        )
        # Si se agrego/elimino un capitulo mientras otra generacion seguia en
        # curso en otro panel, los paneles recien creados deben nacer ya
        # deshabilitados en vez de dejar una ventana para dispararla en paralelo.
        if self.busy:
            self._set_engine_busy(True)

    # ---------------- exclusion mutua del motor ----------------
    def _set_engine_busy(self, busy: bool) -> None:
        """
        Deshabilita, a nivel de toda la app, todo lo que pueda disparar una
        llamada al modelo (generar un capitulo, generar el esquema, cargar un
        modelo nuevo) mientras alguna de esas operaciones ya esta en curso en
        otro hilo. self.engine envuelve una sola instancia de Llama, que no
        soporta llamadas concurrentes.
        """
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.generate_outline_btn.configure(state=state)
        self.load_model_btn.configure(state=state)
        # Agregar/quitar capitulos durante una generacion desplazaria los
        # indices de project.chapters que el hilo en curso sigue usando.
        self.add_chapter_btn.configure(
            state="disabled" if busy else ("normal" if self.project.can_add_chapter() else "disabled")
        )
        for panel in self.chapter_panels:
            panel.generate_btn.configure(state=state)
            panel.remove_btn.configure(state=state)

    # ---------------- autoguardado ----------------
    def _offer_autosave_recovery(self) -> None:
        if not os.path.isfile(AUTOSAVE_PATH):
            return
        try:
            recovered = Project.load(AUTOSAVE_PATH)
        except Exception:
            return  # autoguardado corrupto/ilegible: lo ignoramos en vez de tronar al abrir la app
        if not messagebox.askyesno(
            APP_TITLE,
            "Se encontro una copia de autoguardado, probablemente de una generacion "
            "interrumpida (cierre inesperado o crash) en una sesion anterior. "
            "¿Recuperar ese proyecto ahora?",
        ):
            self._discard_autosave()
            return
        self.project = recovered
        self.current_path = None  # se recupera el contenido, pero se debe elegir donde guardarlo
        self._load_into_ui()

    def _autosave_tick(self) -> None:
        if self.busy:
            self._autosave()
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_tick)

    def _autosave(self) -> None:
        """
        Guarda el estado actual en AUTOSAVE_PATH (separado del archivo que el
        usuario guarda explicitamente) para poder recuperar el progreso si la
        app se cierra a medio camino de una generacion larga (15-40 minutos
        por capitulo). Nunca debe interrumpir la generacion: cualquier error
        se ignora en silencio.
        """
        try:
            self._sync_all()
            os.makedirs(os.path.dirname(AUTOSAVE_PATH), exist_ok=True)
            self.project.save(AUTOSAVE_PATH)
        except Exception:
            pass

    def _discard_autosave(self) -> None:
        try:
            os.remove(AUTOSAVE_PATH)
        except OSError:
            pass

    # ---------------- sincronizacion general ----------------
    def _sync_all(self) -> None:
        self.project.plot = self.plot_box.get()
        self.project.characters = self.characters_box.get()
        self.project.setting = self.setting_box.get()
        selected_style = self.writing_style_menu.get()
        self.project.writing_style = "" if selected_style == WRITING_STYLE_DEFAULT_LABEL else selected_style
        for panel in self.outline_panels:
            panel.sync_to_model()
        for panel in self.chapter_panels:
            panel.sync_to_model()

    def _load_into_ui(self) -> None:
        self.plot_box.set(self.project.plot)
        self.characters_box.set(self.project.characters)
        self.setting_box.set(self.project.setting)
        self.outline_count_entry.delete(0, "end")
        self.outline_count_entry.insert(0, str(len(self.project.chapters) or MAX_CHAPTERS))
        self.writing_style_menu.set(
            self.project.writing_style if self.project.writing_style in WRITING_STYLES
            else WRITING_STYLE_DEFAULT_LABEL
        )
        self._render_outline_panels()
        self._render_chapters()

    # ---------------- acciones de archivo ----------------
    def new_project(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, "Hay una generacion en curso. Espera a que termine antes de cambiar de proyecto."
            )
            return
        if not messagebox.askyesno(APP_TITLE, "¿Crear un nuevo proyecto? Se perdera lo no guardado."):
            return
        self.project = Project()
        self.current_path = None
        self._load_into_ui()

    def open_project(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, "Hay una generacion en curso. Espera a que termine antes de cambiar de proyecto."
            )
            return
        path = filedialog.askopenfilename(title="Abrir proyecto", filetypes=[("Proyecto StoryForge", "*.json")])
        if not path:
            return
        try:
            self.project = Project.load(path)
            self.current_path = path
            self._load_into_ui()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"No se pudo abrir el proyecto: {exc}")

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno(
            APP_TITLE,
            "Hay una generacion en curso. Si sales ahora se perdera el progreso no guardado "
            "de ese capitulo/esquema. ¿Salir de todas formas?",
        ):
            return

        choice = messagebox.askyesnocancel(APP_TITLE, "¿Guardar el proyecto antes de salir?")
        if choice is None:  # Cancelar: no salir
            return
        if choice:  # Si: guardar (si el dialogo "guardar como" se cancela, no salimos)
            path_before = self.current_path
            self.save_project()
            if self.current_path is None and path_before is None:
                return
        else:
            # El usuario decidio explicitamente no guardar: no le ofrezcamos
            # "recuperar" ese mismo contenido descartado en el proximo arranque.
            self._discard_autosave()
        self.destroy()

    def save_project(self) -> None:
        if not self.current_path:
            self.save_project_as()
            return
        self._sync_all()
        errors = self.project.validate_inputs()
        if errors:
            messagebox.showwarning(APP_TITLE, "Se guardara con estas advertencias:\n\n" + "\n".join(errors))
        self.project.save(self.current_path)
        # Ya hay un guardado explicito y mas reciente: la copia de
        # autoguardado quedaria obsoleta y solo generaria una oferta de
        # "recuperar" confusa en el proximo arranque.
        self._discard_autosave()
        messagebox.showinfo(APP_TITLE, "Proyecto guardado.")

    def save_project_as(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Guardar proyecto como", defaultextension=".json",
            filetypes=[("Proyecto StoryForge", "*.json")],
        )
        if not path:
            return
        self.current_path = path
        self.save_project()

    def export_word(self) -> None:
        self._sync_all()
        path = filedialog.asksaveasfilename(
            title="Exportar a Word", defaultextension=".docx", filetypes=[("Word", "*.docx")]
        )
        if not path:
            return
        try:
            export_docx(self.project, path)
            messagebox.showinfo(APP_TITLE, f"Exportado a {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Error al exportar: {exc}")

    def export_txt_file(self) -> None:
        self._sync_all()
        path = filedialog.asksaveasfilename(
            title="Exportar a TXT", defaultextension=".txt", filetypes=[("Texto", "*.txt")]
        )
        if not path:
            return
        try:
            export_txt(self.project, path)
            messagebox.showinfo(APP_TITLE, f"Exportado a {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Error al exportar: {exc}")


def run() -> None:
    app = StoryForgeApp()
    app.mainloop()
