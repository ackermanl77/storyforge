# Chapter Version History

## Goal

Let a destructive edit to a chapter's content (regenerate, refine, reduce repetition) be undone by keeping a bounded history of previous versions, instead of the only safety net being a confirmation dialog before the loss happens — inspired by a competing tool that keeps generation history for exactly this reason.

## Steps

1. Any of "Generar" (when the chapter already has content), "Aplicar refinamiento", or "Reducir repeticion" saves the chapter's current content as a version before replacing it.
2. Click "Versiones anteriores (N)" on a chapter panel (the count updates automatically) — clicking it with zero versions just shows an info message instead of opening anything.
3. Pick a version from the dropdown (most recent first) to preview it in the read-only box below.
4. "Restaurar esta version" replaces the chapter's current content with the selected version — and, symmetrically, saves what was there *before* restoring as a new version too, so restoring is itself undoable.

## Implementation

- `app/project.py::Chapter.history: List[str]` holds previous `content` snapshots, oldest first, capped at `MAX_CHAPTER_HISTORY` (5) — `push_history()` appends the current content (no-op if it's empty; nothing meaningful to preserve) and trims from the front once over the cap. Persisted with the rest of the chapter; an old project file with no `"history"` key loads as `[]`.
- Three call sites push history right before overwriting content: `ChapterPanel._on_generate()` (only when there's existing content to confirm-overwrite in the first place), `_on_refine()`, and `_on_reduce()` (word-repetition reduction — previously documented as an irreversible action with no undo at all; this closes that gap as a side effect).
- `app/gui.py::VersionHistoryDialog` (a `CTkToplevel`) lists `chapter.history` newest-first in a dropdown (`Version N of len(history) (word count)`), with a read-only preview box kept in sync via the dropdown's `command` callback, and a restore button. `_selected_history_index()` maps the newest-first display order back to `history`'s real (oldest-first) list index.

## Known limits

- **Bounded to 5 versions per chapter, silently dropping the oldest past that.** No warning when a version falls off the end — a 6th regenerate/refine/reduce after 5 already-saved versions permanently loses whichever was oldest, with no indication in the UI that this happened.
- **Not wired into every destructive action** — restoring a version through this dialog does push the pre-restore content, but nothing calls `push_history()` when the user manually types over `content_box` by hand; only the three specific buttons above trigger it. Free-hand edits you make yourself aren't protected by this mechanism.
- History entries are plain strings — no timestamp, no label for *why* that version exists (regenerate vs. refine vs. reduce-repetition), just a word count. Distinguishing them relies entirely on reading the preview.
