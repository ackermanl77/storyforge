"""
Pestana Modelo: elegir y cargar el .gguf, opciones de carga (GPU, contexto,
flash attention, cache KV), estimacion de VRAM, formato de chat y muestreo.
"""
from __future__ import annotations

import logging
import os
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

import customtkinter as ctk

from . import strings_es as S
from .error_text import describe_exception
from .chat_format import (
    CHAT_FORMAT_AUTO,
    CHAT_FORMAT_CHOICES,
    CHAT_FORMAT_LABELS,
    chat_format_from_label,
)
from .engine import LocalStoryEngine
from .gguf import (
    KV_CACHE_TYPES,
    estimate_vram,
    list_model_entries,
    model_info,
    query_free_vram_bytes,
    query_total_ram_bytes,
)
from .project import (
    portable_model_path,
    resolve_model_path,
)
from .sampling import (
    PRESET_CHOICES,
    PRESET_CUSTOM,
    PROSE_PRESETS,
    SamplingConfig,
    SamplingSettings,
    parse_seed,
)
from .settings import (
    get_chat_format_for_model,
    get_last_model,
    get_model_settings,
    set_chat_format_for_model,
    set_model_settings,
)
from .task_runner import call_supported
from .ui_common import (
    APP_TITLE,
    MODELS_DIR,
    NO_MODELS_LABEL,
    _parse_optional_int,
)
from .ui_dialogs import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_WARN,
)
from .ui_focus import apply_tab_order

# Un solo registrador para toda la ventana principal ("app.gui"), como
# antes de dividir gui.py en modulos.
logger = logging.getLogger("app.gui")


