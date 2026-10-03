"""
Ayudantes para orden de tabulacion explicito en la GUI.

CustomTkinter deja el foco real en widgets internos de Tk (`_entry`,
`_textbox`, etc.), asi que el orden por defecto no siempre coincide con el
orden visual ni es facil de probar de forma headless. Estas funciones atan
Tab / Shift+Tab a una lista explicita de widgets y saltan automaticamente
los que estan ocultos o deshabilitados.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence


def _flatten(items: Iterable) -> List[object]:
    out: List[object] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, (list, tuple)):
            out.extend(_flatten(item))
        else:
            out.append(item)
    return out


def focus_target(widget):
    """Widget de Tk que realmente recibe teclas y foco."""
    return getattr(widget, "_textbox", getattr(widget, "_entry", widget))


def _widget_exists(widget) -> bool:
    try:
        return bool(int(widget.winfo_exists()))
    except Exception:  # noqa: BLE001
        return False


def _widget_disabled(widget) -> bool:
    for candidate in (widget, focus_target(widget)):
        try:
            state = candidate.cget("state")
        except Exception:  # noqa: BLE001
            continue
        if str(state).lower() == "disabled":
            return True
    return False


def _widget_viewable(widget) -> bool:
    for candidate in (widget, focus_target(widget)):
        try:
            return bool(candidate.winfo_viewable())
        except Exception:  # noqa: BLE001
            continue
    return False


def _focusable(widget) -> bool:
    return _widget_exists(widget) and _widget_viewable(widget) and not _widget_disabled(widget)


def _move_focus(order: Sequence[object], current_index: int, step: int) -> str:
    if not order:
        return "break"
    total = len(order)
    for offset in range(1, total + 1):
        candidate = order[(current_index + step * offset) % total]
        if _focusable(candidate):
            focus_target(candidate).focus_set()
            return "break"
    return "break"


def apply_tab_order(container, *widgets) -> List[object]:
    """
    Instala un orden de foco explicito en `container`.

    Devuelve la lista normalizada de widgets y la deja tambien en
    `container._storyforge_tab_order` para las pruebas.
    """
    order = _flatten(widgets)
    container._storyforge_tab_order = order
    for index, widget in enumerate(order):
        target = focus_target(widget)
        for candidate in (widget, target):
            try:
                candidate.configure(takefocus=True)
            except Exception:  # noqa: BLE001
                pass
        for sequence, step in (("<Tab>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1)):
            # _e=None: some CustomTkinter widgets call bound callbacks without an
            # event, and a missing argument surfaced as an "unexpected error" dialog.
            target.bind(sequence, lambda _e=None, i=index, s=step, o=order: _move_focus(o, i, s))
    return order
