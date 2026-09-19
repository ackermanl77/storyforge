"""
Pruebas de app/gui.py. A diferencia del resto de la suite, estas SI
requieren customtkinter y poder crear una ventana real de Tk -- se saltan
automaticamente (no fallan) si eso no esta disponible en el entorno donde
corren, para no romper `python -m unittest discover -s tests` en una maquina
sin las dependencias de GUI instaladas.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GUI_AVAILABLE = True
_SKIP_REASON = ""
try:
    import tkinter as _tk

    _probe = _tk.Tk()
    _probe.destroy()
    import customtkinter  # noqa: F401

    from app.engine import ContextOverflowError, ModelNotLoadedError
    from app.gui import StoryForgeApp
except Exception as _import_exc:  # pragma: no cover - environment dependent
    GUI_AVAILABLE = False
    _SKIP_REASON = f"GUI dependencies not available: {_import_exc}"


class _SynchronousThread:
    """
    Stand-in for threading.Thread that runs `target` immediately, on the
    current (main) thread, instead of spawning a real OS thread.

    The bug these tests exist for (a lambda referencing a name that
    `except X as name:` already deleted by the time the lambda actually
    runs) is purely about Python variable-scope timing: it happens as soon
    as something *defers* a callback past the end of its except block, via
    `self.app.after(0, ...)`, regardless of whether a real background
    thread was involved. Using a real thread here would also need the main
    thread to be genuinely inside Tk's C-level mainloop for a
    cross-thread `after()` registration to succeed (calling `.update()` in
    a plain Python loop does not count, and raises a *different*,
    unrelated "main thread is not in main loop" error) -- real, but a
    threading/Tcl-interaction detail this test isn't about. Running
    synchronously sidesteps that entirely while still exactly reproducing
    the scope-timing bug: `self.app.after(0, cb)` still only *schedules*
    `cb`, which this test flushes afterward with a plain `self.app.update()`
    -- after the except block (and worker()) has already returned, exactly
    like the real deferred case.
    """

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestBackgroundErrorReporting(unittest.TestCase):
    """
    ChapterPanel._on_generate, StoryForgeApp._on_generate_outline and
    StoryForgeApp._load_model all do their work on a background thread and
    report failures back to the UI via `self.app.after(0, lambda: ...)`.

    `except SomeError as exc:` deletes `exc` from scope as soon as the
    except block ends (standard Python cleanup) -- a lambda that only runs
    later, once the Tk event loop gets around to it, raises NameError when
    it references `exc` instead of showing the real error message. These
    tests reproduce that (worker runs synchronously -- see
    _SynchronousThread above for why real threading isn't needed here --
    then a real `self.app.update()` flushes the deferred `after(0, ...)`
    callback) and confirm it no longer happens.
    """

    def setUp(self):
        self.shown_errors = []
        self._messagebox_patcher = mock.patch(
            "app.gui.messagebox.showerror",
            side_effect=lambda title, msg: self.shown_errors.append(msg),
        )
        self._messagebox_patcher.start()
        # StoryForgeApp() itself can pop a real, blocking askyesno() dialog
        # on construction if an autosave/autosave.json happens to exist
        # (offers to recover it) -- always decline so this suite can never
        # hang waiting for a click that will never come, regardless of
        # what's on disk on the machine running it.
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=False)
        self._askyesno_patcher.start()
        self._thread_patcher = mock.patch("app.gui.threading.Thread", _SynchronousThread)
        self._thread_patcher.start()

        self.app = StoryForgeApp()
        self.callback_exceptions = []
        # Tkinter calls this instead of letting a callback exception
        # propagate out of mainloop/update() -- capture it so a regression
        # shows up as a test failure instead of a silently swallowed error.
        self.app.report_callback_exception = lambda *args: self.callback_exceptions.append(args)

    def tearDown(self):
        self.app.destroy()
        self._thread_patcher.stop()
        self._askyesno_patcher.stop()
        self._messagebox_patcher.stop()

    def _flush_deferred_callbacks(self):
        # worker() already ran synchronously (see _SynchronousThread) and
        # scheduled its self.after(0, ...) calls; update() now actually
        # runs them, exactly as the real Tk event loop would a moment
        # later in production.
        self.app.update()

    def test_model_not_loaded_error_shown_when_generating_a_chapter(self):
        class FailingEngine:
            is_loaded = True

            def generate_chapter(self, *a, **k):
                raise ModelNotLoadedError("no model loaded")

        self.app.engine = FailingEngine()
        self.app.project.plot = "a story"
        self.app.project.characters = "a hero"
        self.app.project.setting = "a place"
        self.app.project.add_chapter("Cap 1", target_words=100)
        self.app._render_chapters()
        panel = self.app.chapter_panels[0]

        panel._on_generate()
        self._flush_deferred_callbacks()

        self.assertEqual(self.callback_exceptions, [], f"deferred Tk callback raised: {self.callback_exceptions}")
        self.assertEqual(self.shown_errors, ["no model loaded"])

    def test_context_overflow_error_shown_when_generating_outline(self):
        class FailingEngine:
            is_loaded = True

            def generate_outline(self, *a, **k):
                raise ContextOverflowError("too much context")

        self.app.engine = FailingEngine()
        self.app.project.plot = "a story"
        self.app.project.characters = "a hero"
        self.app.project.setting = "a place"
        self.app.outline_count_entry.delete(0, "end")
        self.app.outline_count_entry.insert(0, "1")

        self.app._on_generate_outline()
        self._flush_deferred_callbacks()

        self.assertEqual(self.callback_exceptions, [], f"deferred Tk callback raised: {self.callback_exceptions}")
        self.assertEqual(len(self.shown_errors), 1)
        self.assertIn("too much context", self.shown_errors[0])

    def test_generic_error_shown_when_loading_a_model(self):
        class FailingEngine:
            def load(self, *a, **k):
                raise RuntimeError("bad gguf file")

        self.app.engine = FailingEngine()
        self.app.model_combo.set("fake_model.gguf")

        self.app._load_model()
        self._flush_deferred_callbacks()

        self.assertEqual(self.callback_exceptions, [], f"deferred Tk callback raised: {self.callback_exceptions}")
        self.assertIn("bad gguf file", self.app.model_status.cget("text"))


if __name__ == "__main__":
    unittest.main()
