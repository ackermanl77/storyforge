"""
Formato de chat: convierte un prompts.ChatPrompt (turno de sistema + turno
de usuario + comienzo opcional de la respuesta) en el texto exacto que se le
pasa a llama.cpp como completion.

Los modelos instruct (Llama 3.x Instruct, Mistral, Qwen, y derivados como
los "abliterated") siguen mucho mejor las instrucciones cuando las reciben en
el formato de turnos con el que fueron entrenados. Antes toda la app usaba
completion cruda: las reglas eran solo "texto anterior" para el modelo.

Se sigue usando create_completion() sobre el texto ya renderizado (no
create_chat_completion()): asi el streaming, los stop, la cancelacion y la
reutilizacion del prefijo en la cache KV de llama.cpp funcionan igual que
antes, y se puede "pre-llenar" la respuesta del asistente con el final del
capitulo para que el modelo CONTINUE la prosa en vez de contestar.

Opciones (pestana Modelo, "Formato de chat"):
- auto:    la plantilla Jinja del propio GGUF (tokenizer.chat_template) si
           existe; si no, se deduce por los tokens especiales del vocabulario
           (p.ej. <|start_header_id|> => Llama 3); si nada coincide, raw.
- llama3 / chatml / mistral / alpaca: plantillas escritas a mano.
- raw:     sin plantilla (modelos base), el comportamiento de siempre.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional

from .prompts import ChatPrompt

CHAT_FORMAT_AUTO = "auto"
CHAT_FORMAT_GGUF = "gguf"  # resultado de "auto" cuando el GGUF trae plantilla propia
CHAT_FORMAT_LLAMA3 = "llama3"
CHAT_FORMAT_CHATML = "chatml"
CHAT_FORMAT_MISTRAL = "mistral"
CHAT_FORMAT_ALPACA = "alpaca"
CHAT_FORMAT_RAW = "raw"

# Opciones que el usuario puede elegir, en el orden en que se muestran.
CHAT_FORMAT_CHOICES = [
    CHAT_FORMAT_AUTO,
    CHAT_FORMAT_LLAMA3,
    CHAT_FORMAT_CHATML,
    CHAT_FORMAT_MISTRAL,
    CHAT_FORMAT_ALPACA,
    CHAT_FORMAT_RAW,
]

CHAT_FORMAT_LABELS: Dict[str, str] = {
    CHAT_FORMAT_AUTO: "Auto (desde el GGUF)",
    CHAT_FORMAT_GGUF: "Plantilla del GGUF",
    CHAT_FORMAT_LLAMA3: "Llama 3",
    CHAT_FORMAT_CHATML: "ChatML (Qwen, etc.)",
    CHAT_FORMAT_MISTRAL: "Mistral",
    CHAT_FORMAT_ALPACA: "Alpaca",
    CHAT_FORMAT_RAW: "Sin plantilla (modelo base)",
}


def chat_format_from_label(label: str) -> str:
    for key, value in CHAT_FORMAT_LABELS.items():
        if value == label:
            return key
    return CHAT_FORMAT_AUTO


class ChatFormatter:
    """Renderiza un ChatPrompt a texto. `stop` son secuencias de fin de turno
    que se agregan a los stop de cada llamada (llama.cpp ya corta en los
    tokens de fin de turno que conoce; esto es una red de seguridad)."""

    key = CHAT_FORMAT_RAW
    stop: List[str] = []

    @property
    def is_chat(self) -> bool:
        return self.key != CHAT_FORMAT_RAW

    @property
    def label(self) -> str:
        return CHAT_FORMAT_LABELS.get(self.key, self.key)

    def render(self, prompt) -> str:
        if isinstance(prompt, str):
            return prompt
        return self._render(prompt)

    def _render(self, prompt: ChatPrompt) -> str:
        return prompt.raw


class RawFormatter(ChatFormatter):
    key = CHAT_FORMAT_RAW


class Llama3Formatter(ChatFormatter):
    key = CHAT_FORMAT_LLAMA3
    stop = ["<|eot_id|>"]

    def _render(self, prompt: ChatPrompt) -> str:
        # Sin <|begin_of_text|>: llama.cpp agrega el BOS por su cuenta.
        # Un prompt sin sistema (prompt propio de un capitulo) no lleva ese turno.
        system = f"<|start_header_id|>system<|end_header_id|>\n\n{prompt.system}<|eot_id|>" if prompt.system else ""
        return (
            f"{system}"
            "<|start_header_id|>user<|end_header_id|>\n\n"
            f"{prompt.user}<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n\n"
            f"{prompt.prefill}"
        )


class ChatMLFormatter(ChatFormatter):
    key = CHAT_FORMAT_CHATML
    stop = ["<|im_end|>"]

    def _render(self, prompt: ChatPrompt) -> str:
        system = f"<|im_start|>system\n{prompt.system}<|im_end|>\n" if prompt.system else ""
        return (
            f"{system}"
            f"<|im_start|>user\n{prompt.user}<|im_end|>\n"
            f"<|im_start|>assistant\n{prompt.prefill}"
        )


class MistralFormatter(ChatFormatter):
    key = CHAT_FORMAT_MISTRAL
    stop = ["</s>", "[INST]"]

    def _render(self, prompt: ChatPrompt) -> str:
        # Mistral no tiene turno de sistema: va al principio del turno de usuario.
        system = f"{prompt.system}\n\n" if prompt.system else ""
        return f"[INST] {system}{prompt.user} [/INST]{prompt.prefill}"


class AlpacaFormatter(ChatFormatter):
    key = CHAT_FORMAT_ALPACA
    stop = ["### Instruction:"]

    def _render(self, prompt: ChatPrompt) -> str:
        system = f"{prompt.system}\n\n" if prompt.system else ""
        return f"{system}### Instruction:\n{prompt.user}\n\n### Response:\n{prompt.prefill}"


class JinjaTemplateFormatter(ChatFormatter):
    """
    La plantilla Jinja que trae el propio GGUF (metadata
    tokenizer.chat_template), renderizada igual que lo hace transformers/
    llama-cpp-python. Si la plantilla no admite el rol "system" (Gemma,
    algunas Mistral lo rechazan con raise_exception), el turno de sistema se
    une al de usuario.
    """

    key = CHAT_FORMAT_GGUF

    def __init__(self, template: str, bos_token: str = "", eos_token: str = ""):
        import jinja2
        import jinja2.ext
        from jinja2.sandbox import ImmutableSandboxedEnvironment

        def raise_exception(message: str):
            raise ValueError(message)

        env = ImmutableSandboxedEnvironment(
            loader=jinja2.BaseLoader(), trim_blocks=True, lstrip_blocks=True,
            extensions=[jinja2.ext.loopcontrols],
        )
        env.globals["raise_exception"] = raise_exception
        env.globals["strftime_now"] = lambda fmt: datetime.now().strftime(fmt)
        self._template = env.from_string(template)
        self._bos = bos_token or ""
        self._eos = eos_token or ""
        self.stop = [eos_token] if eos_token else []

    def _render_messages(self, messages: List[dict]) -> str:
        # bos_token vacio: llama.cpp agrega el BOS por su cuenta al tokenizar
        # el prompt; renderizarlo aqui tambien lo duplicaria.
        return self._template.render(
            messages=messages, add_generation_prompt=True, bos_token="", eos_token=self._eos,
        )

    def _render(self, prompt: ChatPrompt) -> str:
        if not prompt.system:
            text = self._render_messages([{"role": "user", "content": prompt.user}])
        else:
            try:
                text = self._render_messages([
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ])
            except Exception:  # noqa: BLE001 - plantilla sin rol system
                text = self._render_messages([
                    {"role": "user", "content": f"{prompt.system}\n\n{prompt.user}"},
                ])
        if self._bos and text.startswith(self._bos):
            text = text[len(self._bos):]
        return text + prompt.prefill


_PRESETS = {
    CHAT_FORMAT_RAW: RawFormatter,
    CHAT_FORMAT_LLAMA3: Llama3Formatter,
    CHAT_FORMAT_CHATML: ChatMLFormatter,
    CHAT_FORMAT_MISTRAL: MistralFormatter,
    CHAT_FORMAT_ALPACA: AlpacaFormatter,
}


def preset_formatter(key: str) -> ChatFormatter:
    return _PRESETS.get(key, RawFormatter)()


def detect_formatter(
    metadata: Optional[dict],
    has_special_token: Callable[[str], bool],
    bos_token: str = "",
    eos_token: str = "",
) -> ChatFormatter:
    """
    Resuelve "Auto": plantilla del GGUF si existe (y compila); si no, se
    deduce la familia por los tokens especiales del vocabulario. Hay modelos
    (p.ej. varios merges de Llama 3) cuyo GGUF no trae tokenizer.chat_template
    aunque son instruct: llama-cpp-python caeria en su formato por defecto
    ("llama-2"), que para ellos es el equivocado.
    """
    template = (metadata or {}).get("tokenizer.chat_template")
    if template:
        try:
            return JinjaTemplateFormatter(template, bos_token=bos_token, eos_token=eos_token)
        except Exception:  # noqa: BLE001 - plantilla invalida o sin jinja2
            pass
    if has_special_token("<|start_header_id|>") and has_special_token("<|eot_id|>"):
        return Llama3Formatter()
    if has_special_token("<|im_start|>") and has_special_token("<|im_end|>"):
        return ChatMLFormatter()
    if has_special_token("[INST]") and has_special_token("[/INST]"):
        return MistralFormatter()
    return RawFormatter()
