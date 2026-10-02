"""
Lectura de la cabecera de archivos GGUF (sin cargar el modelo), agrupacion
de modelos partidos en varios archivos, estimacion de VRAM y mensajes de
error de carga en espanol.

- Un modelo grande puede venir partido: "modelo-00001-of-00002.gguf",
  "modelo-00002-of-00002.gguf". Solo la PRIMERA parte se carga (llama.cpp
  encuentra las demas); antes la lista de modelos mostraba cada parte por
  separado, incluso una segunda parte huerfana sin la primera, que fallaba
  al cargar con un error generico de llama.cpp.
- La cabecera dice el contexto con el que se entreno el modelo, su
  arquitectura, cuantizacion y si trae plantilla de chat: con eso se sugiere
  un n_ctx razonable y se avisa si se pide mas contexto del entrenado.
- Con el tamano de los pesos y la forma de la cache KV se estima cuanta VRAM
  hace falta y cuantas capas conviene poner en la GPU.

El lector es Python puro (struct): no necesita llama-cpp-python ni carga
pesos. Los arreglos grandes (el vocabulario, ~128k cadenas) se saltean.
"""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, List, Optional, Tuple

GGUF_MAGIC = b"GGUF"

# Tipos de valor de GGUF (ver la especificacion de ggml).
_UINT8, _INT8, _UINT16, _INT16, _UINT32, _INT32, _FLOAT32, _BOOL, _STRING, _ARRAY, _UINT64, _INT64, _FLOAT64 = range(13)
_SCALAR_FORMATS = {
    _UINT8: "<B", _INT8: "<b", _UINT16: "<H", _INT16: "<h", _UINT32: "<I", _INT32: "<i",
    _FLOAT32: "<f", _BOOL: "<?", _UINT64: "<Q", _INT64: "<q", _FLOAT64: "<d",
}

# general.file_type -> nombre de la cuantizacion (enum llama_ftype).
FILE_TYPE_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
    10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M",
    16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S",
    22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M",
    28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16",
}

_SHARD_RE = re.compile(r"^(?P<base>.+)-(?P<no>\d{5})-of-(?P<total>\d{5})\.gguf$", re.IGNORECASE)


class GGUFError(ValueError):
    """El archivo no es un GGUF valido (o esta truncado)."""


