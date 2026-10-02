# Export Workflow

## Goal

Turn a `Project`'s chapters into a shareable file: Word (.docx), EPUB, Markdown or plain text.

## Steps

1. From the **Archivo** menu, choose "Exportar a Word (.docx)", "Exportar a EPUB", "Exportar a Markdown (.md)" or "Exportar a TXT". Title, author and the chapter heading style ("Chapter N: title", "Capítulo N: title", or title only) come from the Plot tab.
2. Pick a destination path in the file dialog.
3. The app syncs every tab's current UI state into the `Project` (`_sync_all()`) before writing, so unsaved edits are included even if you haven't used "Guardar proyecto" yet.

## Implementation

- `chapter_paragraphs()` cleans each chapter first: a model-written first line like "## Chapter 3: ..." is dropped and other markdown `#` headings lose their hashes; an italic span that crosses a paragraph break is closed and reopened in each paragraph.
- `parse_inline()` handles `**bold**` before `*italic*`; an asterisk only counts when there is no space on its inner side (`a * b and c * d` stays literal).
- `export_txt()` / `export_markdown()` write title, author and one heading per chapter (markup kept as text). `export_docx()` writes core properties, a title page, a page break before each chapter and real bold/italic runs. `export_epub()` builds an EPUB 3 zip by hand (stored `mimetype` first, `container.xml`, OPF, `nav.xhtml`, `toc.ncx`, one XHTML per chapter, CSS) with no extra dependency.
- All exports are atomic (`app/fileutil.py`, with `os.replace` retries for OneDrive/antivirus locks). Covered by `tests/test_export.py` (reads the .docx back with python-docx, parses every EPUB XML file).

## Known limits

- Only `*italic*` and `**bold**` become real formatting; dialogue quotes stay plain characters. The EPUB has no cover image and was validated structurally in tests, not with epubcheck or a real reader.
- `export_docx()` requires `python-docx` to be installed (it's in `requirements.txt`); if it's missing, the app surfaces a clear `RuntimeError` message rather than crashing, but the export itself fails.
