"""
Menu de la ventana principal, atajos de teclado globales y cancelar la
tarea en curso.
"""
from __future__ import annotations

import tkinter as tk

from . import strings_es as S


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
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
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
        menubar.add_cascade(label=S.MENU_ARCHIVO, menu=file_menu)
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label=S.BUSCAR_EN_EL_CAPITULO, command=self.find_in_chapter, accelerator=S.CTRL_F)
        edit_menu.add_command(label=S.BUSCAR_EN_PROYECTO_MENU, command=self.open_project_search,
                              accelerator=S.CTRL_SHIFT_F)
        edit_menu.add_separator()
        edit_menu.add_command(label=S.CONVERSACION_MENU, command=self.open_side_chat)
        edit_menu.add_command(label=S.COMPONENTES_MENU, command=self.open_prompt_components)
        menubar.add_cascade(label=S.MENU_EDITAR, menu=edit_menu)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label=S.MODO_ENFOQUE, command=self.toggle_focus_mode, accelerator=S.F11)
        view_menu.add_command(label=S.VER_EL_ULTIMO_PROMPT_ENVIADO, command=self.show_last_prompt)
        view_menu.add_command(label=S.MATRIZ_MENU, command=self.open_story_matrix)
        menubar.add_cascade(label=S.MENU_VER, menu=view_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=S.ACERCA_DE_STORYFORGE, command=self.show_about)
        help_menu.add_command(label=S.ABRIR_CARPETA_DE_REGISTROS, command=self._open_log_folder)
        menubar.add_cascade(label=S.MENU_AYUDA, menu=help_menu)
        self.configure(menu=menubar)

    # ---------------- atajos de teclado ----------------
    SHORTCUTS = {
        "<Control-n>": "new_project",
        "<Control-o>": "open_project",
        "<Control-s>": "save_project",
        "<Control-S>": "save_project_as",  # Ctrl+Shift+S
        "<Control-f>": "find_in_chapter",
        "<Control-F>": "open_project_search",  # Ctrl+Shift+F
        "<F11>": "toggle_focus_mode",
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
        # El cuadro de texto de Tk trae Ctrl+O = "insertar salto de linea" y
        # Ctrl+F = "avanzar un caracter": sin quitarlos, el atajo tambien
        # editaria el texto.
        self.bind_class("Text", "<Control-o>", "")
        self.bind_class("Text", "<Control-f>", "")
        # Cualquier tecla puede dejar cambios sin guardar (F10).
        self.bind_all("<KeyRelease>", lambda _e: self.schedule_dirty_check(), add="+")

    def cancel_running_generation(self) -> None:
        """Esc: cancela la generacion de capitulo (o tarea) en curso."""
        for panel in self.chapter_panels:
            if panel._cancel_flag is not None:
                panel._on_cancel()
        self.task_runner.request_stop()

    def stop_current_task(self) -> None:
        """Boton "Detener" de la barra de estado: cualquier tarea del modelo."""
        self.cancel_running_generation()