# ---------------------------------------------------------------- lectura
def _read_exact(f: BinaryIO, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise GGUFError("El archivo GGUF esta truncado (termino antes de lo esperado).")
    return data


def _read_scalar(f: BinaryIO, value_type: int):
    fmt = _SCALAR_FORMATS[value_type]
    return struct.unpack(fmt, _read_exact(f, struct.calcsize(fmt)))[0]


def _read_string(f: BinaryIO) -> str:
    (length,) = struct.unpack("<Q", _read_exact(f, 8))
    if length > 64 * 1024 * 1024:
        raise GGUFError("Cadena GGUF de tamaño inválido.")
    return _read_exact(f, length).decode("utf-8", errors="replace")


def _skip_string(f: BinaryIO) -> None:
    (length,) = struct.unpack("<Q", _read_exact(f, 8))
    f.seek(length, os.SEEK_CUR)


def _read_value(f: BinaryIO, value_type: int, keep_array_items: int):
    if value_type == _STRING:
        return _read_string(f)
    if value_type in _SCALAR_FORMATS:
        return _read_scalar(f, value_type)
    if value_type == _ARRAY:
        (item_type,) = struct.unpack("<I", _read_exact(f, 4))
        (count,) = struct.unpack("<Q", _read_exact(f, 8))
        if count <= keep_array_items:
            return [_read_value(f, item_type, keep_array_items) for _ in range(count)]
        # Arreglo grande (vocabulario, merges...): se saltea y solo se
        # recuerda su longitud.
        if item_type in _SCALAR_FORMATS:
            f.seek(count * struct.calcsize(_SCALAR_FORMATS[item_type]), os.SEEK_CUR)
        elif item_type == _STRING:
            for _ in range(count):
                _skip_string(f)
        else:
            for _ in range(count):
                _read_value(f, item_type, 0)
        return {"array_length": count}
    raise GGUFError(f"Tipo de valor GGUF desconocido: {value_type}")


def read_gguf_metadata(path: str, keep_array_items: int = 16) -> Dict[str, object]:
    """Pares clave/valor de la cabecera de un GGUF. Lanza GGUFError si no lo es."""
    with open(path, "rb") as f:
        if f.read(4) != GGUF_MAGIC:
            raise GGUFError("El archivo no es un modelo GGUF (firma invalida).")
        (version,) = struct.unpack("<I", _read_exact(f, 4))
        if version == 1:
            _tensors, kv_count = struct.unpack("<II", _read_exact(f, 8))
        else:
            _tensors, kv_count = struct.unpack("<QQ", _read_exact(f, 16))
        if kv_count > 100_000:
            raise GGUFError("Cabecera GGUF invalida.")
        metadata: Dict[str, object] = {"gguf.version": version}
        for _ in range(kv_count):
            key = _read_string(f)
            (value_type,) = struct.unpack("<I", _read_exact(f, 4))
            metadata[key] = _read_value(f, value_type, keep_array_items)
        return metadata


# ---------------------------------------------------------------- modelos partidos
def shard_parts(path: str) -> Optional[Tuple[str, int, int]]:
    """(base, numero de parte, total) si el nombre es "x-0000k-of-0000n.gguf"."""
    match = _SHARD_RE.match(os.path.basename(path))
    if not match:
        return None
    return match.group("base"), int(match.group("no")), int(match.group("total"))


def shard_path(first_or_any: str, part: int, total: int) -> str:
    info = shard_parts(first_or_any)
    if info is None:
        return first_or_any
    base, _no, _total = info
    return os.path.join(os.path.dirname(first_or_any), f"{base}-{part:05d}-of-{total:05d}.gguf")


def missing_shards(path: str) -> List[int]:
    """Numeros de parte que faltan en la carpeta para el modelo de `path`
    (vacio si no es un modelo partido, o si estan todas)."""
    info = shard_parts(path)
    if info is None:
        return []
    _base, _no, total = info
    return [i for i in range(1, total + 1) if not os.path.isfile(shard_path(path, i, total))]


@dataclass
class ModelEntry:
    """Un modelo en la lista de la pestana Modelo (una entrada por modelo,
    no por archivo)."""
    path: str  # la primera parte si es un modelo partido
    label: str
    parts_total: int = 1
    missing_parts: List[int] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing_parts


def list_model_entries(models_dir: str) -> List[ModelEntry]:
    if not os.path.isdir(models_dir):
        return []
    entries: List[ModelEntry] = []
    groups: Dict[Tuple[str, int], List[int]] = {}
    for name in sorted(os.listdir(models_dir)):
        if not name.lower().endswith(".gguf"):
            continue
        full = os.path.join(models_dir, name)
        if not os.path.isfile(full):
            continue
        info = shard_parts(full)
        if info is None:
            entries.append(ModelEntry(path=full, label=name))
            continue
        base, no, total = info
        groups.setdefault((base, total), []).append(no)
    for (base, total), _present in sorted(groups.items()):
        first = os.path.join(models_dir, f"{base}-{1:05d}-of-{total:05d}.gguf")
        missing = missing_shards(first)
        name = os.path.basename(first)
        if missing:
            label = f"{name} (incompleto: faltan {len(missing)} de {total} partes)"
        else:
            label = f"{name} ({total} partes)"
        entries.append(ModelEntry(path=first, label=label, parts_total=total, missing_parts=missing))
    entries.sort(key=lambda e: e.label.lower())
    return entries


def total_model_size(path: str) -> int:
    """Bytes de todas las partes presentes del modelo."""
    info = shard_parts(path)
    if info is None:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    _base, _no, total = info
    size = 0
    for i in range(1, total + 1):
        part = shard_path(path, i, total)
        if os.path.isfile(part):
            size += os.path.getsize(part)
    return size


# ---------------------------------------------------------------- informacion del modelo
@dataclass
class ModelInfo:
    path: str
    size_bytes: int = 0
    architecture: str = ""
    name: str = ""
    trained_context: Optional[int] = None
    n_layers: Optional[int] = None
    n_head: Optional[int] = None
    n_head_kv: Optional[int] = None
    head_dim: Optional[int] = None
    quantization: str = ""
    has_chat_template: bool = False
    parts_total: int = 1
    missing_parts: List[int] = field(default_factory=list)
    error: str = ""

    def summary_es(self) -> str:
        """Una linea para mostrar en la pestana Modelo."""
        if self.error:
            return self.error
        bits = []
        if self.architecture:
            bits.append(f"arquitectura {self.architecture}")
        if self.quantization:
            bits.append(self.quantization)
        bits.append(f"{self.size_bytes / 1024**3:.1f} GB")
        if self.trained_context:
            bits.append(f"contexto entrenado {self.trained_context:,}")
        if self.n_layers:
            bits.append(f"{self.n_layers} capas")
        bits.append("con plantilla de chat" if self.has_chat_template else "sin plantilla de chat")
        if self.parts_total > 1:
            bits.append(f"{self.parts_total} partes")
        text = ", ".join(bits)
        if self.missing_parts:
            text += f". FALTAN las partes {', '.join(map(str, self.missing_parts))}: no se puede cargar."
        return text


def _as_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list) and value and all(isinstance(v, int) for v in value):
        return max(value)  # p.ej. head_count_kv por capa
    return None


