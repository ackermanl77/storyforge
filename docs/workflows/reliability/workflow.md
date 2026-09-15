# Concurrency, Exit Confirmation, and Autosave

## Goal

Protect a local generation run — which can legitimately take 15-40 minutes for a single chapter on CPU — from the three ways it was previously easy to lose: a second generation racing the same model instance, closing the app without saving, and a crash or unexpected close with no recovery path at all.

## Concurrency (the engine busy-lock)

`LocalStoryEngine` wraps exactly one `llama_cpp.Llama` instance, which is not safe for concurrent inference calls. `StoryForgeApp.busy` is the single source of truth for whether *any* engine call (a chapter, the outline, or a model load) is in flight; `_set_engine_busy(bool)` is the only place that flips it, and it disables every other entry point that could start a second one:

- every `ChapterPanel.generate_btn`
- the outline tab's "Generar esquema completo"
- the model tab's "Cargar modelo"
- "+ Agregar capitulo" and every chapter's "Eliminar capitulo" (adding/removing a chapter mid-generation would shift the `project.chapters` index the running worker thread is still using)

A `ChapterPanel` created while `self.busy` is already true (e.g. via `_apply_outline()` adding chapters) is built already disabled, instead of leaving a window where a freshly-rendered panel's button is briefly clickable.

"Nuevo proyecto" and "Abrir proyecto" also refuse to run while `self.busy` — switching projects destroys and rebuilds every `ChapterPanel` via `_render_chapters()`, and a still-running generation's `progress_callback` closure holds a reference to the old (about-to-be-destroyed) widget.

## Exit confirmation

`StoryForgeApp._on_close()` is wired to both the window's own close button (`self.protocol("WM_DELETE_WINDOW", ...)`) and the "Salir" menu item — previously the menu called `self.destroy()` directly and the close button had no handler at all. It:

1. Warns (and lets you cancel) if `self.busy` — closing now would lose the in-progress generation.
2. Otherwise asks Save / Don't Save / Cancel (`messagebox.askyesnocancel`). Cancel aborts the close entirely; "Don't Save" also discards any pending autosave (see below) since that's an intentional choice, not something to offer back as "recovered" next launch. If "Save" is chosen but the user then cancels the save-as file dialog (no `current_path` yet), the close is aborted rather than silently discarding the work anyway.

## Autosave

A generation this long deserved its own safety net independent of the user remembering to save. `AUTOSAVE_PATH` (`autosave/autosave.json`, next to the app, gitignored) is separate from the project file the user explicitly saves:

- `StoryForgeApp._autosave_tick()` re-schedules itself every `AUTOSAVE_INTERVAL_MS` (20s) for the life of the app, and only actually writes when `self.busy` is true.
- Because `ChapterPanel.sync_to_model()` reads straight from the live `content_box` widget (which the generation's `progress_callback` keeps updating section by section), `_autosave()`'s call to `_sync_all()` picks up in-progress prose, not just already-completed chapters.
- One more autosave fires immediately when a chapter or outline generation finishes, so the just-completed result (including its summary) is captured without waiting up to 20s for the next tick.
- On startup, `_offer_autosave_recovery()` checks for `autosave/autosave.json` and, if present, asks whether to load it (`current_path` stays unset — recovered content still needs an explicit "Guardar como" to pick a real destination).
- Any error writing the autosave is swallowed — it is a safety net and must never interrupt a real generation in progress.
- The autosave file is deleted after an explicit "Guardar proyecto" succeeds (it would otherwise be a stale, confusing "recover?" prompt next launch), and after the "Don't Save" choice on exit.

## Known limits

- None of this is covered by the `unittest` suite under `tests/` (which doesn't touch `app/gui.py` — see `docs/PROJECT_STATUS.md`). It has been verified with ad hoc headless smoke scripts (instantiating `StoryForgeApp` directly and calling its methods) during development, not with a committed regression test.
- The autosave write is a blocking `Project.save()` call on the Tk main thread every 20 seconds during a generation — acceptable on local disk, could stutter the UI briefly on a slow one.
