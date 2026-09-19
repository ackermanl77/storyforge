# Windows Desktop Build

## Goal

Package the app as a standalone Windows `.exe` that a user without Python installed can run, given a `.gguf` model dropped into `models/`.

## Steps

```powershell
build.bat
```

This installs dependencies with `pip`, runs `pyinstaller --noconfirm --clean storyforge.spec` (which produces `dist\StoryForge\`), then mirrors that into `StoryForge-App\` — a fixed, easy-to-find location that isn't wiped by `--clean` on the next build the way `dist\` is. The result to actually run is `StoryForge-App\StoryForge.exe`. Copy `models\` (with your `.gguf` file inside) next to it, inside `StoryForge-App\`, if it isn't there already — model files are never bundled by the spec.

## Automated builds (CI)

`.github/workflows/build-exe.yml` runs this same build automatically on every push to `main`/`test-story` (and on demand via the Actions tab's "Run workflow" button): checks out the repo on a `windows-latest` runner, installs dependencies (Python 3.12, pinned so `llama-cpp-python` installs from a prebuilt wheel instead of compiling from source on every run), runs `python -m unittest discover -s tests -v` (the build fails fast here if the test suite doesn't pass), then runs the same `pyinstaller --noconfirm --clean storyforge.spec` and uploads `dist/StoryForge/` as a build artifact named `StoryForge-<commit-sha>`. Download it from the workflow run's page under "Artifacts". This exists so the `.exe` never has to be rebuilt by hand just to pick up the latest commit — push, then download the artifact once the run finishes (a few minutes).

It does **not** publish a GitHub Release or otherwise version the `.exe` — every push produces a new, separately-downloadable artifact (subject to the repo's normal artifact retention period), not a persistent "latest" download link. A CI runner also never has NLTK data pre-cached, so a CI-built `.exe` always needs one-time internet access the first time "Reducir repeticion" is used — the incidental full-offline bundling described under "Implementation" below only happens on a local build done on a machine that already has `nltk_data` cached.

## Implementation

- `storyforge.py` is the PyInstaller entry script (`from app.main import main`).
- `build.bat`'s copy step (`if exist StoryForge-App rmdir /s /q StoryForge-App` then `xcopy /e /i /y dist\StoryForge StoryForge-App`) exists purely for discoverability: a first-time user (or anyone re-running `build.bat`) has to go look in PyInstaller's own working directory otherwise, which many people wouldn't think to check, and which `--clean` empties before every build anyway. `StoryForge-App\` is gitignored, just like `dist\`/`build\` — it's still build output, not a second copy meant to be committed.
- `storyforge.spec` calls `collect_all()` for `customtkinter`, `llama_cpp`, and `docx` — each of these ships non-Python data/binaries (compiled `llama.cpp` bindings, CustomTkinter's theme JSON, etc.) that plain `Analysis()` wouldn't pick up on its own.
- `storyforge.spec`'s `Analysis()` also passes an explicit `excludes` list (`EXCLUDED_UNUSED_HEAVY_DEPS`): `llama_cpp.server` and its transitive `uvicorn`/`fastapi`/`starlette`/`websockets`/`anyio`/`sse_starlette`, plus `matplotlib`/`PySide6`/`shiboken6`, plus `pandas`/`pyarrow`/`scipy`. `collect_all("llama_cpp")` sweeps in the whole package regardless of what's actually imported (this app only ever does `from llama_cpp import Llama`), and `nltk`'s own PyInstaller hook proactively includes optional integrations this app never exercises (`app/repetition.py` only uses `nltk`'s stopwords/wordnet corpora) — without the excludes, PyInstaller's Analysis follows both into a much larger dependency tree than this app needs. Verified none of `app/`'s own code imports anything in that list (`grep` across `app/`) before excluding it, and reverified the built `.exe` still launches and runs correctly afterward. Effect measured on one build: 425 MB → 137 MB `dist/StoryForge/` (~3.1x smaller), and several fewer minutes of Analysis time (no more walking the full Qt binding tree). The remaining 137 MB is dominated by `llama_cpp` (31 MB, the real compiled bindings), `numpy.libs` (21 MB), and `PIL` (13 MB) — things this app genuinely needs.
- Must be run **on Windows** — there is no cross-compilation path to produce a Windows `.exe` from another OS.

## Known limits

- NLTK's `stopwords`/`wordnet` data is bundled only incidentally: if the build machine already has it cached in a standard NLTK search path (e.g. `%APPDATA%\nltk_data`), PyInstaller's `nltk` hook picks it up automatically (`_internal/nltk_data/` in the build measured above, +11 MB) and that `.exe` works offline for "Reducir repeticion" right away. A build on a machine with no cached NLTK data won't have it bundled, and needs one-time internet access the first time that feature is used (see `docs/workflows/repetition-reduction/workflow.md`) — there's no explicit step in this spec/`build.bat` to guarantee one behavior or the other; to reliably ship a fully-offline build, manually populate `nltk_data/` at the project root before building.
- CI (see "Automated builds" above) rebuilds and test-gates the `.exe` on every push, but doesn't re-verify the exclusion list's savings or launch the built `.exe` to confirm it actually runs — the 137 MB figure and the "still launches correctly" check under "Implementation" are from one manual build/run, not something CI re-checks itself.