def model_info(path: str) -> ModelInfo:
    info = ModelInfo(path=path)
    info.missing_parts = missing_shards(path)
    parts = shard_parts(path)
    if parts:
        info.parts_total = parts[2]
    info.size_bytes = total_model_size(path)
    # La primera parte trae los metadatos completos; si falta, se intenta
    # con la que este.
    header_path = path
    if parts and not os.path.isfile(path):
        for i in range(1, parts[2] + 1):
            candidate = shard_path(path, i, parts[2])
            if os.path.isfile(candidate):
                header_path = candidate
                break
    try:
        meta = read_gguf_metadata(header_path)
    except (OSError, GGUFError, struct.error) as exc:
        info.error = f"No se pudo leer la cabecera del modelo: {exc}"
        return info
    arch = str(meta.get("general.architecture") or "")
    info.architecture = arch
    info.name = str(meta.get("general.name") or "")
    info.trained_context = _as_int(meta.get(f"{arch}.context_length"))
    info.n_layers = _as_int(meta.get(f"{arch}.block_count"))
    info.n_head = _as_int(meta.get(f"{arch}.attention.head_count"))
    info.n_head_kv = _as_int(meta.get(f"{arch}.attention.head_count_kv")) or info.n_head
    key_length = _as_int(meta.get(f"{arch}.attention.key_length"))
    embedding = _as_int(meta.get(f"{arch}.embedding_length"))
    if key_length:
        info.head_dim = key_length
    elif embedding and info.n_head:
        info.head_dim = embedding // info.n_head
    file_type = _as_int(meta.get("general.file_type"))
    info.quantization = FILE_TYPE_NAMES.get(file_type, "") if file_type is not None else ""
    info.has_chat_template = bool(meta.get("tokenizer.chat_template"))
    return info


