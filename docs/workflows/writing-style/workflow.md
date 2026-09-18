# Writing Style Emphasis

## Goal

Let the user pick a broad writing-style emphasis (Narrativa, Descriptiva, Creativa, Dialogo, Poetica, Accion rapida) that applies to the whole story, on top of the app's fixed `STYLE_GUIDE` formatting conventions (third-person narration, `*italics*` for internal thoughts, quoted dialogue, etc.) — not a replacement for them.

## Steps

1. In the **Esquema** tab's controls row, set "Tipo de escritura" (next to "Numero de capitulos"). Default is "(Por defecto)" — no extra emphasis, only the base `STYLE_GUIDE`.
2. The selection applies to the **whole project**, not per chapter — there is deliberately no per-chapter override. It affects both "Generar esquema completo" and every chapter's "Generar" in the **Capitulos** tab, since both read `project.writing_style` directly.
3. Saved with the project (`.json`); persists across save/load like plot/characters/setting.

## Implementation

- `app/project.py::WRITING_STYLES` is the fixed list of valid values; `Project.writing_style: str` holds the current selection (`""` = none). `Project.to_dict()`/`Project.load()` persist and restore it; a project file saved before this feature existed has no `"writing_style"` key and loads as `""` (no emphasis), not an error.
- `app/prompts.py::WRITING_STYLE_INSTRUCTIONS` maps each label to one English instruction sentence (output is always requested in English regardless of the label's Spanish name, consistent with every other prompt in this app). `build_writing_style_instruction(project)` looks up the current selection and returns a `WRITING STYLE EMPHASIS: ...` block, or `""` if unset or if the stored value doesn't match any known style (e.g. an old project file with a since-removed value) — unknown values are silently ignored rather than raising.
- That block is inserted into both `build_chapter_system_prompt()` (right before `STYLE_GUIDE`, so the formatting rules still apply) and `build_outline_prompt()` (so the generated beat sheet's emphasis — e.g. more scene-setting beats for "Descriptiva", faster-paced turning points for "Accion rapida" — matches what the prose generation will later be asked to lean into).
- `app/gui.py`'s `StoryForgeApp.writing_style_menu` (a `CTkOptionMenu` in the Esquema tab) is the only UI control; `_sync_all()`/`_load_into_ui()` translate between its display label and `project.writing_style` (`WRITING_STYLE_DEFAULT_LABEL` ↔ `""`).

## Known limits

- No per-chapter override — a project mixing very different chapter styles (e.g. one dialogue-heavy, one descriptive) can't express that through this control; the whole story gets one emphasis, or none.
- The instruction is a single guidance sentence, not a hard constraint — like the rest of `STYLE_GUIDE`, a local model may follow it loosely or ignore it, especially a smaller/less-instructable one (see the README's "Limitaciones reales" on model quality).
