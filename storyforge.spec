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

# A CUDA-enabled llama-cpp-python wheel (README, "Rendimiento / GPU") ships
# ggml-cuda.dll but not the CUDA runtime DLLs it needs (cublas64_*/cublasLt64_*/
# cudart64_*) -- those come from the standalone nvidia-cuda-runtime/nvidia-cublas
# pip packages. In dev, app/engine.py::_ensure_cuda_dlls_discoverable() finds
# them under site-packages; in the frozen app there is no site-packages, so they
# are bundled into llama_cpp/lib instead, next to ggml-cuda.dll -- llama_cpp's
# own loader prepends that folder to PATH before loading, which is exactly what
# the winmode=0 DLL search needs. With a CPU-only llama-cpp-python build (or no
# nvidia packages installed) the glob finds nothing and this is a no-op.
import glob
import os
import site

_CUDA_RUNTIME_DLLS = ("cublas64_", "cublasLt64_", "cudart64_")
for _site_packages in site.getsitepackages():
    for _dll in glob.glob(os.path.join(_site_packages, "nvidia", "*", "bin", "*", "*.dll")):
        if os.path.basename(_dll).startswith(_CUDA_RUNTIME_DLLS):
            binaries.append((_dll, os.path.join("llama_cpp", "lib")))

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