# ---------------------------------------------------------------- VRAM
KV_CACHE_TYPES = ("f16", "q8_0", "q4_0")
# Bytes por elemento de la cache KV (q8_0: bloques de 32 valores en 34 bytes).
KV_BYTES_PER_ELEMENT = {"f16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}
# Buffers de computo, contexto CUDA, etc.: un colchon fijo aproximado.
GPU_OVERHEAD_BYTES = 700 * 1024**2


def estimate_kv_bytes(info: ModelInfo, n_ctx: int, kv_type: str = "f16") -> Optional[int]:
    if not (info.n_layers and info.n_head_kv and info.head_dim and n_ctx > 0):
        return None
    per_elem = KV_BYTES_PER_ELEMENT.get(kv_type, 2.0)
    return int(n_ctx * info.n_layers * info.n_head_kv * info.head_dim * 2 * per_elem)


@dataclass
class VramEstimate:
    weights_bytes: int
    kv_bytes: Optional[int]
    free_vram_bytes: Optional[int]
    total_ram_bytes: Optional[int]
    suggested_gpu_layers: Optional[int]
    fits_fully: Optional[bool]
    message: str


def _gb(value: Optional[int]) -> str:
    return "?" if value is None else f"{value / 1024**3:.1f} GB"


def estimate_vram(info: ModelInfo, n_ctx: int, kv_type: str = "f16",
                  free_vram_bytes: Optional[int] = None,
                  total_ram_bytes: Optional[int] = None) -> VramEstimate:
    """Cuanto ocupa el modelo y cuantas capas conviene poner en la GPU.
    Estimacion aproximada: pesos ~ tamano del archivo, cache KV segun la
    forma del modelo, mas un colchon fijo para buffers de computo."""
    weights = info.size_bytes
    kv = estimate_kv_bytes(info, n_ctx, kv_type)
    need = weights + (kv or 0) + GPU_OVERHEAD_BYTES
    suggested: Optional[int] = None
    fits: Optional[bool] = None
    parts = [f"Pesos {_gb(weights)}", f"cache KV {_gb(kv)} ({kv_type}, n_ctx={n_ctx:,})"]
    if free_vram_bytes is None:
        parts.append("VRAM libre desconocida (no se encontro nvidia-smi)")
        message = ", ".join(parts) + "."
    else:
        parts.append(f"VRAM libre {_gb(free_vram_bytes)}")
        if need <= free_vram_bytes:
            fits = True
            suggested = -1
            verdict = "cabe completo en GPU (n_gpu_layers = -1)"
        else:
            fits = False
            if info.n_layers:
                per_layer = (weights + (kv or 0)) / info.n_layers
                usable = free_vram_bytes - GPU_OVERHEAD_BYTES
                suggested = max(0, min(info.n_layers, int(usable // per_layer))) if per_layer > 0 else 0
                verdict = f"no cabe completo: ~{suggested} de {info.n_layers} capas en GPU"
            else:
                suggested = 0
                verdict = "no cabe completo en la GPU"
        message = ", ".join(parts) + f": {verdict}."
    if total_ram_bytes is not None and free_vram_bytes is not None and weights > total_ram_bytes + free_vram_bytes:
        message += (
            f" ATENCION: el modelo ({_gb(weights)}) es mas grande que la VRAM libre mas la RAM "
            f"total ({_gb(total_ram_bytes)}): va a ser extremadamente lento o no va a cargar."
        )
    elif fits is False:
        message += " Las capas que no entran corren en la CPU (mucho mas lento)."
    return VramEstimate(weights, kv, free_vram_bytes, total_ram_bytes, suggested, fits, message)


def query_free_vram_bytes(timeout: float = 5.0) -> Optional[int]:
    """VRAM libre de la primera GPU NVIDIA, via nvidia-smi. None si no hay
    GPU NVIDIA o nvidia-smi no esta disponible."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout, creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        first = out.stdout.strip().splitlines()[0]
        return int(float(first.strip())) * 1024**2
    except (IndexError, ValueError):
        return None


def query_total_ram_bytes() -> Optional[int]:
    if sys.platform == "win32":
        try:
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:  # noqa: BLE001
            return None
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


# ---------------------------------------------------------------- errores de carga
def friendly_load_error(exc: BaseException, path: str = "") -> str:
    """Traduce los fallos tipicos de llama.cpp al cargar un modelo a un
    mensaje en espanol con una pista de que hacer."""
    detail = str(exc) or exc.__class__.__name__
    low = detail.lower()
    if path and missing_shards(path):
        missing = ", ".join(map(str, missing_shards(path)))
        hint = (f"El modelo esta partido en varios archivos y faltan las partes {missing} "
                "en la carpeta. Descarga todas las partes y ponlas juntas.")
    elif any(s in low for s in ("out of memory", "cudamalloc", "failed to allocate", "alloc_buffer", "oom")):
        hint = ("No hay memoria suficiente (VRAM o RAM). Baja n_gpu_layers o el contexto (n_ctx), "
                "o usa la cache KV q8_0 con flash attention.")
    elif "architecture" in low:
        hint = ("Esta versión de llama-cpp-python no conoce la arquitectura de este modelo. "
                "Actualiza llama-cpp-python (o usa un modelo de una familia mas comun).")
    elif "split" in low:
        hint = "El modelo esta partido en varios archivos: carga la parte 00001 y ten todas las partes juntas."
    elif "failed to load model" in low or "gguf" in low or "magic" in low:
        hint = ("llama.cpp no pudo abrir el archivo. Puede estar incompleto o corrupto (vuelve a "
                "descargarlo), no ser un GGUF, o ser un archivo de OneDrive \"solo en linea\" "
                "que aun no se descargo (mejor guarda los modelos fuera de OneDrive).")
    else:
        hint = "No se pudo cargar el modelo."
    return f"{hint}\n\nDetalle: {detail}"
