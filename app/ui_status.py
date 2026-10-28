"""
Barra de estado global (F2): operacion en curso y tiempo transcurrido,
tokens/s, ETA, barra de progreso, medidor de contexto (prompt + respuesta
reservada / n_ctx, con el nivel de presupuesto usado), "Ver prompt",
"Detener" y el total de palabras del proyecto.

Lee LocalStoryEngine.stats (GenerationStats) cada ~250 ms desde el hilo
principal; el motor nunca toca widgets.
"""
from __future__ import annotations

import time
from typing import Optional

import customtkinter as ctk

from . import strings_es as S
from .ui_dialogs import COLOR_ERROR, COLOR_MUTED, COLOR_OK, COLOR_WARN

POLL_MS = 250


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--"
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        return S.DURACION_HORAS.format(hours=seconds // 3600, minutes=seconds % 3600 // 60)
    return f"{seconds // 60}:{seconds % 60:02d}"


def describe_stats(stats, elapsed: float) -> str:
    """Texto de la barra para un GenerationStats (funcion pura, se prueba)."""
    parts = [f"{stats.operation or S.TRABAJANDO} · {format_duration(elapsed)}"]
    tps = stats.tokens_per_second
    if tps:
        parts.append(S.TOK_S.format(tps=tps))
    if stats.prompt_eval_seconds:
        parts.append(S.PROMPT_S.format(prompt_eval_seconds=stats.prompt_eval_seconds))
    if stats.target_words:
        parts.append(S.ESTADO_PALABRAS.format(words_written=stats.words_written, target_words=stats.target_words))
        eta = stats.eta_seconds()
        if eta is not None:
            parts.append(S.ETA.format(eta=format_duration(eta)))
    elif stats.total_parts:
        parts.append(S.PARTE.format(part=stats.part, total_parts=stats.total_parts))
    if stats.seed is not None:
        parts.append(S.SEMILLA.format(seed=stats.seed))
    return "  |  ".join(parts)


def describe_context(stats) -> str:
    frac = stats.context_fraction
    if frac is None or not stats.prompt_tokens:
        return S.CONTEXTO_VACIO
    level = S.NIVEL_3.format(budget_level=stats.budget_level) if stats.budget_level and stats.budget_level > 1 else ""
    return (S.CONTEXTO_MEDIDOR.format(percent=frac * 100, prompt_tokens=stats.prompt_tokens,
                                      max_tokens=stats.max_tokens, n_ctx=stats.n_ctx, level=level))


# UI2: Detener is gold only while there is something to stop; disabled, it was gold too and read as
# active. (light, dark) pairs, as CustomTkinter takes them.
STOP_ACTIVE_COLOR = "#8a6a2f"
STOP_IDLE_COLOR = ("gray72", "gray30")


class StatusBar(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, height=34)
        self.app = app
        self._started: Optional[float] = None
        self._poll_id = None
        self.grid_columnconfigure(1, weight=1)

        self.op_label = ctk.CTkLabel(self, text=S.LISTO, anchor="w", text_color=COLOR_MUTED)
        self.op_label.grid(row=0, column=0, sticky="w", padx=(10, 6))
        self.progress = ctk.CTkProgressBar(self, width=160)
        self.progress.set(0)
        self.progress.grid(row=0, column=1, sticky="w", padx=6)
        # UI2: only while something runs -- idle, a half- or fully-filled bar read as "busy".
        self.progress.grid_remove()
        self.context_label = ctk.CTkLabel(self, text=S.CONTEXTO_VACIO, text_color=COLOR_MUTED)
        self.context_label.grid(row=0, column=2, padx=6)
        self.prompt_btn = ctk.CTkButton(self, text=S.VER_PROMPT, width=90, command=app.show_last_prompt)
        self.prompt_btn.grid(row=0, column=3, padx=4, pady=3)
        self.stop_btn = ctk.CTkButton(
            self, text=S.DETENER, width=80, state="disabled", fg_color=STOP_IDLE_COLOR, hover_color="#6e5526",
            command=app.stop_current_task,
        )
        self.stop_btn.grid(row=0, column=4, padx=4, pady=3)
        self.words_label = ctk.CTkLabel(self, text="", text_color=COLOR_MUTED)
        self.words_label.grid(row=0, column=5, padx=(6, 10))

    def start(self, label: str) -> None:
        self._started = time.monotonic()
        self.op_label.configure(text=f"{label}...", text_color=("#1a1a1a", "#e6e6e6"))
        self.progress.grid()
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.stop_btn.configure(state="normal", fg_color=STOP_ACTIVE_COLOR)
        self._schedule()

    def stop(self, outcome: str = "ok") -> None:
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:  # noqa: BLE001
                pass
            self._poll_id = None
        self.refresh()
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.progress.grid_remove()
        self.stop_btn.configure(state="disabled", fg_color=STOP_IDLE_COLOR)
        elapsed = format_duration(time.monotonic() - self._started) if self._started else "--"
        text, color = {
            "ok": (S.LISTO_TIEMPO.format(elapsed=elapsed), COLOR_OK),
            "cancelled": (S.DETENIDO.format(elapsed=elapsed), COLOR_WARN),
        }.get(outcome, (S.TERMINO_CON_ERROR.format(elapsed=elapsed), COLOR_ERROR))
        stats = getattr(self.app.engine, "stats", None)
        if stats is not None and stats.tokens_per_second:
            text += S.TOK_S_FINAL.format(tokens_per_second=stats.tokens_per_second)
        self.op_label.configure(text=text, text_color=color)
        self._started = None

    def _schedule(self) -> None:
        self._poll_id = self.after(POLL_MS, self._tick)

    def _tick(self) -> None:
        self._poll_id = None
        if self._started is None:
            return
        self.refresh()
        self._schedule()

    def refresh(self) -> None:
        stats = getattr(self.app.engine, "stats", None)
        if stats is None or self._started is None:
            return
        try:
            elapsed = time.monotonic() - self._started
            self.op_label.configure(text=describe_stats(stats, elapsed))
            frac = stats.progress_fraction
            if frac is not None:
                if str(self.progress.cget("mode")) != "determinate":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                self.progress.set(frac)
            ctx = stats.context_fraction
            color = COLOR_MUTED if ctx is None else (COLOR_ERROR if ctx > 0.9 else COLOR_WARN if ctx > 0.75 else COLOR_OK)
            self.context_label.configure(text=describe_context(stats), text_color=color)
        except Exception:  # noqa: BLE001 - nunca romper la UI por la barra
            pass

    def set_word_total(self, words: int, chapters: int) -> None:
        self.words_label.configure(text=S.PALABRAS_EN_CAPITULOS.format(words=words, chapters=chapters))
