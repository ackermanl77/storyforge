# Chapter Generation Workflow

## Goal

Generate one chapter's prose, up to its `target_words`, from a local GGUF model — in sections rather than one call, and without exceeding the loaded model's context window.

## Steps

1. Load a model in the **Modelo** tab.
2. In **Capitulos**, set the chapter's title and "Palabras objetivo" (clamped to `MAX_WORDS_PER_CHAPTER`).
3. Click "Generar". If the chapter already has content, you'll be asked to confirm before it's overwritten.
4. Watch live progress (`words generated / target`) as each ~900-word section streams in.
5. "Cancelar" stops after the current section finishes (not mid-section) — whatever was generated up to that point is kept.
6. On success, the app automatically requests a short summary of the chapter (`LocalStoryEngine.summarize()`) to use as continuity context for the next chapter, instead of a raw text cutoff.

## Implementation

- `app/engine.py::LocalStoryEngine.generate_chapter()` loops, requesting `SECTION_TARGET_WORDS` (~900) words per call, until the chapter's `target_words` is reached or `MAX_SECTIONS_PER_CHAPTER` sections have been generated (whichever comes first — a safety cap against a model that never converges).
- The first section's prompt is the chapter's system prompt (plot/characters/setting/previous-chapters summary/this chapter's outline, from `app/prompts.py::build_chapter_system_prompt()`) plus "Begin the chapter now"; every later section is a continuation prompt (`build_continuation_prompt()`) built from the **tail** of what's been written so far (not the start) — `app/prompts.py::_trim_words_tail()` — so the model picks up mid-scene instead of losing the thread or restarting.
- **Context overflow handling**: `LocalStoryEngine._complete_with_shrinking_budget()` tries each level in `CONTEXT_BUDGET_LEVELS` (full context → progressively smaller plot/characters/setting/previous-chapters/tail budgets) until one fits the loaded model's `n_ctx`, using the model's own tokenizer (`Llama.tokenize()`) when available, or a word-count-based estimate (`TOKENS_PER_WORD_ESTIMATE`) otherwise. Only raises `ContextOverflowError` if even the smallest level doesn't fit.
- `progress_callback(text, words, target)` fires after every section so the GUI can show live progress; `cancel_check()` is polled between sections (not mid-section — a request to the model can't be interrupted once sent).

## Known limits

- Cancellation is section-granular, not token-granular: if a single section is mid-generation, cancelling waits for that call to finish before stopping.
- A chapter can legitimately take 15-40 minutes on CPU per `models/README.txt`'s own estimate for the recommended model size — see `docs/workflows/reliability/workflow.md` for what protects that much work from being lost to a crash or accidental close.
- `summarize()`'s failure (e.g. a transient context overflow) is swallowed silently — the chapter's generated content is never lost because of it, but the next chapter then falls back to a raw trimmed excerpt instead of a real summary (`build_previous_context()`).
