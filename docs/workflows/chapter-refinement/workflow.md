# Chapter Refinement

## Goal

Revise an already-generated chapter per a specific instruction ("make it darker", "shorten the dialogue in the last scene") instead of only being able to regenerate the whole thing from scratch or hand-edit it directly — inspired by a competing tool's chat-based iterative refinement, adapted here as a single-shot instruction rather than a multi-turn conversation (see "Known limits" for why).

## Steps

1. Generate a chapter's content first — there's nothing to refine before that (the button warns instead of doing anything if `content` is empty).
2. In that chapter's panel, at the bottom, type an instruction into "Instruccion de refinamiento" and click "Aplicar refinamiento".
3. Confirm the prompt — refining reprocesses the whole chapter and shows a side-by-side diff preview (Aceptar / Aceptar y seguir refinando / Descartar); nothing is replaced until you accept (the version you had is saved to "Versiones anteriores" first — see `docs/workflows/version-history/workflow.md` — so this is recoverable).
4. The model rewrites the chapter applying your instruction; progress isn't streamed section-by-section the way initial generation is (see "Known limits").

## Implementation

- `app/prompts.py::build_refine_chapter_prompt()` builds the revision prompt: the editing instruction, the project's `writing_style` emphasis, `STYLE_GUIDE`, and the chapter's current text. Deliberately does **not** include plot/characters/setting (unlike `build_chapter_system_prompt()`) — prioritizes keeping as much of the actual chapter text intact as the context window allows, since that's what's actually being edited.
- `app/engine.py::LocalStoryEngine.refine_chapter()` never trims the chapter (it used to, via a `max_content_words` budget -- and the revised trimmed text then replaced the whole chapter, silently dropping its ending). If the whole chapter plus the expected output (`REFINE_OUTPUT_HEADROOM`, 1.3x its length) fits in `n_ctx`, it is one call; otherwise `_split_for_refine()` splits it into consecutive chunks (paragraphs first, then sentences, then words as a last resort), each is refined with a "part i of n" note in the prompt, and the results are rejoined in order. An empty part aborts the whole refine with an error rather than dropping text. Uses `stop=["[END]"]` only, not the prose default (`"\n\nChapter"`).
- The output token budget is `max(chapter.word_count(), chapter.target_words)` — a chapter longer than its own target reserves output space matching its actual length, not the (possibly smaller) target.
- `app/ui_chapter_editor.py`'s `ChapterPanel._on_refine()` mirrors `_on_generate()`'s structure: same engine-loaded/busy checks, same confirm-before-overwrite, same background thread + `self.app.after(0, ...)` error reporting (careful to capture the exception message into a plain variable first — see `docs/PROJECT_STATUS.md`'s "Recently Fixed" for why that specific pattern matters). Unlike `_on_generate()`, there's no section-by-section progress callback — `refine_chapter()` is one call, so the status label just says "Refinando..." until it's done.

## Known limits

- **Not actually a chat / multi-turn conversation**, despite the inspiration — each click is a fresh, independent revision of whatever `chapter.content` currently is; there's no memory of previous refinement instructions beyond their cumulative effect on the text itself. Asking for one change, then a second unrelated one, works fine (each one revises the latest text) — but you can't say "undo that last change" as an instruction; use "Versiones anteriores" instead.
- **Long chapters are refined in parts** when they do not fit the context window whole: each part gets the same instruction but not the other parts, so instructions that depend on the whole chapter at once work best with a larger `n_ctx` (Modelo tab). Parts are rejoined with a blank line, so a single oversized paragraph that had to be split mid-paragraph comes back as two paragraphs.
- No streaming/progress feedback during the (potentially several-minutes-long) call — this is a known gap, not a deliberate design choice; adding a progress callback to `refine_chapter()` would need it to also generate in sections like `generate_chapter()` does, which wasn't attempted here.
