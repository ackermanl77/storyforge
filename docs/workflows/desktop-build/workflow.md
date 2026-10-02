# Windows Desktop Build

## Goal

Package the app as a standalone Windows `.exe` that a user without Python installed can run, given a `.gguf` model dropped into `models/`.

## Steps

```powershell
build.bat
```

This installs dependencies with `pip`, runs `pyinstaller --noconfirm --clean storyforge.spec` (which produces `dist\StoryForge\`), then mirrors that into `StoryForge-App\` — a fixed, easy-to-find location that isn't wiped by `--clean` on the next build the way `dist\` is. The result to actually run is `StoryForge-App\StoryForge.exe`. `build.bat` creates `StoryForge-App\models\` (with `README.txt`) and keeps it, and any `.gguf` in it, across rebuilds — model files are never bundled by the spec.

## Automated builds (CI)

`.github/workflows/build-exe.yml` runs on every push to `master`/`test-story` (and via "Run workflow") as a two-entry matrix on `windows-latest` / Python 3.12: it installs the exact versions in `requirements-build.txt`, then `llama-cpp-python==0.3.35` with `--only-binary=:all:` from abetlen's prebuilt wheel index (`whl/cpu` for the `cpu` variant; `whl/cu130` plus `requirements-cuda.txt`'s pinned `nvidia-cuda-runtime`/`nvidia-cublas` for `cuda13`), runs `python -m pytest -q`, runs the same `pyinstaller --noconfirm --clean storyforge.spec`, and uploads `dist/StoryForge/` as `StoryForge-<variant>-<commit-sha>`. Previously CI installed the unpinned `requirements.txt`; PyPI only has an sdist for llama-cpp-python, so every cache miss compiled a CPU-only build and the CI artifact had no GPU support. Both indexes were checked to carry 0.3.35 `win_amd64` wheels on 2026-09-30; bump `LLAMA_CPP_VERSION` and the pins together.

It does **not** publish a GitHub Release or otherwise version the `.exe` — every push produces a new, separately-downloadable artifact (subject to the repo's normal artifact retention period), not a persistent "latest" download link. A CI runner also never has NLTK data pre-cached, so a CI-built `.exe` always needs one-time internet access the first time "Reducir repeticion" is used — the incidental full-offline bundling described under "Implementation" below only happens on a local build done on a machine that already has `nltk_data` cached.

## Implementation

- **Clean build environment (K1).** `build.bat [cpu|cuda13]` deletes and recreates `.build-venv` with `py -%STORYFORGE_PYVER%` (default 3.14, the PC's Python; CI uses 3.12), installs `requirements-build.txt` (exact pins), llama-cpp-python 0.3.35 from abetlen's prebuilt wheel index with `--only-binary`, and for cuda13 `requirements-cuda.txt`; then downloads NLTK data, runs `pytest`, and runs PyInstaller from that venv. Nothing from the shared interpreter (IPython, jedi, datasets, torch...) can reach the bundle; the spec's `excludes` list stays as a safety net. `.build-venv/` is gitignored.
- **Version (K3).** `app/__init__.py::__version__` is the single source. `storyforge.spec` reads it with a regex (never importing `app/`), writes `build/version_info.txt` and passes `version=` to `EXE`, so Windows shows file/product version. The title bar and Ayuda > Acerca de show it too. CI zips each variant as `StoryForge-<version>-<cpu|cuda13>.zip` (with `models/README.txt`), and a pushed tag `v<version>` (checked against `__version__`) publishes both zips as a GitHub Release. No icon asset exists yet.

- `storyforge.py` is the PyInstaller entry script (`from app.main import main`).
- `build.bat`'s copy step (deletes everything in `StoryForge-App\` except `StoryForge-App\models\`, then `xcopy /e /i /y dist\StoryForge StoryForge-App`, adds `models\README.txt`, and removes `dist\`/`build\`) exists purely for discoverability: a first-time user (or anyone re-running `build.bat`) has to go look in PyInstaller's own working directory otherwise, which many people wouldn't think to check, and which `--clean` empties before every build anyway. `StoryForge-App\` is gitignored, just like `dist\`/`build\` — it's still build output, not a second copy meant to be committed.
- `storyforge.spec` calls `collect_all()` for `customtkinter`, `llama_cpp`, and `docx` — each of these ships non-Python data/binaries (compiled `llama.cpp` bindings, CustomTkinter's theme JSON, etc.) that plain `Analysis()` wouldn't pick up on its own.
- `storyforge.spec`'s `Analysis()` also passes an explicit `excludes` list (`EXCLUDED_UNUSED_HEAVY_DEPS`): `llama_cpp.server` and its transitive `uvicorn`/`fastapi`/`starlette`/`websockets`/`anyio`/`sse_starlette`, plus `matplotlib`/`PySide6`/`shiboken6`, plus `pandas`/`pyarrow`/`scipy`. `collect_all("llama_cpp")` sweeps in the whole package regardless of what's actually imported (this app only ever does `from llama_cpp import Llama`), and `nltk`'s own PyInstaller hook proactively includes optional integrations this app never exercises (`app/repetition.py` only uses `nltk`'s stopwords/wordnet corpora) — without the excludes, PyInstaller's Analysis follows both into a much larger dependency tree than this app needs. Verified none of `app/`'s own code imports anything in that list (`grep` across `app/`) before excluding it, and reverified the built `.exe` still launches and runs correctly afterward. Effect measured on one (pre-`.build-venv`) build: 425 MB → 137 MB `dist/StoryForge/`; a clean `build.bat` on 2026-10-01 gave 116 MB (`cpu`) and 756 MB (`cuda13`, ~640 MB of it cuBLAS/cuBLASLt/ggml-cuda), both launched fine and report version 0.4.0 (~3.1x smaller), and several fewer minutes of Analysis time (no more walking the full Qt binding tree). The remaining 137 MB is dominated by `llama_cpp` (31 MB, the real compiled bindings), `numpy.libs` (21 MB), and `PIL` (13 MB) — things this app genuinely needs.
- Must be run **on Windows** — there is no cross-compilation path to produce a Windows `.exe` from another OS.

## Known limits

- NLTK data is now explicit: `build.bat` and CI run `python -m nltk.downloader -d nltk_data stopwords wordnet` and `storyforge.spec` bundles `nltk_data/` when present, so every build works offline for "Reducir repetición".
- CI (see "Automated builds" above) rebuilds and test-gates the `.exe` on every push, but doesn't re-verify the exclusion list's savings or launch the built `.exe` to confirm it actually runs — the 137 MB figure and the "still launches correctly" check under "Implementation" are from one manual build/run, not something CI re-checks itself.
