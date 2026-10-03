# Chapter Version History

## Goal

Let a destructive edit to a chapter's content (regenerate, refine, reduce repetition) be undone by keeping a bounded history of previous versions, instead of the only safety net being a confirmation dialog before the loss happens — inspired by a competing tool that keeps generation history for exactly this reason.

## Steps

1. Any of "Generar" / "Continuar" / "Desde el cursor" / "Reintentar" (when the chapter already has content), "Aplicar refinamiento" (on Aceptar), a right-click selection rewrite, a find/replace (chapter or project-wide), "Reducir repetición" or a restore saves the chapter's current content as a version before replacing it.
2. Click "Versiones anteriores (N)" on a chapter panel (the count updates automatically) — clicking it with zero versions just shows an info message instead of opening anything.
3. Pick a version from the dropdown (most recent first) to preview it in the read-only box below.
4. "Restaurar esta version" replaces the chapter's current content with the selected version — and, symmetrically, saves what was there *before* restoring as a new version too, so restoring is itself undoable.

## Implementation

- `app/project.py::Chapter.history: List[str]` holds previous `content` snapshots, oldest first, capped at `Project.history_limit` (default `MAX_CHAPTER_HISTORY` = 20), with a parallel `history_meta` list (`source`, `at`) saved as `{"text","source","at"}` in format v2 — `push_history()` appends the current content (no-op if it's empty; nothing meaningful to preserve) and trims from the front once over the cap. Persisted with the rest of the chapter; an old project file with no `"history"` key loads as `[]`.
- Every overwrite goes through `ChapterPanel.push_history(source)` / `Project.push_chapter_history()`, with `source` one of `generate`, `continue`, `retry`, `refine: <instruction>`, `rewrite`, `replace`, `reduce` or `restore` (shown with Spanish labels from `app/strings_es.py::HISTORY_SOURCE_LABELS`).
- `app/ui_chapter_editor.py::VersionHistoryDialog` (a `CTkToplevel`) lists `chapter.history` newest-first in a dropdown with each version's source, timestamp and word count, a read-only preview box kept in sync via the dropdown's `command` callback, "Comparar con la actual" (a diff against the current text) and a restore button. `_selected_history_index()` maps the newest-first display order back to `history`'s real (oldest-first) list index.

## Known limits

- **Bounded to `history_limit` versions per chapter (default 20), silently dropping the oldest past that.** No warning when a version falls off the end, and the limit has no UI (only the project file's `history_limit`, 1-100).
- **Manual typing isn't versioned** — nothing calls `push_history()` when the user types over `content_box` by hand; the text box's own Ctrl+Z covers those edits.
- Entries saved before the P2 round (format v1) have no source or timestamp.
