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

A generation this long deserved its own safety net independent of the user remembering to save. `StoryForgeApp.autosave_path` (`<user_data_dir()>/autosave/autosave.json`: the repo in development, `%APPDATA%\StoryForge` in the .exe, or `STORYFORGE_USER_DATA_DIR` when set) is separate from the project file the user explicitly saves:

- `StoryForgeApp._autosave_tick()` re-schedules itself every `AUTOSAVE_INTERVAL_MS` (20s) for the life of the app, and only actually writes when `self.busy` is true.
- Because `ChapterPanel.sync_to_model()` reads straight from the live `content_box` widget (which the generation's `progress_callback` keeps updating section by section), `_autosave()`'s call to `_sync_all()` picks up in-progress prose, not just already-completed chapters.
- One more autosave fires immediately when a chapter or outline generation finishes, so the just-completed result (including its summary) is captured without waiting up to 20s for the next tick.
- On startup, `_offer_autosave_recovery()` checks for `autosave/autosave.json` and, if present, asks whether to load it (`current_path` stays unset — recovered content still needs an explicit "Guardar como" to pick a real destination).
- An error writing the autosave is logged and reported once per session; it never interrupts a generation.

## Unexpected errors

`StoryForgeApp.report_callback_exception` (Tk callbacks), `threading.excepthook` (installed by `gui.run()`, marshalled to the Tk thread with `after()`) and `sys.excepthook` (`main()`) log the traceback and show a message with the log location; Ayuda > "Abrir carpeta de registros" opens `user_data_dir()`.
- The autosave file is deleted after an explicit "Guardar proyecto" succeeds (it would otherwise be a stale, confusing "recover?" prompt next launch), and after the "Don't Save" choice on exit.

## Known limits

- Partially covered by `tests/test_gui.py` (autosave failure reporting, save errors, user-data isolation, unexpected-error reporting); the busy-lock and exit confirmation are still only smoke-tested.
- Autosave (every 20 s while the engine is busy, every 60 s when the project is dirty) serializes on the Tk thread and writes on a short-lived worker thread; a generation counter makes sure a late, older write never replaces a newer one, and `_discard_autosave()` cancels pending writes. Errors are collected and shown once from the Tk thread. Every engine task goes through `app/task_runner.py::EngineTaskRunner` (busy lock, Stop, error dialogs, autosave).
