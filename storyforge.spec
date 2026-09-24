# -*- mode: python ; coding: utf-8 -*-
# Especificacion de PyInstaller para StoryForge Local.
# Uso (en Windows, con las dependencias ya instaladas):
#   pyinstaller --noconfirm --clean storyforge.spec
# El resultado queda en dist/StoryForge/StoryForge.exe

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = []
binaries = []
hiddenimports = []

for pkg in ("customtkinter", "llama_cpp", "docx"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports


def _is_import_lib(path):
    # llama_cpp/lib trae las import libraries de MSVC (llama.lib ~20 MB,
    # ggml*.lib, mtmd.lib) junto a las DLLs: solo sirven para enlazar C/C++
    # contra ellas, nunca se cargan en tiempo de ejecucion.
    return path.lower().endswith(".lib")


datas = [d for d in datas if not _is_import_lib(d[0])]
binaries = [b for b in binaries if not _is_import_lib(b[0])]

# A CUDA-enabled llama-cpp-python wheel (README, "Rendimiento / GPU") ships
# ggml-cuda.dll but not the CUDA runtime DLLs it needs (cublas64_*/cublasLt64_*/
# cudart64_*) -- those come from the standalone nvidia-cuda-runtime/nvidia-cublas
# pip packages. In dev, app/engine.py::_ensure_cuda_dlls_discoverable() finds
# them under site-packages; in the frozen app there is no site-packages, so they
# are bundled into llama_cpp/lib instead, next to ggml-cuda.dll -- llama_cpp's
# own loader prepends that folder to PATH before loading, which is exactly what
# the winmode=0 DLL search needs. With a CPU-only llama-cpp-python build (or no
# nvidia packages installed) the glob finds nothing and this is a no-op.
# Both nvidia package layouts are searched: CUDA 13 nests the DLLs one level
# deeper (nvidia/cu13/bin/x86_64/*.dll), CUDA 12 puts them directly in
# nvidia/<pkg>/bin/*.dll -- same rule as app/engine.py::find_nvidia_dll_dirs()
# (duplicated here rather than imported, so building never imports app/).
import glob
import os
import site

_CUDA_RUNTIME_DLLS = ("cublas64_", "cublasLt64_", "cudart64_")
_LLAMA_LIB_DIR = os.path.join("llama_cpp", "lib")
_bundled_cuda_dll_names = set()
for _site_packages in site.getsitepackages():
    for _pattern in (("nvidia", "*", "bin", "*.dll"), ("nvidia", "*", "bin", "*", "*.dll")):
        for _dll in sorted(glob.glob(os.path.join(_site_packages, *_pattern))):
            _name = os.path.basename(_dll)
            if _name.startswith(_CUDA_RUNTIME_DLLS) and _name.lower() not in _bundled_cuda_dll_names:
                _bundled_cuda_dll_names.add(_name.lower())
                binaries.append((_dll, _LLAMA_LIB_DIR))

# collect_all("llama_cpp") sweeps in the whole package regardless of what
# this app actually imports (app/engine.py only ever does
# `from llama_cpp import Llama`). In an environment where llama_cpp's
# optional `server` extra (an HTTP server on FastAPI/uvicorn) happens to be
# installed, that pulls in uvicorn/fastapi/starlette/websockets/anyio, and
# separately matplotlib gets pulled in with a full PySide6/Qt backend --
# none of which this app uses. Separately, nltk's own PyInstaller hook
# proactively includes optional integrations this app never exercises
# (app/repetition.py only ever uses nltk's stopwords/wordnet corpora): a
# pandas/pyarrow-based huggingface `datasets` integration, and scipy (a
# dependency of some of nltk's classifiers/metrics, not its corpus readers).
# A build before these excludes took several extra minutes analyzing Qt
# alone and produced a dist/ folder around 4x the expected size (425 MB vs
# ~110 MB after adding matplotlib/Qt/server excludes, confirmed further
# dominated by pyarrow/scipy/pandas at ~160 MB combined -- see
# docs/workflows/desktop-build/workflow.md). Excluding all of this here is
# safe: `grep`-confirmed that no file under app/ imports any of them, so
# nothing excluded here can be reached at runtime.
EXCLUDED_UNUSED_HEAVY_DEPS = [
    "llama_cpp.server",
    "matplotlib",
    "PySide6",
    "shiboken6",
    "uvicorn",
    "fastapi",
    "starlette",
    "websockets",
    "anyio",
    "sse_starlette",
    "pandas",
    "pyarrow",
    "scipy",
    # Also installed in the shared build interpreter (for other projects) and dragged in
    # transitively by optional integrations, but never imported by app/ -- llama.cpp runs GGUF
    # models with its own tokenizer, no torch/transformers involved. Without these excludes a CPU
    # torch (~1 GB) plus sympy ends up bundled for nothing.
    "torch",
    "torchvision",
    "sympy",
    "transformers",
    "diffusers",
]

a = Analysis(
    ["storyforge.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_UNUSED_HEAVY_DEPS,
    noarchive=False,
    cipher=block_cipher,
)

# PyInstaller's own binary-dependency analysis ALSO collects cublas64_*/
# cublasLt64_* (ggml-cuda.dll links against them, and it resolves them from
# the nvidia/ folders the loop above just pulled from), placing them at their
# original relative path, _internal/nvidia/cu13/bin/x86_64/ -- a second
# ~550 MB copy of cuBLAS next to the one in llama_cpp/lib. Only the
# llama_cpp/lib copy is ever loaded: llama_cpp's loader prepends llama_cpp/lib
# to PATH before its winmode=0 (legacy search order) ctypes.CDLL call, and in
# the frozen app nothing puts _internal/nvidia/... on PATH (engine.py's
# _ensure_cuda_dlls_discoverable() only scans sys.path entries ending in
# "site-packages", which a frozen app has none of). So the nvidia/ copies are
# dropped here -- but only those whose file name is also bundled in
# llama_cpp/lib, so nothing that exists only under nvidia/ goes missing.
def _toc_dest(entry):
    return entry[0].replace("\\", "/")


a.binaries = [
    b for b in a.binaries
    if not (
        _toc_dest(b).startswith("nvidia/")
        and os.path.basename(_toc_dest(b)).lower() in _bundled_cuda_dll_names
    )
    and not _is_import_lib(_toc_dest(b))
]
a.datas = [d for d in a.datas if not _is_import_lib(_toc_dest(d))]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StoryForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StoryForge",
)
