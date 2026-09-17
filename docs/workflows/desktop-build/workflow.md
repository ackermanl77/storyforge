# Windows Desktop Build

## Goal

Package the app as a standalone Windows `.exe` that a user without Python installed can run, given a `.gguf` model dropped into `models/`.

## Steps

```powershell
build.bat
```

This installs dependencies with `pip`, then runs `pyinstaller --noconfirm --clean storyforge.spec`. The result is `dist\StoryForge\StoryForge.exe`. Copy `models\` (with your `.gguf` file inside) next to the `.exe` if it isn't there already — model files are never bundled by the spec.

## Implementation

- `storyforge.py` is the PyInstaller entry script (`from app.main import main`).
- `storyforge.spec` calls `collect_all()` for `customtkinter`, `llama_cpp`, and `docx` — each of these ships non-Python data/binaries (compiled `llama.cpp` bindings, CustomTkinter's theme JSON, etc.) that plain `Analysis()` wouldn't pick up on its own.
- `storyforge.spec`'s `Analysis()` also passes an explicit `excludes` list (`EXCLUDED_UNUSED_HEAVY_DEPS`): `llama_cpp.server` and its transitive `uvicorn`/`fastapi`/`starlette`/`websockets`/`anyio`/`sse_starlette`, plus `matplotlib`/`PySide6`/`shiboken6`, plus `pandas`/`pyarrow`/`scipy`. `collect_all("llama_cpp")` sweeps in the whole package regardless of what's actually imported (this app only ever does `from llama_cpp import Llama`), and `nltk`'s own PyInstaller hook proactively includes optional integrations this app never exercises (`app/repetition.py` only uses `nltk`'s stopwords/wordnet corpora) — without the excludes, PyInstaller's Analysis follows both into a much larger dependency tree than this app needs. Verified none of `app/`'s own code imports anything in that list (`grep` across `app/`) before excluding it, and reverified the built `.exe` still launches and runs correctly afterward. Effect measured on one build: 425 MB → 137 MB `dist/StoryForge/` (~3.1x smaller), and several fewer minutes of Analysis time (no more walking the full Qt binding tree). The remaining 137 MB is dominated by `llama_cpp` (31 MB, the real compiled bindings), `numpy.libs` (21 MB), and `PIL` (13 MB) — things this app genuinely needs.
- Must be run **on Windows** — there is no cross-compilation path to produce a Windows `.exe` from another OS.

## Known limits

- NLTK's `stopwords`/`wordnet` data is bundled only incidentally: if the build machine already has it cached in a standard NLTK search path (e.g. `%APPDATA%\nltk_data`), PyInstaller's `nltk` hook picks it up automatically (`_internal/nltk_data/` in the build measured above, +11 MB) and that `.exe` works offline for "Reducir repeticion" right away. A build on a machine with no cached NLTK data won't have it bundled, and needs one-time internet access the first time that feature is used (see `docs/workflows/repetition-reduction/workflow.md`) — there's no explicit step in this spec/`build.bat` to guarantee one behavior or the other; to reliably ship a fully-offline build, manually populate `nltk_data/` at the project root before building.
- No CI or automated step rebuilds/verifies the `.exe` — `build.bat` is run manually, and its output isn't part of this repository (see `.gitignore`). The size/timing numbers above are from one manual build and aren't re-verified automatically as dependencies change.
