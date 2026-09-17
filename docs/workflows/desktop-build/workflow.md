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
- Must be run **on Windows** — there is no cross-compilation path to produce a Windows `.exe` from another OS.

## Known limits

- **`collect_all("llama_cpp")` can pull in a much heavier dependency tree than this app needs, not yet fixed.** This app only ever imports `from llama_cpp import Llama` (`app/engine.py`) — it never touches `llama_cpp`'s optional `server` submodule (an HTTP server built on `uvicorn`/`fastapi`). But `collect_all()` sweeps in the whole package regardless of what's actually imported, and if that submodule's extras happen to be installed in the environment doing the build, PyInstaller's dependency analysis follows them into `uvicorn`/`fastapi`/`websockets`/`anyio`, and separately discovers `matplotlib` with a full `PySide6`/Qt backend plus `scipy`/`pandas`/`pyarrow` — none of which this app uses either. A build under those conditions took several minutes just analyzing Qt and produced a 425 MB `dist/StoryForge/` (confirmed to still launch and run correctly — this is bloat, not a correctness bug). The fix would be adding `excludes=["llama_cpp.server", "matplotlib", "uvicorn", "fastapi", "websockets", "anyio", "scipy", "pandas", "pyarrow", "PySide6"]` (or similar) to `storyforge.spec`'s `Analysis()` call and rebuilding to confirm the app still runs without them.
- NLTK's `stopwords`/`wordnet` data is not bundled either; a packaged build still needs one-time internet access the first time "Reducir repeticion"/"Reporte de repeticion" is used, unless you manually pre-populate `nltk_data/` next to the `.exe` before distributing it (see `docs/workflows/repetition-reduction/workflow.md`).
- No CI or automated step rebuilds/verifies the `.exe` — `build.bat` is run manually, and its output isn't part of this repository (see `.gitignore`).
