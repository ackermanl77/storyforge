# Chapter Generation Workflow

## Goal

Generate one chapter's prose, up to its `target_words`, from a local GGUF model — in sections rather than one call, and without exceeding the loaded model's context window.

## Steps

1. Load a model in the **Modelo** tab.
2. In **Capitulos**, set the chapter's title and "Palabras objetivo" (clamped to `MAX_WORDS_PER_CHAPTER`).
3. Click "Generar". If the chapter already has content, you'll be asked to confirm before it's overwritten.
4. Watch live progress (`words generated / target`) as each ~900-word section streams in.
5. "Cancelar" (or Esc) stops mid-section — whatever was generated is kept, and "Continuar" resumes from it. "Continuar desde el cursor" resumes from the insert mark (text after it is replaced; previous version saved to history). While a chapter is being written its text box is read-only.
6. On success, the app automatically requests a short summary of the chapter (`LocalStoryEngine.summarize()`) to use as continuity context for the next chapter, instead of a raw text cutoff.

## Implementation

- `app/engine.py::LocalStoryEngine.generate_chapter()` loops, requesting `SECTION_TARGET_WORDS` (~900) words per call, until the chapter's `target_words` is reached or `MAX_SECTIONS_PER_CHAPTER` sections have been generated (whichever comes first — a safety cap against a model that never converges).
- The first section's prompt is the chapter's system prompt (plot/characters/setting/previous-chapters summary/this chapter's outline, from `app/prompts.py::build_chapter_system_prompt()`) plus "Begin the chapter now"; every later section is a continuation prompt (`build_continuation_prompt()`) built from the **tail** of what's been written so far (not the start) — `app/prompts.py::_trim_words_tail()` — so the model picks up mid-scene instead of losing the thread or restarting.
- **Context overflow handling**: `LocalStoryEngine._complete_with_shrinking_budget()` tries each level in `CONTEXT_BUDGET_LEVELS` (full context → progressively smaller plot/characters/setting/previous-chapters/tail budgets) until one fits the loaded model's `n_ctx`, using the model's own tokenizer (`Llama.tokenize()`) when available, or a word-count-based estimate (`TOKENS_PER_WORD_ESTIMATE`) otherwise. Only raises `ContextOverflowError` if even the smallest level doesn't fit.
- `progress_callback(text, words, target)` fires after every section so the GUI can show live progress; `cancel_check()` is polled between sections (not mid-section — a request to the model can't be interrupted once sent).

- Prompts are `prompts.ChatPrompt`s rendered through the model's chat template (`app/chat_format.py`, "Formato de chat" on the Modelo tab); in chat mode a continuation pre-fills the assistant turn with the chapter's own ending so the model continues the prose. The continuation tail fills the free context (`_dynamic_tail_words()`), not a fixed 400 words.
- `finish_reason` is read: a section cut by `max_tokens` continues the same sentence instead of starting a new paragraph; a natural end at >= 80% of the target ends the chapter.
- Previous-chapter context (`build_previous_context()`) is built newest-first and always includes chapter N-1's summary and closing lines.

## Known limits

- A chapter can legitimately take 15-40 minutes on CPU per `models/README.txt`'s own estimate for the recommended model size — see `docs/workflows/reliability/workflow.md` for what protects that much work from being lost to a crash or accidental close.
- A `summarize()` failure is logged and shown in the chapter's status line; the summary is then marked missing and can be regenerated. Summaries are marked stale whenever the chapter text changes (`Chapter.summary_source_hash`).
