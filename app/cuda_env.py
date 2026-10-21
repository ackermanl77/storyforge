"""Las DLL de CUDA de las ruedas nvidia-* de pip, para el llama-cpp-python con CUDA (R6:
separado de engine.py, que reexporta estas funciones)."""

from __future__ import annotations

import glob
import os
import sys
from typing import List

_cuda_dlls_prepared = False


def _ensure_cuda_dlls_discoverable() -> None:
    """A CUDA-enabled llama-cpp-python wheel (see README's "Rendimiento / GPU"
    section) bundles ggml-cuda.dll, which needs the CUDA runtime DLLs
    (cudart64_*.dll/cublas64_*.dll/cublasLt64_*.dll) at import time -- not
    just when a model is actually offloaded to GPU. Those DLLs aren't bundled
    in the wheel itself; the standalone `nvidia-cuda-runtime`/`nvidia-cublas`
    pip packages provide them instead (no full CUDA Toolkit install needed).

    llama_cpp's own loader (_ctypes_extensions.py) calls
    `ctypes.CDLL(..., winmode=ctypes.RTLD_GLOBAL)` -- on Windows RTLD_GLOBAL
    is 0, and passing winmode=0 makes ctypes use the legacy DLL search order,
    which ignores directories registered via `os.add_dll_directory()` (that
    only applies under the "safe search mode" flags). The legacy search order
    does still consult PATH, so prepending the DLL directory there (in
    addition to add_dll_directory, for forward compatibility if that bug gets
    fixed upstream) is what actually makes the import succeed -- confirmed by
    reproducing llama_cpp's exact load call directly.

    A CPU-only environment (no `nvidia-*` packages installed, or the default
    PyPI CPU-only wheel) hits none of this: the glob below just finds nothing
    and the import proceeds exactly as it always did.

    Two package layouts exist: the CUDA 13 packages nest the DLLs one level
    deeper (nvidia/cu13/bin/x86_64/*.dll), while the CUDA 12 ones
    (nvidia-cublas-cu12 etc.) put them directly in nvidia/<pkg>/bin/*.dll --
    both are checked (see find_nvidia_dll_dirs()).
    """
    global _cuda_dlls_prepared
    if _cuda_dlls_prepared or sys.platform != "win32":
        return
    _cuda_dlls_prepared = True

    for site_packages in (p for p in sys.path if p.endswith("site-packages")):
        for dll_dir in find_nvidia_dll_dirs(site_packages):
            try:
                os.add_dll_directory(dll_dir)
            except OSError:
                pass
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")


def find_nvidia_dll_dirs(site_packages: str) -> List[str]:
    """Carpetas bajo site-packages/nvidia que contienen DLLs, en cualquiera de
    los dos layouts conocidos: nvidia/<pkg>/bin/*.dll (CUDA 12) o
    nvidia/<pkg>/bin/<arch>/*.dll (CUDA 13)."""
    found: List[str] = []
    patterns = (
        os.path.join(site_packages, "nvidia", "*", "bin"),
        os.path.join(site_packages, "nvidia", "*", "bin", "*"),
    )
    for pattern in patterns:
        for dll_dir in sorted(glob.glob(pattern)):
            if os.path.isdir(dll_dir) and glob.glob(os.path.join(dll_dir, "*.dll")):
                found.append(dll_dir)
    return found


def supports_gpu_offload() -> bool:
    """Whether the installed llama-cpp-python build can actually offload
    layers to a GPU -- used by the GUI to pick a sensible default for
    n_gpu_layers instead of always defaulting to CPU-only (0)."""
    _ensure_cuda_dlls_discoverable()
    try:
        from llama_cpp import llama_cpp as _llama_cpp_lib
    except Exception:
        # Not just ImportError: when a CUDA build's DLLs can't be resolved, llama_cpp raises
        # RuntimeError("Failed to load shared library ...") from its import. This runs while the
        # GUI is being built, so it must degrade to "no GPU" rather than crash the app at startup.
        return False
    try:
        return bool(_llama_cpp_lib.llama_supports_gpu_offload())
    except Exception:
        return False
