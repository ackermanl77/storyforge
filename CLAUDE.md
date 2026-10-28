# CLAUDE.md

Guidance for Claude Code in this repository. User guide: [GUIA_DE_USUARIO.md](GUIA_DE_USUARIO.md);
install, performance and limits: [README.md](README.md); architecture, entry points and fix history:
[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) and [docs/workflows/](docs/workflows/README.md).
All of them are in Spanish.

## What this is

A CustomTkinter desktop app that writes long English fiction with a local GGUF model
(`llama-cpp-python`) or an OpenAI-compatible server (`app/server_backend.py`). `storyforge.py` /
`app/main.py` start it; `--servidor` serves the phone page and the story generator
(`app/web_server.py`, `app/web/`); `--self-test` checks a build (`app/selftest.py`).

## Commands

```powershell
python storyforge.py
python -m pytest -q                                   # needs requirements-dev.txt
ruff check app tests                                  # ruff.toml: E9 + pyflakes only
.\scripts\run_coverage.ps1
build.bat                                             # PyInstaller build, copied to StoryForge-App\
```

CI: `.github/workflows/build-exe.yml` (ruff, tests with coverage, CPU and CUDA 13 zips; a `v*` tag
equal to `app/__init__.py`'s version publishes a release with installers).

## Rules

- **Every user-visible string lives in `app/strings_es.py`.** The UI is Spanish; generated story
  text is English.
- **The engine is split by concern**: `engine.py` re-exports `engine_types.py` and mixes in
  `engine_model.py` (load/connect) and `completion.py` (tokens, context, retries). Tests patch names
  on `engine`, so keep the re-exports.
- Model work runs through `app/task_runner.py` (busy state, Stop, errors), never on the Tk thread.
- Projects are saved atomically (`app/fileutil.py`) in the versioned format of `app/project.py`;
  change the format only with a migration.
- Tests use a temp data folder (`STORYFORGE_USER_DATA_DIR`, set in `tests/conftest.py`). Prompt
  snapshots live in `tests/snapshots/` (`STORYFORGE_UPDATE_SNAPSHOTS=1` after an intended prompt
  change). `tests/test_real_model.py` runs only with `STORYFORGE_TEST_MODEL` set.
- `pytest.ini` limits collection to `tests/` because `StoryForge-App\_internal\` holds a build.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost), then `graphify export wiki` -- the git hooks rebuild graph.json after each commit/checkout but never the wiki.
- graphify-out/ is gitignored: every clone builds its own graph (`/graphify`), and the git hooks (`graphify hook install`) keep it current. Do not commit it or suggest skipping the rebuild or its hooks.
- Community names live in graphify-out/.graphify_labels.json (curated); a community a rebuild creates or reshapes gets a hub-name fallback in `.graphify_labels.pending.json` (e.g. a bare file or test name). When the report shows such names, rename them there (2-5 plain words) and run `graphify cluster-only .`.
