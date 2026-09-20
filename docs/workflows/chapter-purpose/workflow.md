# Chapter Purpose

## Goal

Tell the model what narrative role a specific chapter plays (opening, climax, ending, epilogue) instead of treating every chapter as generic "the next one" — inspired by a competing tool's per-generation "Purpose" selector (Story Opening / Story Chapter / Climax Scene / Story Ending / Epilogue), adapted to this app's existing per-chapter structure.

## Steps

1. In **Capitulos**, each chapter panel has a "Proposito" dropdown between the title row and the action buttons, right under the chapter title/target-words row.
2. Choose one of Apertura / Escena climatica / Final / Epilogo, or leave it at "(Capitulo regular)" for no special instruction (the default — existing chapters and projects saved before this feature all start here).
3. Generate the chapter as usual — the instruction is included automatically.

Unlike `writing_style` (a whole-project setting in the Esquema tab), this is per chapter: chapter 1 can be "Apertura" while chapter 7 is "Escena climatica", each independently.

## Implementation

- `app/project.py::CHAPTER_PURPOSES` is the fixed list of valid values; `Chapter.purpose: str` holds the current selection (`""` = regular chapter). Persisted like every other chapter field; a project file saved before this feature existed has no `"purpose"` key and loads as `""`, not an error.
- `app/prompts.py::CHAPTER_PURPOSE_INSTRUCTIONS` maps each label to one English instruction paragraph (output is always requested in English, consistent with the rest of this app's prompts) describing what that chapter should accomplish — e.g. "Apertura" asks for the normal world and the inciting incident without resolving anything; "Final" asks to resolve the central conflict and not introduce new threads. `build_chapter_purpose_instruction(chapter)` looks it up, returning `""` for an unset or unrecognized value (e.g. an old project with a since-removed label) rather than raising.
- That instruction is inserted into `build_chapter_system_prompt()` right before the `writing_style` emphasis and the `STYLE_GUIDE` — both still apply regardless of the chosen purpose.

## Known limits

- No validation prevents picking "Apertura" for chapter 5 or "Epilogo" for chapter 1 — the app doesn't know or enforce where in the book a purpose "belongs"; it's just an instruction sent to the model, so a mismatched choice produces a mismatched chapter, not an error.
- Like `writing_style`, this is guidance, not a hard constraint — a small local model may follow it loosely, especially the more nuanced asks ("build steadily toward... don't resolve too early").
