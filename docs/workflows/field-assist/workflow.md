# Plot / Characters / Setting: Expand and Import

## Goal

Two ways to fill in Plot / Personajes / Setting faster: expand a short note into a fuller version with the local model, or import text from an existing `.txt` file — inspired by a competing tool's "expand with AI" icon and file-attachment button on its equivalent fields.

## Steps

**Expandir con IA** (needs a loaded model):
1. Write a short note in Plot, Personajes, or Setting — a sentence or two is enough.
2. Click "Expandir con IA" (next to "Importar desde archivo..." above the text box).
3. If the field already has more than ~60 words, you'll be asked to confirm — expanding **replaces** the field, it doesn't append.
4. The model develops your note into a fuller version in the same spirit (same characters/setting/premise implied, just more detail) — it's not asked to invent a different story.

**Importar desde archivo...** (no model needed, doesn't touch the engine at all):
1. Click the button, pick a `.txt` file.
2. If the field already has content, confirm the replacement.
3. The file's text replaces the field's content directly.

## Implementation

- `app/gui.py::LimitedTextBox` (used for all three fields) optionally takes `on_expand`/`on_import` callables; when given, it renders both buttons above the text box and exposes them as `self.expand_btn`/`self.import_btn` so the app-level busy-lock can find and disable `expand_btn` specifically (see below) — `import_btn` never needs disabling, since it's synchronous and never calls the engine.
- `StoryForgeApp._expand_field()` is wired the same way as every other engine-calling action in this app: checks `engine.is_loaded`/`self.busy` first, runs on a background thread, reports failure via `self.app.after(0, ...)` with the message captured into a plain variable (not referencing the `except ... as exc` name directly — see `docs/PROJECT_STATUS.md`'s "Recently Fixed" for why that matters), and is included in `_set_engine_busy()`'s disable list alongside every chapter's `generate_btn`/`refine_btn`.
- `app/prompts.py::build_expand_field_prompt()` / `app/engine.py::LocalStoryEngine.expand_field()` mirror `summarize()`'s structure closely: a fixed instruction plus the user's note, trimmed to fit the context window the same way (`_fit_text_to_token_budget()`) if the note itself is unusually long. Output is capped at `min(field's own word limit, 500)` words regardless of how large the field's actual limit is (50,000 for Plot) — expanding is meant to produce one fuller paragraph, not fill the field to its maximum.
- `StoryForgeApp._import_field()` is plain, synchronous file I/O (`Path.read_text(encoding="utf-8", errors="replace")`) wrapped in `filedialog.askopenfilename()` — no thread, no busy-lock interaction, matches every other file-picker action already in this app (`_browse_model`, `open_project`, etc.).

## Known limits

- Expand and import both **replace** the field outright — there's no "insert at cursor" or "append" option, and neither integrates with the chapter version-history mechanism (`docs/workflows/version-history/workflow.md`), since that's chapter-specific (`Chapter.push_history()`), not something `Project.plot`/`characters`/`setting` have. Undo relies entirely on the OS-level undo the `CTkTextbox` widget itself may or may not support, or not saving the project yet.
- Import doesn't validate or preview the file before replacing — a binary file or one in the wrong encoding will still "succeed" (via `errors="replace"`) but produce garbled replacement characters in the field.
