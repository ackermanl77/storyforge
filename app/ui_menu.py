"""
Menu de la ventana principal, atajos de teclado globales y cancelar la
tarea en curso.
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk

import customtkinter as ctk

from . import strings_es as S

logger = logging.getLogger(__name__)


def use_dark_popup_menus(dark: bool) -> None:
    """Windows: dark (or light) drop-down and context menus to match the app (UI2). Tk's menus are
    native there and ignore its colours; uxtheme's SetPreferredAppMode (ordinal 135, undocumented
    but what Explorer and many apps use) switches them, FlushMenuThemes (136) applies it. Anything
    unexpected leaves the system default."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        uxtheme = ctypes.WinDLL("uxtheme")
        uxtheme[135](2 if dark else 3)  # 2 = force dark, 3 = force light
        uxtheme[136]()
    except Exception:  # noqa: BLE001 -- cosmetic only
        logger.debug("could not set the menu theme", exc_info=True)


class MenuMixin:
    """Menu y atajos de StoryForgeApp."""

    def open_side_chat(self):
        """Editar > Lluvia de ideas y entrevistas (F14): una sola ventana, que se trae al frente."""
        from .ui_side_chat import SideChatWindow

        window = getattr(self, "side_chat", None)
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            return window
        self.side_chat = SideChatWindow(self)
        return self.side_chat

    def open_prompt_components(self):
        """Editar > Componentes de prompt (F20)."""
        from .ui_components import ComponentsWindow

        window = getattr(self, "components_window", None)
        if window is not None and window.winfo_exists():
            window.lift()
            return window
        self.components_window = ComponentsWindow(self)
        return self.components_window

    def open_story_matrix(self):
        """Ver > Matriz de la historia (F18)."""
        from .ui_matrix import StoryMatrixWindow

        window = getattr(self, "matrix_window", None)
        if window is not None and window.winfo_exists():
            window.refresh()
            window.lift()
            return window
        self.matrix_window = StoryMatrixWindow(self)
        return self.matrix_window

    # ---------------- menu ----------------
    def _build_menu(self) -> None:
        # UI2: the native menu bar is drawn by Windows in white whatever the theme; this bar is a
        # row of themed buttons that open the same menus (see _menu_bar()).
        file_menu = tk.Menu(self, tearoff=0)
        file_menu.add_command(label=S.NUEVO_PROYECTO, command=self.new_project, accelerator=S.CTRL_N)
        file_menu.add_command(label=S.ABRIR_PROYECTO_MENU, command=self.open_project, accelerator=S.CTRL_O)
        file_menu.add_command(label=S.IMPORTAR_MANUSCRITO_MENU, command=self.import_manuscript)
        file_menu.add_command(label=S.GUARDAR_PROYECTO, command=self.save_project, accelerator=S.CTRL_S)
        file_menu.add_command(
            label=S.GUARDAR_PROYECTO_COMO_MENU, command=self.save_project_as, accelerator=S.CTRL_SHIFT_S,
        )
        file_menu.add_separator()
        file_menu.add_command(label=S.EXPORTAR_A_WORD_DOCX, command=self.export_word)
        file_menu.add_command(label=S.EXPORTAR_A_EPUB, command=self.export_epub_file)
        file_menu.add_command(label=S.EXPORTAR_A_MARKDOWN_MD, command=self.export_markdown_file)
        file_menu.add_command(label=S.EXPORTAR_A_TXT, command=self.export_txt_file)
        file_menu.add_separator()
        file_menu.add_command(label=S.PREFERENCIAS_MENU, command=self.open_preferences)
        file_menu.add_separator()
        file_menu.add_command(label=S.SALIR, command=self._on_close)
        edit_menu = tk.Menu(self, tearoff=0)
        edit_menu.add_command(label=S.BUSCAR_EN_EL_CAPITULO, command=self.find_in_chapter, accelerator=S.CTRL_F)
        edit_menu.add_command(label=S.BUSCAR_EN_PROYECTO_MENU, command=self.open_project_search,
                              accelerator=S.CTRL_SHIFT_F)
        edit_menu.add_separator()
        edit_menu.add_command(label=S.CONVERSACION_MENU, command=self.open_side_chat)
        edit_menu.add_command(label=S.COMPONENTES_MENU, command=self.open_prompt_components)
        view_menu = tk.Menu(self, tearoff=0)
        view_menu.add_command(label=S.MODO_ENFOQUE, command=self.toggle_focus_mode, accelerator=S.F11)
        view_menu.add_command(label=S.VER_EL_ULTIMO_PROMPT_ENVIADO, command=self.show_last_prompt)
        view_menu.add_command(label=S.MATRIZ_MENU, command=self.open_story_matrix)
        help_menu = tk.Menu(self, tearoff=0)
        help_menu.add_command(label=S.ATAJOS_DE_TECLADO, command=self.show_shortcuts, accelerator=S.F1)
        help_menu.add_command(label=S.ACERCA_DE_STORYFORGE, command=self.show_about)
        help_menu.add_command(label=S.ABRIR_CARPETA_DE_REGISTROS, command=self._open_log_folder)
        self._menu_bar([(S.MENU_ARCHIVO, "a", file_menu), (S.MENU_EDITAR, "e", edit_menu), (S.MENU_VER, "v", view_menu),
                        (S.MENU_AYUDA, "u", help_menu)])

    def _menu_bar(self, menus) -> None:
        """The themed menu bar (UI2): one button per (label, Alt key, menu); F10 opens the first and
        Alt + its key opens a menu, as with the native bar (Ayuda: Alt+U, as "Ay&uda")."""
        self.menu_bar = ctk.CTkFrame(self, fg_color="transparent", height=30)
        self.menu_bar.pack(side="top", fill="x", padx=6, pady=(4, 0))
        self.menu_buttons = {}
        for label, key, menu in menus:
            button = ctk.CTkButton(
                self.menu_bar, text=label, width=0, height=26, corner_radius=4, fg_color="transparent",
                hover_color=("gray80", "gray25"), text_color=("gray10", "gray90"),
            )
            button.configure(command=lambda b=button, m=menu: self._open_menu(b, m))
            button.pack(side="left", padx=1)
            self.menu_buttons[label] = (button, menu)
            self.bind(f"<Alt-{key}>", lambda _e, b=button, m=menu: (self._open_menu(b, m), "break")[1])
        first_button, first_menu = next(iter(self.menu_buttons.values()))
        self.bind("<F10>", lambda _e: (self._open_menu(first_button, first_menu), "break")[1])
        use_dark_popup_menus(ctk.get_appearance_mode() == "Dark")

    @staticmethod
    def _open_menu(button, menu) -> None:
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    # ---------------- atajos de teclado ----------------
    SHORTCUTS = {
        "<Control-n>": "new_project",
        "<Control-o>": "open_project",
        "<Control-s>": "save_project",
        "<Control-S>": "save_project_as",  # Ctrl+Shift+S
        "<Control-f>": "find_in_chapter",
        "<Control-F>": "open_project_search",  # Ctrl+Shift+F
        "<F11>": "toggle_focus_mode",
        "<F1>": "show_shortcuts",
        "<Escape>": "cancel_running_generation",
    }

    def _bind_shortcuts(self) -> None:
        """
        Atajos globales (ver SHORTCUTS). Ctrl+Z / Ctrl+Y los da el propio
        cuadro de texto (undo=True); Ctrl+Enter se liga en el cuadro de cada
        capitulo (ChapterPanel._on_ctrl_enter).
        """
        for sequence, method_name in self.SHORTCUTS.items():
            method = getattr(self, method_name)
            # En la ventana principal (no bind_all): Esc dentro de un dialogo
            # no debe cancelar una generacion.
            self.bind(sequence, lambda _e, m=method: (m(), "break")[1])
        # Ctrl+1 … Ctrl+8: las pestañas, en orden (UI6).
        for number, name in enumerate(self.tab_names, start=1):
            self.bind(f"<Control-Key-{number}>", lambda _e, n=name: (self.tabview.set(n), "break")[1])
        # El cuadro de texto de Tk trae Ctrl+O = "insertar salto de linea" y
        # Ctrl+F = "avanzar un caracter": sin quitarlos, el atajo tambien
        # editaria el texto.
        self.bind_class("Text", "<Control-o>", "")
        self.bind_class("Text", "<Control-f>", "")
        # Cualquier tecla puede dejar cambios sin guardar (F10).
        self.bind_all("<KeyRelease>", lambda _e: self.schedule_dirty_check(), add="+")

    def show_shortcuts(self) -> None:
        """Ayuda > Atajos de teclado (F1)."""
        from .ui_dialogs import TextViewerDialog

        width = max(len(keys) for keys, _action in S.ATAJOS_LISTA)
        text = "\n".join(f"{keys.ljust(width)}   {action}" for keys, action in S.ATAJOS_LISTA)
        TextViewerDialog(self, S.ATAJOS_DE_TECLADO, text)

    def cancel_running_generation(self) -> None:
        """Esc: cancela la generacion de capitulo (o tarea) en curso."""
        for panel in self.chapter_panels:
            if panel._cancel_flag is not None:
                panel._on_cancel()
        self.task_runner.request_stop()

    def stop_current_task(self) -> None:
        """Boton "Detener" de la barra de estado: cualquier tarea del modelo."""
        self.cancel_running_generation()
