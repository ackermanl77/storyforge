# Word-Repetition Reduction Workflow

## Goal

Flag words used more often than a natural-language baseline in a chapter, and optionally replace the excess occurrences with synonyms — entirely offline once its data is available.

## Steps

1. Generate or write a chapter's content in **Capitulos**.
2. Click "Reporte de repeticion" to see the top overused words (>= a threshold per 1000 words, ignoring stopwords and short words) without changing the text.
3. Click "Reducir repeticion" to actually rewrite: the **first** occurrence of a flagged word is always left untouched (the "anchor"); occurrences from the 2nd onward are replaced with a WordNet synonym not already used nearby, up to `max_replacements_per_word` (default 6) substitutions per word.

## Implementation

- `app/repetition.py::_ensure_nltk_data()` looks for NLTK's `stopwords`/`wordnet` corpora first in a local `nltk_data/` folder next to the app, then tries to download them (~35 MB, once) if missing and internet is available. The result is cached for the process lifetime so a missing-internet case doesn't retry on every call. WordNet counts as present as `corpora/wordnet.zip` too: `nltk.downloader` leaves it zipped and NLTK reads it from the zip, but the check used to ask only for `corpora/wordnet`, so synonym substitution silently never ran (fixed 2026-10-02, regression test in `tests/test_repetition.py`). Only `stopwords` and `wordnet` are needed; `omw-1.4` (other languages' WordNets, 26 MB) is not downloaded or bundled.
- If NLTK data is unavailable at all, `word_frequencies()`/`overused_words()` still work using a small built-in stopword list (`_FALLBACK_STOPWORDS`) — repetition **detection** always works offline; only synonym **substitution** (`_best_synonym()`, which needs WordNet) is unavailable without the corpora.
- `reduce_repetition()` is a rule-based pass, not a model rewrite: it only swaps the flagged word itself via regex substitution (`_TOKEN_RE`), preserving sentence structure, and matches the replacement's capitalization to the original (`_match_case()`).

## Known limits

- `_best_synonym()` doesn't check the word's grammatical role in its actual sentence (tense, part of speech as used) — it picks the most common synonym across WordNet's first 5 synsets for that surface form. This can occasionally produce a synonym that doesn't grammatically fit the sentence it lands in; review the result rather than trusting it blindly, especially for verbs.
- Both actions are irreversible in the UI (no undo) — they overwrite `content_box` directly. Keep a saved copy of the project if you want to compare before/after.