class ModelTabMixin:
    """Pestana Modelo de StoryForgeApp."""

    # ---------------- pestana Modelo ----------------
    def _build_model_tab(self) -> None:
        outer = ctk.CTkScrollableFrame(self.tab_model, fg_color="transparent")
        outer.pack(fill="both", expand=True)
        tab = outer
        tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                S.COLOCA_UN_ARCHIVO_DE_MODELO
            ),
            wraplength=900, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=10)

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=10)
        row.grid_columnconfigure(0, weight=1)
        self.model_combo = ctk.CTkComboBox(
            row, values=self._list_models() or [NO_MODELS_LABEL], command=self._on_model_selected,
        )
        self.model_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.refresh_models_btn = ctk.CTkButton(row, text=S.ACTUALIZAR_LISTA, command=self._refresh_models)
        self.refresh_models_btn.grid(row=0, column=1, padx=4)
        self.browse_model_btn = ctk.CTkButton(row, text=S.ELEGIR_ARCHIVO, command=self._browse_model)
        self.browse_model_btn.grid(row=0, column=2, padx=4)
        self.load_model_btn = ctk.CTkButton(row, text=S.CARGAR_MODELO, command=self._load_model)
        self.load_model_btn.grid(row=0, column=3, padx=4)

        self.model_info_label = ctk.CTkLabel(tab, text="", text_color=COLOR_MUTED, wraplength=900, justify="left")
        self.model_info_label.grid(row=2, column=0, sticky="w", padx=10, pady=(6, 0))

        basic = ctk.CTkFrame(tab, fg_color="transparent")
        basic.grid(row=3, column=0, sticky="w", padx=10, pady=(6, 0))
        ctk.CTkLabel(basic, text=S.CONTEXTO_N_CTX_0_EL).pack(side="left", padx=(0, 4))
        self.n_ctx_entry = ctk.CTkEntry(basic, width=70)
        self.n_ctx_entry.insert(0, "8192")
        self.n_ctx_entry.pack(side="left", padx=(0, 12))
        gpu_layers_label = (S.CAPAS_EN_GPU_1_TODAS if self._gpu_available
                            else S.CAPAS_EN_GPU_0_SOLO)
        ctk.CTkLabel(basic, text=gpu_layers_label).pack(side="left", padx=(0, 4))
        self.n_gpu_layers_entry = ctk.CTkEntry(basic, width=50)
        # -1 = TODAS las capas; solo se precarga con soporte de GPU real.
        self.n_gpu_layers_entry.insert(0, "-1" if self._gpu_available else "0")
        self.n_gpu_layers_entry.pack(side="left", padx=(0, 4))
        self.suggest_layers_btn = ctk.CTkButton(basic, text=S.ESTIMAR_VRAM, width=110, command=self._on_estimate_vram)
        self.suggest_layers_btn.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(basic, text=S.HILOS_CPU_VACIO_AUTOMATICO).pack(side="left", padx=(0, 4))
        self.n_threads_entry = ctk.CTkEntry(basic, width=50)
        self.n_threads_entry.pack(side="left")
        gpu_status_text = (S.GPU_DETECTADA_SE_USARA_PARA if self._gpu_available
                           else S.SIN_SOPORTE_DE_GPU_SOLO)
        self.gpu_status_label = ctk.CTkLabel(tab, text=gpu_status_text,
                                             text_color=COLOR_OK if self._gpu_available else COLOR_MUTED)
        self.gpu_status_label.grid(row=4, column=0, sticky="w", padx=10)

        # Opciones avanzadas de rendimiento (P1) y formato de chat: plegadas bajo "Avanzado" (UI1),
        # porque casi nunca hacen falta y antes llenaban la primera pantalla.
        self.model_advanced_toggle = ctk.CTkButton(
            tab, text=S.AVANZADO_MOSTRAR, fg_color="transparent", anchor="w", width=0,
            command=self._toggle_model_advanced,
        )
        self.model_advanced_toggle.grid(row=5, column=0, sticky="w", padx=6, pady=(6, 0))
        self.model_advanced = ctk.CTkFrame(tab, fg_color="transparent")
        self.model_advanced.grid(row=6, column=0, sticky="w", padx=10)
        self.model_advanced.grid_remove()
        adv = ctk.CTkFrame(self.model_advanced, fg_color="transparent")
        adv.pack(anchor="w", pady=(6, 0))
        self.flash_attn_var = ctk.BooleanVar(value=self._gpu_available)
        self.flash_attn_check = ctk.CTkCheckBox(adv, text=S.FLASH_ATTENTION, variable=self.flash_attn_var)
        self.flash_attn_check.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(adv, text=S.LOTE_N_BATCH).pack(side="left", padx=(0, 4))
        self.n_batch_entry = ctk.CTkEntry(adv, width=60)
        self.n_batch_entry.insert(0, "1024" if self._gpu_available else "512")
        self.n_batch_entry.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(adv, text=S.N_UBATCH_ETIQUETA).pack(side="left", padx=(0, 4))
        self.n_ubatch_entry = ctk.CTkEntry(adv, width=60, placeholder_text=S.AUTO_PLACEHOLDER)
        self.n_ubatch_entry.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(adv, text=S.CACHE_KV).pack(side="left", padx=(0, 4))
        self.kv_cache_menu = ctk.CTkOptionMenu(adv, values=list(KV_CACHE_TYPES), width=90)
        self.kv_cache_menu.set("f16")
        self.kv_cache_menu.pack(side="left")

        chat_row = ctk.CTkFrame(self.model_advanced, fg_color="transparent")
        chat_row.pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(chat_row, text=S.FORMATO_DE_CHAT).pack(side="left", padx=(0, 4))
        self.chat_format_menu = ctk.CTkOptionMenu(
            chat_row, values=[CHAT_FORMAT_LABELS[k] for k in CHAT_FORMAT_CHOICES], width=230,
            command=self._on_chat_format_changed,
        )
        self.chat_format_menu.set(CHAT_FORMAT_LABELS[CHAT_FORMAT_AUTO])
        self.chat_format_menu.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            chat_row,
            text=S.AUTO_USA_LA_PLANTILLA_DEL,
            text_color=COLOR_MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")

        ctk.CTkLabel(
            tab,
            text=(
                S.UN_N_CTX_MAYOR_PERMITE
            ),
            wraplength=900, justify="left", text_color=COLOR_MUTED, font=ctk.CTkFont(size=11),
        ).grid(row=7, column=0, sticky="w", padx=10, pady=(4, 0))

        self.model_status = ctk.CTkLabel(tab, text=S.NINGUN_MODELO_CARGADO, text_color=COLOR_MUTED,
                                         wraplength=900, justify="left")
        self.model_status.grid(row=8, column=0, sticky="w", padx=10, pady=10)

        self._build_sampling_panel(tab, row=9)
        self._build_server_panel(tab, row=10)
        self._on_model_selected(self.model_combo.get())

    def _toggle_model_advanced(self) -> None:
        """Muestra u oculta los ajustes avanzados de carga (UI1)."""
        self.model_advanced_shown = not getattr(self, "model_advanced_shown", False)
        if self.model_advanced_shown:
            self.model_advanced.grid()
        else:
            self.model_advanced.grid_remove()
        self.model_advanced_toggle.configure(text=S.AVANZADO_OCULTAR if self.model_advanced_shown else S.AVANZADO_MOSTRAR)

    # ---- modelo en un servidor compatible con OpenAI (B14) ----
    def _build_server_panel(self, tab, row: int) -> None:
        from .settings import get_server_settings

        saved = get_server_settings()
        frame = ctk.CTkFrame(tab)
        frame.grid(row=row, column=0, sticky="ew", padx=10, pady=(10, 10))
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=S.SERVIDOR_TITULO, font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=6, sticky="w", padx=8, pady=(8, 2))
        ctk.CTkLabel(frame, text=S.SERVIDOR_AYUDA, wraplength=880, justify="left", text_color=COLOR_MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=1, column=0, columnspan=6, sticky="w", padx=8)
        ctk.CTkLabel(frame, text=S.SERVIDOR_URL).grid(row=2, column=0, sticky="e", padx=(8, 4), pady=8)
        self.server_url_entry = ctk.CTkEntry(frame)
        self.server_url_entry.insert(0, saved["url"])
        self.server_url_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(frame, text=S.SERVIDOR_MODELO).grid(row=2, column=2, sticky="e", padx=(0, 4))
        self.server_model_entry = ctk.CTkEntry(frame, width=200)
        self.server_model_entry.insert(0, saved["model"])
        self.server_model_entry.grid(row=2, column=3, padx=(0, 8))
        ctk.CTkLabel(frame, text=S.SERVIDOR_CLAVE).grid(row=2, column=4, sticky="e", padx=(0, 4))
        self.server_key_entry = ctk.CTkEntry(frame, width=120, show="•")
        self.server_key_entry.insert(0, saved["api_key"])
        self.server_key_entry.grid(row=2, column=5, padx=(0, 8))
        self.server_connect_btn = ctk.CTkButton(frame, text=S.SERVIDOR_CONECTAR, command=self._connect_server, width=110)
        self.server_connect_btn.grid(row=3, column=5, sticky="e", padx=8, pady=(0, 8))

    def _connect_server(self) -> None:
        from .settings import set_server_settings

        if self.busy:
            messagebox.showwarning(APP_TITLE, S.ESPERA_ANTES_DE_CARGAR_MODELO)
            return
        url = self.server_url_entry.get().strip()
        model = self.server_model_entry.get().strip()
        api_key = self.server_key_entry.get().strip()
        chat_format = self._selected_chat_format()
        try:
            n_ctx = int(self.n_ctx_entry.get().strip() or 0) or None
        except ValueError:
            n_ctx = None
        self.model_status.configure(text=S.SERVIDOR_CONECTANDO.format(url=url), text_color=COLOR_MUTED)
        engine = self.engine

        def work(_cancel_check):
            engine.connect_server(url, model=model, api_key=api_key, n_ctx=n_ctx, chat_format=chat_format)
            return None

        def on_success(_result) -> None:
            set_server_settings(url, model, api_key)
            self.project.context_size = engine.n_ctx or None
            self.model_status.configure(
                text=S.SERVIDOR_CONECTADO.format(model=engine._llm.model or "?", url=engine._llm.root, n_ctx=engine.n_ctx,
                                                 chat_format=self._chat_format_description(chat_format)),
                text_color=COLOR_OK,
            )
            self.schedule_dirty_check()

        def on_error(exc) -> str:
            logger.error("No se pudo conectar con %s: %s", url, exc)
            message = S.ERROR_GENERICO.format(exc=describe_exception(exc))
            self.after(0, lambda: self.model_status.configure(text=message, text_color=COLOR_ERROR))
            return ""

        self.task_runner.run(S.SERVIDOR_TAREA, work, on_success=on_success, on_error=on_error, autosave=False)

    def _build_sampling_panel(self, tab, row: int) -> None:
        """Muestreo (B6): preset de prosa, valores avanzados y semilla. Se
        guarda en el proyecto; las demas tareas usan sus propios valores."""
        frame = ctk.CTkFrame(tab)
        frame.grid(row=row, column=0, sticky="ew", padx=10, pady=(4, 10))
        ctk.CTkLabel(frame, text=S.MUESTREO_DE_LA_PROSA_SE,
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=8, sticky="w", padx=8, pady=(6, 2))
        ctk.CTkLabel(frame, text=S.PRESET).grid(row=1, column=0, sticky="w", padx=8)
        self.sampling_preset_menu = ctk.CTkOptionMenu(frame, values=PRESET_CHOICES, width=150,
                                                      command=self._on_sampling_preset)
        self.sampling_preset_menu.grid(row=1, column=1, sticky="w")
        self.sampling_entries: Dict[str, ctk.CTkEntry] = {}
        fields = [("temperature", S.TEMPERATURA), ("min_p", "min_p"), ("top_p", "top_p"), ("top_k", "top_k"),
                  ("repeat_penalty", S.PENALIZ_REPETICION), ("presence_penalty", S.PRESENCIA),
                  ("frequency_penalty", S.FRECUENCIA)]
        for i, (name, label) in enumerate(fields):
            r, c = 2 + i // 4, (i % 4) * 2
            ctk.CTkLabel(frame, text=f"{label}:").grid(row=r, column=c, sticky="e", padx=(8, 4), pady=2)
            entry = ctk.CTkEntry(frame, width=70)
            entry.grid(row=r, column=c + 1, sticky="w", pady=2)
            entry.bind("<KeyRelease>", lambda _e: self.sampling_preset_menu.set(PRESET_CUSTOM))
            self.sampling_entries[name] = entry
        ctk.CTkLabel(frame, text=S.SEMILLA_VACIO_ALEATORIA).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 8))
        self.seed_entry = ctk.CTkEntry(frame, width=110)
        self.seed_entry.grid(row=4, column=2, sticky="w", pady=(4, 8))
        self.use_last_seed_btn = ctk.CTkButton(frame, text=S.USAR_LA_ULTIMA, width=110, command=self._use_last_seed)
        self.use_last_seed_btn.grid(
            row=4, column=3, sticky="w", padx=6, pady=(4, 8))
        self.last_seed_label = ctk.CTkLabel(frame, text="", text_color=COLOR_MUTED)
        self.last_seed_label.grid(row=4, column=4, columnspan=4, sticky="w", padx=6, pady=(4, 8))
        self._load_sampling_into_ui()
        apply_tab_order(
            self.tab_model,
            self.model_combo, self.refresh_models_btn, self.browse_model_btn, self.load_model_btn,
            self.n_ctx_entry, self.n_gpu_layers_entry, self.suggest_layers_btn, self.n_threads_entry,
            self.flash_attn_check, self.n_batch_entry, self.n_ubatch_entry, self.kv_cache_menu,
            self.chat_format_menu, self.sampling_preset_menu, list(self.sampling_entries.values()),
            self.seed_entry, self.use_last_seed_btn,
        )

    def _load_sampling_into_ui(self) -> None:
        cfg = self.project.sampling
        self.sampling_preset_menu.set(cfg.preset)
        self._show_sampling_values(cfg.prose())
        self.seed_entry.delete(0, "end")
        if cfg.seed is not None:
            self.seed_entry.insert(0, str(cfg.seed))

    def _show_sampling_values(self, settings: SamplingSettings) -> None:
        for name, entry in self.sampling_entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(getattr(settings, name)))

    def _on_sampling_preset(self, preset: str) -> None:
        if preset in PROSE_PRESETS:
            self._show_sampling_values(PROSE_PRESETS[preset])

    def _use_last_seed(self) -> None:
        seed = getattr(self.engine, "last_seed", None)
        if seed is None:
            messagebox.showinfo(APP_TITLE, S.TODAVIA_NO_SE_GENERO_NADA)
            return
        self.seed_entry.delete(0, "end")
        self.seed_entry.insert(0, str(seed))

    def _sync_sampling(self) -> None:
        preset = self.sampling_preset_menu.get()
        values = {name: entry.get() for name, entry in self.sampling_entries.items()}
        custom = SamplingSettings.from_dict(values, self.project.sampling.custom_prose)
        if preset != PRESET_CUSTOM:
            custom = self.project.sampling.custom_prose
        self.project.sampling = SamplingConfig(preset=preset, custom_prose=custom,
                                               seed=parse_seed(self.seed_entry.get()))
        if isinstance(self.engine, LocalStoryEngine):
            self.engine.sampling = self.project.sampling
        seed = getattr(self.engine, "last_seed", None)
        if seed is not None:
            self.last_seed_label.configure(text=S.ULTIMA_SEMILLA_USADA.format(seed=seed))

    def _selected_chat_format(self) -> str:
        return chat_format_from_label(self.chat_format_menu.get())

    def _resolve_model_selection(self, value: str) -> str:
        if value in self._model_paths:
            return self._model_paths[value]
        return value if os.path.isabs(value) else os.path.join(MODELS_DIR, value)

    def _on_model_selected(self, value: str) -> None:
        """Al elegir un modelo: formato de chat y opciones de carga usados con
        el la ultima vez en esta PC, y su informacion (cabecera GGUF)."""
        if not value or value.startswith("("):
            self.model_info_label.configure(text="")
            return
        path = self._resolve_model_selection(value)
        saved = get_chat_format_for_model(path)
        key = saved if saved in CHAT_FORMAT_CHOICES else CHAT_FORMAT_AUTO
        self.chat_format_menu.set(CHAT_FORMAT_LABELS[key])
        options = get_model_settings(path)
        self._apply_model_options(options)
        if os.path.isfile(path):
            self._current_model_info = model_info(path)
            text = self._current_model_info.summary_es()
            if not options and self._current_model_info.trained_context:
                # Primera vez con este modelo: contexto = el entrenado, como mucho 16k.
                self._set_entry(self.n_ctx_entry, str(min(self._current_model_info.trained_context, 16384)))
            self.model_info_label.configure(text=text)
        else:
            self._current_model_info = None
            self.model_info_label.configure(text="")

    @staticmethod
    def _set_entry(entry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    def _apply_model_options(self, options: dict) -> None:
        if "n_ctx" in options and isinstance(options["n_ctx"], int):
            self._set_entry(self.n_ctx_entry, str(options["n_ctx"]))
        if "n_gpu_layers" in options and isinstance(options["n_gpu_layers"], int):
            self._set_entry(self.n_gpu_layers_entry, str(options["n_gpu_layers"]))
        if "n_threads" in options:
            self._set_entry(self.n_threads_entry, str(options["n_threads"] or ""))
        if "flash_attn" in options:
            self.flash_attn_var.set(bool(options["flash_attn"]))
        if "n_batch" in options:
            self._set_entry(self.n_batch_entry, str(options["n_batch"] or ""))
        if "n_ubatch" in options:
            self._set_entry(self.n_ubatch_entry, str(options["n_ubatch"] or ""))
        if options.get("kv_cache_type") in KV_CACHE_TYPES:
            self.kv_cache_menu.set(options["kv_cache_type"])

    def _on_estimate_vram(self) -> None:
        """P2: cuanto ocupa el modelo elegido con este n_ctx/cache KV y cuantas
        capas conviene poner en la GPU (se completa el campo)."""
        info = getattr(self, "_current_model_info", None)
        if info is None or info.error:
            messagebox.showinfo(APP_TITLE, S.ELIGE_PRIMERO_UN_MODELO_GGUF)
            return
        try:
            n_ctx = int(self.n_ctx_entry.get()) or (info.trained_context or 8192)
        except ValueError:
            n_ctx = info.trained_context or 8192
        estimate = estimate_vram(info, n_ctx, self.kv_cache_menu.get(), query_free_vram_bytes(), query_total_ram_bytes())
        if estimate.suggested_gpu_layers is not None and self._gpu_available:
            self._set_entry(self.n_gpu_layers_entry, str(estimate.suggested_gpu_layers))
        color = COLOR_OK if estimate.fits_fully else (COLOR_WARN if estimate.fits_fully is False else COLOR_MUTED)
        self.model_info_label.configure(text=f"{info.summary_es()}\n{estimate.message}", text_color=color)

    def _on_chat_format_changed(self, _label: str = "") -> None:
        """Cambiar el formato no requiere recargar el modelo: se aplica a la
        proxima llamada y se recuerda para este modelo."""
        choice = self._selected_chat_format()
        if self.engine.is_loaded and not self.busy:
            self.engine.set_chat_format(choice)
            if self.engine.model_path:
                set_chat_format_for_model(self.engine.model_path, choice)
            self.model_status.configure(
                text=S.FORMATO_DE_CHAT_ACTUAL.format(description=self._chat_format_description()), text_color=COLOR_OK,
            )

    def _chat_format_description(self, choice: Optional[str] = None) -> str:
        choice = choice or self._selected_chat_format()
        try:
            label = self.engine.formatter.label
        except Exception:  # noqa: BLE001 - motores de prueba sin formateador
            label = None
        if not label:
            return CHAT_FORMAT_LABELS.get(choice, "")
        if choice == CHAT_FORMAT_AUTO:
            return S.ETIQUETA_AUTO.format(label=label)
        return label

    def _model_dirs(self) -> List[str]:
        dirs = [MODELS_DIR]
        extra = (self.prefs.get("models_dir") or "").strip() if hasattr(self, "prefs") else ""
        if extra and os.path.isdir(extra) and os.path.abspath(extra) != os.path.abspath(MODELS_DIR):
            dirs.append(extra)
        return dirs

    def _list_models(self) -> list[str]:
        self._model_paths = {}
        labels = []
        for folder in self._model_dirs():
            for entry in list_model_entries(folder):
                label = entry.label if folder == MODELS_DIR else f"{entry.label} [{folder}]"
                self._model_paths[label] = entry.path
                labels.append(label)
        return labels

    def _refresh_models(self) -> None:
        values = self._list_models() or [NO_MODELS_LABEL]
        self.model_combo.configure(values=values)
        self.model_combo.set(values[0])
        self._on_model_selected(values[0])

    def _browse_model(self) -> None:
        path = filedialog.askopenfilename(title=S.SELECCIONA_UN_MODELO_GGUF, filetypes=[(S.GGUF, "*.gguf")])
        if path:
            self.model_combo.set(path)
            self._on_model_selected(path)

    def _select_model_path(self, path: str) -> None:
        for label, known in self._model_paths.items():
            if os.path.normcase(known) == os.path.normcase(path):
                self.model_combo.set(label)
                self._on_model_selected(label)
                return
        self.model_combo.set(path)
        self._on_model_selected(path)

    def _restore_last_model_selection(self) -> None:
        """Preselecciona (sin cargar) el ultimo modelo usado en esta PC."""
        last = get_last_model()
        if last and os.path.isfile(last):
            self._select_model_path(last)

    def _restore_project_model(self) -> None:
        """Al abrir un proyecto: preselecciona su modelo y contexto, con un
        aviso explicito si el archivo ya no esta (antes se ignoraba)."""
        stored = self.project.model_path
        if not stored:
            return
        path = None
        for folder in self._model_dirs():
            candidate = resolve_model_path(stored, folder)
            if candidate and os.path.isfile(candidate):
                path = candidate
                break
        if path is None:
            self.model_status.configure(
                text=(S.ESTE_PROYECTO_SE_ESCRIBIO_CON.format(stored=os.path.basename(stored))),
                text_color=COLOR_WARN,
            )
            return
        self._select_model_path(path)
        if self.project.context_size:
            self._set_entry(self.n_ctx_entry, str(self.project.context_size))
        loaded = getattr(self.engine, "model_path", None)
        if not (loaded and os.path.normcase(loaded) == os.path.normcase(path)):
            self.model_status.configure(
                text=S.MODELO_DEL_PROYECTO_SELECCIONADO_PULSA.format(path=os.path.basename(path)),
                text_color=COLOR_MUTED,
            )

    def _read_load_options(self) -> Optional[dict]:
        try:
            n_ctx = int(self.n_ctx_entry.get())
            if n_ctx < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_TITLE, S.CONTEXTO_N_CTX_INVALIDO_DEBE)
            return None
        try:
            n_gpu_layers = int(self.n_gpu_layers_entry.get())
            if n_gpu_layers < -1:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                APP_TITLE, S.CAPAS_EN_GPU_N_GPU
            )
            return None
        try:
            n_threads = _parse_optional_int(self.n_threads_entry.get())
            if n_threads is not None and n_threads <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                APP_TITLE, S.HILOS_CPU_N_THREADS_INVALIDO
            )
            return None
        try:
            n_batch = _parse_optional_int(self.n_batch_entry.get())
            n_ubatch = _parse_optional_int(self.n_ubatch_entry.get())
            if (n_batch is not None and n_batch <= 0) or (n_ubatch is not None and n_ubatch <= 0):
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_TITLE, S.N_BATCH_N_UBATCH_INVALIDO)
            return None
        flash_attn = bool(self.flash_attn_var.get())
        kv = self.kv_cache_menu.get()
        if kv != "f16" and not flash_attn:
            messagebox.showwarning(APP_TITLE, S.LA_CACHE_KV_REQUIERE_FLASH.format(kv=kv))
            return None
        return dict(n_ctx=n_ctx, n_threads=n_threads, n_gpu_layers=n_gpu_layers, flash_attn=flash_attn,
                    n_batch=n_batch, n_ubatch=n_ubatch, kv_cache_type=kv)

    def _load_model(self) -> None:
        if self.busy:
            messagebox.showwarning(
                APP_TITLE, S.ESPERA_ANTES_DE_CARGAR_MODELO,
            )
            return
        selected = self.model_combo.get()
        if not selected or selected.startswith("("):
            messagebox.showwarning(APP_TITLE, S.SELECCIONA_UN_ARCHIVO_GGUF_VALIDO)
            return
        options = self._read_load_options()
        if options is None:
            return
        path = self._resolve_model_selection(selected)
        info = model_info(path) if os.path.isfile(path) else None
        if info is not None and info.missing_parts:
            messagebox.showerror(APP_TITLE, info.summary_es())
            return
        trained = info.trained_context if info else None
        if trained and options["n_ctx"] > trained and not messagebox.askyesno(
            APP_TITLE,
            S.PEDISTE_N_CTX_PERO_ESTE.format(n_ctx=options['n_ctx'], trained=trained),
        ):
            return
        chat_format = self._selected_chat_format()
        self.model_status.configure(text=S.CARGANDO_MODELO_ESTADO.format(path=os.path.basename(path)), text_color=COLOR_MUTED)
        self.update_idletasks()
        engine = self.engine

        def work(_cancel_check):
            call_supported(engine.load, path, chat_format=chat_format, **options)
            return None

        def on_success(_result) -> None:
            self.project.model_path = portable_model_path(path, MODELS_DIR)
            actual_ctx = getattr(engine, "n_ctx", None)
            actual_ctx = actual_ctx if isinstance(actual_ctx, int) else options["n_ctx"]
            self.project.context_size = actual_ctx or None
            set_chat_format_for_model(path, chat_format)
            saved = dict(options)
            set_model_settings(path, saved)
            extras = []
            if options["n_threads"]:
                extras.append(f"n_threads={options['n_threads']}")
            if options["flash_attn"]:
                extras.append(S.FLASH_ATTENTION_DETALLE)
            if options["kv_cache_type"] != "f16":
                extras.append(S.CACHE_KV_DETALLE.format(kv_cache_type=options['kv_cache_type']))
            extra = f", {', '.join(extras)}" if extras else ""
            self.model_status.configure(
                text=(S.MODELO_CARGADO_N_CTX_N.format(path=os.path.basename(path), actual_ctx=actual_ctx,
                                                      n_gpu_layers=options['n_gpu_layers'], extra=extra,
                                                      chat_format=self._chat_format_description(chat_format))),
                text_color=COLOR_OK,
            )
            self.schedule_dirty_check()

        def on_error(exc) -> str:
            logger.error("No se pudo cargar el modelo %s: %s", path, exc)
            message = S.ERROR_GENERICO.format(exc=describe_exception(exc))
            self.after(0, lambda: self.model_status.configure(text=message, text_color=COLOR_ERROR))
            return ""  # el error queda en la pestana, sin ventana extra

        self.task_runner.run(S.CARGANDO_MODELO_TAREA.format(path=os.path.basename(path)), work, on_success=on_success,
                             on_error=on_error, autosave=False)
