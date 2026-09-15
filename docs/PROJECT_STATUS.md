# Project Status

## Architecture

```text
CustomTkinter desktop GUI (app/gui.py)
        |  llama-cpp-python calls, run on a background thread
        v
LocalStoryEngine (app/engine.py)
        |
        v
llama_cpp.Llama over a user-supplied GGUF model (models/*.gguf)
```

`app/gui.py::StoryForgeApp` is the only entry point into the application logic; there is no CLI and no network service. It owns a single `Project` (`app/project.py`) — plot, characters, setting, and up to `MAX_CHAPTERS` `Chapter` objects (title, outline, content, summary) — and a single `LocalStoryEngine` (`app/engine.py`), which wraps exactly one `llama_cpp.Llama` instance. All generation (outline, chapter prose, chapter summary) runs on a background `threading.Thread` so the UI stays responsive during a run that can take from a few seconds (an outline) to tens of minutes (a full chapter on CPU); `self.after(0, ...)` is used throughout to marshal results back onto the Tk main thread.

`app/prompts.py` builds every prompt sent to the model (outline, chapter system prompt, section continuation) and does the context-budget trimming (word-count based, not token based). `app/engine.py` adds token-aware overflow handling on top of that: it counts real tokens with the loaded model's own tokenizer when available, and retries a prompt at progressively smaller context budgets (`CONTEXT_BUDGET_LEVELS`) before raising `ContextOverflowError`. A chapter is generated in `SECTION_TARGET_WORDS`-sized sections (default ~900 words) rather than in one call, both because local models degrade in coherence over very long single generations and because most consumer hardware can't hold a 10,000-word generation in one context window comfortably.

`app/repetition.py` is a separate, optional post-processing step: it flags and can replace overused words using NLTK's stopwords/WordNet corpora, falling back to a small built-in stopword list and no synonym substitution if NLTK's data isn't available (offline-first by design — see `docs/workflows/repetition-reduction/workflow.md`). `app/export.py` turns a finished `Project` into a `.docx` (via `python-docx`, converting `*italic*` markers into real italic runs) or a plain `.txt`.

A single `Llama` instance is not safe for concurrent inference calls. `StoryForgeApp.busy` (set/read through `_set_engine_busy()`) is the app-wide mutual-exclusion flag that prevents two generations (or a generation and a model load, or a generation and a project switch / chapter add-remove) from running at once — see `docs/workflows/reliability/workflow.md`.

## Primary Entry Points

| Purpose | Entry point |
|---|---|
| Run from source | `python storyforge.py` (imports `app.main.main()`) |
| PyInstaller entry script | `storyforge.py` |
| GUI construction and app logic | `app/gui.py` (`StoryForgeApp`, `run()`) |
| Generation engine (outline, chapter, summary) | `app/engine.py` (`LocalStoryEngine`) |
| Prompt templates and context trimming | `app/prompts.py` |
| Project data model, word-count limits, JSON persistence | `app/project.py` |
| Word-repetition analysis/reduction (NLTK) | `app/repetition.py` |
| Export to `.docx` / `.txt` | `app/export.py` |

## Release

```text
dist/StoryForge/StoryForge.exe
```

