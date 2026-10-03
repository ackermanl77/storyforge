# Feature Workflows

These guides document current application behavior: what each feature does, where it lives in the code (the GUI is `app/gui.py` plus one `app/ui_*.py` module per tab, with all UI text in `app/strings_es.py`), how to exercise it from the GUI, and its known limits. For architecture, entry points, release location, and the running list of fixes, the source of truth is [`docs/PROJECT_STATUS.md`](../PROJECT_STATUS.md).

## Story Generation

- [Outline-first beat sheet](outline/workflow.md)
- [Chapter generation](chapter-generation/workflow.md)
- [Writing style emphasis](writing-style/workflow.md)
- [Chapter purpose](chapter-purpose/workflow.md)
- [Plot / Characters / Setting: expand and import](field-assist/workflow.md)

## Editing Generated Content

- [Chapter refinement](chapter-refinement/workflow.md)
- [Chapter version history](version-history/workflow.md)

## Post-Processing and Output

- [Word-repetition reduction](repetition-reduction/workflow.md)
- [Export to Word / EPUB / Markdown / TXT](export/workflow.md)

Features without their own workflow page (the lorebook, find/replace, Author's Note, selection rewrite, sampling, chat format, status bar, Tab order) are described in `docs/PROJECT_STATUS.md` and, for users, in [`GUIA_DE_USUARIO.md`](../../GUIA_DE_USUARIO.md).

## Reliability and Release

- [Concurrency, exit confirmation, and autosave](reliability/workflow.md)
- [Windows desktop build](desktop-build/workflow.md)

## Project Status

See [docs/PROJECT_STATUS.md](../PROJECT_STATUS.md) for architecture, entry points, release location, verification, and known limitations.
