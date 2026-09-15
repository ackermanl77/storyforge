# Outline-First Beat Sheet Workflow

## Goal

Generate a chapter-by-chapter beat sheet from the plot/characters/setting before writing any prose, so a long, multi-chapter story stays coherent instead of being improvised one chapter at a time.

## Steps

1. Fill in the **Plot**, **Personajes**, and **Setting** tabs (within `MAX_PLOT_WORDS` / `MAX_CHARACTERS_WORDS` / `MAX_SETTING_WORDS`, see `app/project.py`).
2. Load a model in the **Modelo** tab.
3. In the **Esquema** tab, set "Numero de capitulos" (clamped to `MAX_CHAPTERS`) and click "Generar esquema completo".
4. If chapters already exist, you'll be asked to confirm — the title and outline of each existing chapter are replaced, but any prose already generated in `Capitulos` is kept.
5. Edit any chapter's beats directly in its `OutlinePanel` textbox before moving to the `Capitulos` tab to generate prose.

## Implementation

- `app/prompts.py::build_outline_prompt()` asks the model for exactly N chapters, each as `Chapter <n>: <title>` followed by 2-4 sentences of key events/turning points/emotional beats — a fixed, parseable plain-text format, not markdown.
- `app/prompts.py::parse_outline_response()` extracts `(title, beats)` pairs with a regex tolerant of minor formatting drift (`Chapter 1:` vs `Chapter 1.`); if the model ignores the format entirely, the whole response becomes a single "Chapter 1" fallback rather than an empty result.
- `app/engine.py::LocalStoryEngine.generate_outline()` runs this through the same shrinking context-budget retry as chapter generation (see `docs/workflows/chapter-generation/workflow.md`) before giving up with `ContextOverflowError`.
- `app/gui.py::StoryForgeApp._apply_outline()` writes the parsed titles/outlines back into existing `Chapter` objects by index, and creates new ones (up to `MAX_CHAPTERS`) for any beyond the current chapter count.
- Once a chapter has an outline, `app/prompts.py::build_chapter_system_prompt()` includes it as a mandatory `THIS CHAPTER'S OUTLINE` block, plus a compact list of every chapter's title (`build_story_outline_overview()`) so the model has awareness of the full story arc without spending much context budget on it.

## Known limits

- The outline generation call is a single, un-sectioned completion (unlike chapter prose, which is generated in sections) — very large chapter counts combined with a small model context window can hit `ContextOverflowError` even at the smallest context budget level. Reduce plot/characters/setting length or the number of chapters requested.
- If the model doesn't follow the `Chapter N: <title>` format at all, you get one chapter's worth of unstructured text back instead of N chapters — inspect and manually split the result if this happens.