Built with `build.bat` (installs dependencies, then `pyinstaller --noconfirm --clean storyforge.spec`). `storyforge.spec` bundles `customtkinter`, `llama_cpp`, and `docx` via `collect_all()`. The `models/` folder (with the user's own `.gguf` file inside) has to be copied next to the built `.exe` manually — it is never bundled, since model files are several GB and are not part of this repository (see `.gitignore`). NLTK's `stopwords`/`wordnet` corpora are likewise not bundled; they download once on first use of the repetition-reduction feature (see `docs/workflows/repetition-reduction/workflow.md`) and are then cached in `nltk_data/` next to the app.

Must be built on Windows — no cross-compiled `.exe` is produced from any other platform.

## Verification

```powershell
python -m unittest discover -s tests -v
```

38 tests, no `llama-cpp-python` or real model required (`tests/test_engine.py` and `tests/test_outline.py` inject a `FakeLlama` stand-in). Run this yourself before relying on a pass count — this line is not re-verified automatically as the code changes.

`app/gui.py` has no automated test coverage (CustomTkinter/Tk widgets, not exercised by the `unittest` suite); changes there have been verified with ad hoc smoke scripts that instantiate `StoryForgeApp` headlessly and drive it directly (see the "Recently Fixed" entries below for what each smoke test checked), not with a committed test file.

## Known Limitations

See the README's "Limitaciones reales que debes conocer" section for the user-facing version of these (writing quality of small local models, limited context memory, CPU generation speed, model-specific content filters). Two additional, code-level ones not covered there:

- **No GUI test suite.** Every fix under "Recently Fixed" below that touches `app/gui.py` was verified with a one-off script, not a committed regression test — a future change could silently reintroduce one of these bugs (e.g. the busy-lock gaps) with nothing failing in `python -m unittest discover -s tests`.
- **Autosave writes on the main thread.** `StoryForgeApp._autosave()` (see `docs/workflows/reliability/workflow.md`) does a blocking file write every 20 seconds while a generation is in progress. On a slow or network-mounted drive this could introduce a brief UI stutter; not something this project's scale has needed to address yet.

## Recently Fixed

- **The engine had no mutual exclusion.** `LocalStoryEngine` wraps a single `llama_cpp.Llama` instance, which is not safe for concurrent calls, but nothing stopped the user from clicking "Generar" on two different chapters at once, or generating a chapter while also generating the outline or loading a different model — each of those starts its own background thread that calls into the same engine. **Fixed**: `StoryForgeApp.busy` + `_set_engine_busy()` now disable every other entry point (all chapters' "Generar", "Generar esquema completo", "Cargar modelo", "+ Agregar capitulo", and every "Eliminar capitulo") for the duration of any one of them; newly created `ChapterPanel`s are born already disabled if a generation is in progress when they're created. See `docs/workflows/reliability/workflow.md`.
- **Regenerating a chapter silently discarded its existing content.** `ChapterPanel._on_generate()` cleared `content_box` as soon as the first section streamed in, with no confirmation — unlike "Eliminar capitulo", which already asked. **Fixed**: a chapter with existing content now needs an explicit yes/no confirmation before regenerating.
- **Switching projects mid-generation could throw into the Tk event loop.** "Nuevo proyecto" / "Abrir proyecto" destroyed and rebuilt every `ChapterPanel` via `_render_chapters()` even while a background generation thread's `progress_callback` still referenced the old (now-destroyed) `content_box` widget, which raises a Tcl "invalid command name" error the next time that callback fires. **Fixed**: both actions now refuse to run while `self.busy` is true.
- **No confirmation on exit, and no window-close handler at all.** The "Salir" menu item called `self.destroy()` directly, and there was no `WM_DELETE_WINDOW` protocol handler, so the OS close button bypassed even that. Losing an unsaved project — or a generation that had been running for 15-40 minutes — required no acknowledgement at all. **Fixed**: `_on_close()` is now wired to both the window's close button and the "Salir" menu item; it warns if a generation is in progress, then offers Save / Don't Save / Cancel (`messagebox.askyesnocancel`) before actually closing.
- **The Esquema tab's "Numero de capitulos" field didn't resync.** Opening a different project (or starting a new one) left this field showing the previous project's chapter count instead of the newly loaded project's. **Fixed**: `_load_into_ui()` now resets it.
- **No autosave for long generations.** A single chapter can take 15-40 minutes on CPU; before this, nothing was written to disk until the user explicitly saved, so a crash or unexpected close lost all of that progress. **Fixed**: a separate `autosave/autosave.json` (distinct from the user's own save file) is written every 20 seconds while `self.busy` is true, and once more immediately when a generation finishes. On startup, if that file exists, the app offers to recover it. It is discarded automatically after an explicit save, or if the user declines to save when closing (an intentional "discard" shouldn't come back as an unwanted recovery prompt next launch). See `docs/workflows/reliability/workflow.md`.
- **Outline-first workflow, and a stale-data bug found while building it** (carried over from the README's own changelog, kept here as the earliest recorded history for this project). Added the "Esquema" tab: generate a full chapter-by-chapter beat sheet up front from plot/characters/setting, edit it, then have chapter generation follow it (`build_chapter_system_prompt`'s `THIS CHAPTER'S OUTLINE` block, plus a compact all-chapter-titles overview for whole-story awareness). While building it, found that generating a chapter or the outline only synced the plot/characters/setting/outline fields from the UI into the `Project` on save/export, not on generate — so generating without saving first could silently use stale or empty data. Fixed by having both generate actions call `_sync_all()` first.
