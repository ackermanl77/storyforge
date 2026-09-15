# Export Workflow

## Goal

Turn a `Project`'s chapters into a shareable file: a formatted Word document or plain text.

## Steps

1. From the **Archivo** menu, choose "Exportar a Word (.docx)" or "Exportar a TXT".
2. Pick a destination path in the file dialog.
3. The app syncs every tab's current UI state into the `Project` (`_sync_all()`) before writing, so unsaved edits are included even if you haven't used "Guardar proyecto" yet.

## Implementation

- `app/export.py::export_txt()` writes a plain heading + `Chapter N: <title>` + content per chapter, with `*asterisk*`-wrapped internal-thought markers left as literal asterisks in the text.
- `app/export.py::export_docx()` uses `python-docx`: one `Heading 1` per chapter, and `_add_runs_with_italics()` splits each paragraph (chapters are split on blank lines) on the same `*...*` marker to emit real italic `Run`s in the `.docx` instead of literal asterisks — this is the one place in the app where the `STYLE_GUIDE`'s "*asterisks* for internal thoughts" convention (`app/prompts.py`) becomes actual formatting rather than just markup in a text file.

## Known limits

- Only the `*italic*` convention is converted to real formatting; dialogue quotes and any other `STYLE_GUIDE` convention stay as plain characters in both export formats.
- `export_docx()` requires `python-docx` to be installed (it's in `requirements.txt`); if it's missing, the app surfaces a clear `RuntimeError` message rather than crashing, but the export itself fails.
