"""
Parametros de muestreo (sampling) por tarea.

Antes todas las llamadas al modelo (prosa, esquema, resumen, refinar,
expandir) usaban temperature=0.85, top_p=0.92, repeat_penalty=1.15 fijos y
una semilla aleatoria que no se podia ver ni repetir. Un repeat_penalty de
1.15 sobre los ultimos 64 tokens penaliza tambien nombres de personajes y
palabras funcionales, y un resumen o un esquema necesitan una temperatura
mucho mas baja que la prosa.

Ahora:
- cada tarea tiene sus propios valores por defecto (TASK_DEFAULTS);
- la prosa tiene presets ("Creativo", "Equilibrado", "Preciso") y un modo
  "Personalizado" con todos los parametros editables (pestana Modelo);
- la semilla es opcional: vacia = aleatoria (la que se uso se muestra y se
  guarda en el historial del capitulo), fija = resultado reproducible.

La configuracion se guarda por proyecto (Project.sampling).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Dict, Optional

TASK_PROSE = "prose"
TASK_OUTLINE = "outline"
TASK_SUMMARY = "summary"
TASK_REFINE = "refine"
TASK_EXPAND = "expand"
TASKS = (TASK_PROSE, TASK_OUTLINE, TASK_SUMMARY, TASK_REFINE, TASK_EXPAND)

TASK_LABELS = {
    TASK_PROSE: "Prosa",
    TASK_OUTLINE: "Esquema",
    TASK_SUMMARY: "Resúmenes",
    TASK_REFINE: "Refinar / reescribir",
    TASK_EXPAND: "Expandir con IA",
}


@dataclass(frozen=True)
class SamplingSettings:
    temperature: float = 0.9
    top_p: float = 1.0
    min_p: float = 0.05
    top_k: int = 0  # 0 = desactivado
    repeat_penalty: float = 1.07
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0

    def to_kwargs(self) -> dict:
        """Argumentos para llama_cpp.Llama.create_completion()."""
        return asdict(self)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: Optional[dict], base: Optional["SamplingSettings"] = None) -> "SamplingSettings":
        """Construye desde un dict (p.ej. leido de un proyecto), ignorando
        claves desconocidas y valores invalidos y acotando cada valor a un
        rango razonable."""
        base = base or SamplingSettings()
        if not isinstance(data, dict):
            return base
        values = {}
        for name, (lo, hi, cast) in _LIMITS.items():
            if name not in data:
                continue
            try:
                value = cast(data[name])
            except (TypeError, ValueError):
                continue
            values[name] = min(max(value, lo), hi)
        return replace(base, **values)


# (minimo, maximo, tipo) de cada parametro.
_LIMITS = {
    "temperature": (0.0, 2.0, float),
    "top_p": (0.0, 1.0, float),
    "min_p": (0.0, 1.0, float),
    "top_k": (0, 200, int),
    "repeat_penalty": (1.0, 2.0, float),
    "presence_penalty": (-2.0, 2.0, float),
    "frequency_penalty": (-2.0, 2.0, float),
}

TASK_DEFAULTS: Dict[str, SamplingSettings] = {
    TASK_PROSE: SamplingSettings(temperature=0.9, top_p=1.0, min_p=0.05, top_k=0, repeat_penalty=1.07),
    TASK_OUTLINE: SamplingSettings(temperature=0.5, top_p=0.95, min_p=0.05, top_k=40, repeat_penalty=1.05),
    TASK_SUMMARY: SamplingSettings(temperature=0.3, top_p=0.9, min_p=0.05, top_k=40, repeat_penalty=1.05),
    TASK_REFINE: SamplingSettings(temperature=0.7, top_p=0.95, min_p=0.05, top_k=0, repeat_penalty=1.05),
    TASK_EXPAND: SamplingSettings(temperature=0.7, top_p=0.95, min_p=0.05, top_k=0, repeat_penalty=1.05),
}

PRESET_CREATIVE = "Creativo"
PRESET_BALANCED = "Equilibrado"
PRESET_PRECISE = "Preciso"
PRESET_CUSTOM = "Personalizado"
PROSE_PRESETS: Dict[str, SamplingSettings] = {
    PRESET_CREATIVE: SamplingSettings(temperature=1.05, top_p=1.0, min_p=0.08, top_k=0, repeat_penalty=1.05),
    PRESET_BALANCED: TASK_DEFAULTS[TASK_PROSE],
    PRESET_PRECISE: SamplingSettings(temperature=0.7, top_p=0.9, min_p=0.05, top_k=40, repeat_penalty=1.1),
}
PRESET_CHOICES = [PRESET_CREATIVE, PRESET_BALANCED, PRESET_PRECISE, PRESET_CUSTOM]


@dataclass
class SamplingConfig:
    """La configuracion completa que se guarda en un proyecto."""
    preset: str = PRESET_BALANCED
    # Solo se usa con preset == PRESET_CUSTOM.
    custom_prose: SamplingSettings = TASK_DEFAULTS[TASK_PROSE]
    # None = semilla aleatoria en cada operacion.
    seed: Optional[int] = None

    def prose(self) -> SamplingSettings:
        if self.preset == PRESET_CUSTOM:
            return self.custom_prose
        return PROSE_PRESETS.get(self.preset, TASK_DEFAULTS[TASK_PROSE])

    def for_task(self, task: str) -> SamplingSettings:
        if task == TASK_PROSE:
            return self.prose()
        return TASK_DEFAULTS.get(task, TASK_DEFAULTS[TASK_PROSE])

    def to_dict(self) -> dict:
        return {"preset": self.preset, "custom_prose": self.custom_prose.to_dict(), "seed": self.seed}

    @staticmethod
    def from_dict(data: Optional[dict]) -> "SamplingConfig":
        if not isinstance(data, dict):
            return SamplingConfig()
        preset = data.get("preset")
        if preset not in PRESET_CHOICES:
            preset = PRESET_BALANCED
        seed = parse_seed(data.get("seed"))
        custom = SamplingSettings.from_dict(data.get("custom_prose"), TASK_DEFAULTS[TASK_PROSE])
        return SamplingConfig(preset=preset, custom_prose=custom, seed=seed)


MAX_SEED = 2**31 - 1


def parse_seed(value) -> Optional[int]:
    """None/""/valor invalido => None (aleatoria). Acepta int o texto."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return None
    if seed < 0:
        return None
    return seed % (MAX_SEED + 1)
