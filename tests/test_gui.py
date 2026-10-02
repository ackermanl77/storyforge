"""
Pruebas de app/gui.py. A diferencia del resto de la suite, estas SI
requieren customtkinter y poder crear una ventana real de Tk -- se saltan
automaticamente (no fallan) si eso no esta disponible en el entorno donde
corren, para no romper `python -m unittest discover -s tests` en una maquina
sin las dependencias de GUI instaladas.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Antes de construir cualquier StoryForgeApp: todo lo que la app escribe en
# user_data_dir() (autoguardado, settings.json) va a una carpeta temporal.
# Antes estas pruebas borraban el autosave.json REAL del usuario (en
# desarrollo, <repo>/autosave/) -- justo el archivo de recuperacion tras un
# crash. app/paths.py lee STORYFORGE_USER_DATA_DIR en cada llamada.
_TEST_USER_DATA = tempfile.TemporaryDirectory(prefix="storyforge-test-")
_PREVIOUS_USER_DATA_ENV = os.environ.get("STORYFORGE_USER_DATA_DIR")
os.environ["STORYFORGE_USER_DATA_DIR"] = _TEST_USER_DATA.name

GUI_AVAILABLE = True
_SKIP_REASON = ""
try:
    import tkinter as _tk

    _probe = _tk.Tk()
    _probe.destroy()
    import customtkinter  # noqa: F401

    from app.engine import ContextOverflowError, ModelNotLoadedError
    from app.gui import (
        CHAPTER_PURPOSE_DEFAULT_LABEL,
        StoryForgeApp,
        VersionHistoryDialog,
        _lore_entry_matches_search,
        default_autosave_path,
    )
    from app.project import LoreEntry, MAX_LORE_ENTRIES
except Exception as _import_exc:  # pragma: no cover - environment dependent
    GUI_AVAILABLE = False
    _SKIP_REASON = f"GUI dependencies not available: {_import_exc}"


def _clear_autosave() -> None:
    """
    Several actions that call the engine autosave in their `finally` block
    regardless of success or failure. Without clearing it before each test,
    StoryForgeApp() -- constructed fresh in every test's setUp -- would find
    a leftover autosave.json from a PREVIOUS test and either recover it or
    discard it depending on how that test mocked askyesno(). This only ever
    touches the temporary STORYFORGE_USER_DATA_DIR set at the top of this
    module, never the user's real autosave.
    """
    path = default_autosave_path()
    assert path.startswith(_TEST_USER_DATA.name), path  # nunca el autoguardado real
    for p in (path, path + ".bak"):
        try:
            os.remove(p)
        except OSError:
            pass


def tearDownModule():
    _clear_autosave()
    if _PREVIOUS_USER_DATA_ENV is None:
        os.environ.pop("STORYFORGE_USER_DATA_DIR", None)
    else:
        os.environ["STORYFORGE_USER_DATA_DIR"] = _PREVIOUS_USER_DATA_ENV
    _TEST_USER_DATA.cleanup()


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
        _clear_autosave()
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

    def test_error_shown_when_expanding_a_field(self):
        class FailingEngine:
            is_loaded = True

            def expand_field(self, *a, **k):
                raise ModelNotLoadedError("no model loaded")

        self.app.engine = FailingEngine()
        self.app.plot_box.set("a short idea")

        self.app._expand_field(self.app.plot_box, "plot", "Plot", 50_000)
        self._flush_deferred_callbacks()

        self.assertEqual(self.callback_exceptions, [], f"deferred Tk callback raised: {self.callback_exceptions}")
        self.assertEqual(self.shown_errors, ["no model loaded"])
        # el campo no debe haberse tocado si la expansion fallo
        self.assertEqual(self.app.plot_box.get(), "a short idea")

    def test_error_shown_when_refining_a_chapter(self):
        class FailingEngine:
            is_loaded = True

            def refine_chapter(self, *a, **k):
                raise ContextOverflowError("too much context")

        self.app.engine = FailingEngine()
        self.app.project.add_chapter("Cap 1", target_words=100)
        self.app._render_chapters()
        panel = self.app.chapter_panels[0]
        panel.chapter.content = "Existing chapter text."
        panel.content_box.insert("1.0", panel.chapter.content)
        panel.refine_entry.insert(0, "make it darker")

        # askyesno esta mockeado a False en este fixture (ver setUp) -- pero
        # _on_refine solo pide confirmar si hay contenido, y aqui SI lo hay,
        # asi que con askyesno=False la confirmacion se rechazaria y nunca
        # llegaria a llamar al motor. Para este test se necesita True.
        with mock.patch("app.gui.messagebox.askyesno", return_value=True):
            panel._on_refine()
        self._flush_deferred_callbacks()

        self.assertEqual(self.callback_exceptions, [], f"deferred Tk callback raised: {self.callback_exceptions}")
        self.assertEqual(len(self.shown_errors), 1)
        self.assertIn("too much context", self.shown_errors[0])


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestChapterPurposeSync(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=False)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()
        self.app.project.add_chapter("Cap 1")
        self.app._render_chapters()
        self.panel = self.app.chapter_panels[0]

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_selecting_a_purpose_syncs_to_the_chapter(self):
        self.panel.purpose_menu.set("Epilogo")
        self.panel.sync_to_model()
        self.assertEqual(self.panel.chapter.purpose, "Epilogo")

    def test_default_label_syncs_to_empty_string(self):
        self.panel.purpose_menu.set("Epilogo")
        self.panel.sync_to_model()
        self.panel.purpose_menu.set(CHAPTER_PURPOSE_DEFAULT_LABEL)
        self.panel.sync_to_model()
        self.assertEqual(self.panel.chapter.purpose, "")

    def test_panel_starts_with_the_chapters_existing_purpose_selected(self):
        self.app.project.chapters[0].purpose = "Final"
        self.app._render_chapters()
        panel = self.app.chapter_panels[0]
        self.assertEqual(panel.purpose_menu.get(), "Final")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestImportField(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=False)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_import_replaces_empty_field(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Imported text content.")
            path = f.name
        try:
            self.app.plot_box.set("")
            with mock.patch("app.gui.filedialog.askopenfilename", return_value=path):
                self.app._import_field(self.app.plot_box)
            self.assertEqual(self.app.plot_box.get(), "Imported text content.")
        finally:
            os.remove(path)

    def test_import_over_existing_content_requires_confirmation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("New file content.")
            path = f.name
        try:
            self.app.plot_box.set("existing content")
            with mock.patch("app.gui.filedialog.askopenfilename", return_value=path), \
                 mock.patch("app.gui.messagebox.askyesno", return_value=False) as mock_confirm:
                self.app._import_field(self.app.plot_box)
                self.assertTrue(mock_confirm.called)
            # se rechazo la confirmacion -> el contenido original sigue intacto
            self.assertEqual(self.app.plot_box.get(), "existing content")
        finally:
            os.remove(path)

    def test_cancelling_the_file_dialog_does_nothing(self):
        self.app.plot_box.set("existing content")
        with mock.patch("app.gui.filedialog.askopenfilename", return_value=""):
            self.app._import_field(self.app.plot_box)
        self.assertEqual(self.app.plot_box.get(), "existing content")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestExpandAndRefineHappyPath(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._thread_patcher = mock.patch("app.gui.threading.Thread", _SynchronousThread)
        self._thread_patcher.start()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()
        self._thread_patcher.stop()

    def test_expand_field_replaces_box_content(self):
        class FakeEngine:
            is_loaded = True

            def expand_field(self, field_key, text, max_words=400):
                return f"EXPANDED[{field_key}]: {text}"

        self.app.engine = FakeEngine()
        self.app.plot_box.set("a short idea")
        self.app._expand_field(self.app.plot_box, "plot", "Plot", 50_000)
        self.app.update()
        self.assertEqual(self.app.plot_box.get(), "EXPANDED[plot]: a short idea")

    def test_refine_chapter_replaces_content_and_records_history(self):
        class FakeEngine:
            is_loaded = True

            def refine_chapter(self, project, chapter_index, instruction):
                return f"REFINED per '{instruction}'"

        self.app.engine = FakeEngine()
        self.app.project.add_chapter("Cap 1", target_words=100)
        self.app._render_chapters()
        panel = self.app.chapter_panels[0]
        panel.chapter.content = "Original text."
        panel.content_box.insert("1.0", panel.chapter.content)
        panel.refine_entry.insert(0, "make it darker")

        panel._on_refine()
        self.app.update()
        # F4: nothing changes until the diff preview is accepted.
        self.assertEqual(panel.chapter.content, "Original text.")
        self.app.last_preview.accept()

        self.assertEqual(panel.chapter.content, "REFINED per 'make it darker'")
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), panel.chapter.content)
        self.assertEqual(panel.chapter.history, ["Original text."])
        self.assertEqual(panel.history_btn.cget("text"), "Versiones anteriores (1)")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestVersionHistoryDialog(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()
        self.app.project.add_chapter("Cap 1")
        self.app._render_chapters()
        self.panel = self.app.chapter_panels[0]
        self.panel.chapter.content = "first draft"
        self.panel.chapter.push_history()
        self.panel.chapter.content = "second draft"
        self.panel.chapter.push_history()
        self.panel.chapter.content = "current draft"
        # The text box is the source of truth for the current content (what
        # sync_to_model() reads) -- keep it consistent with chapter.content.
        self.panel.content_box.insert("1.0", "current draft")

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_restore_preserves_unsynced_manual_edits_in_history(self):
        # Before: push_history() saved the stale chapter.content, so edits
        # typed since the last sync were lost for good on restore.
        self.panel.content_box.insert("end", " plus a hand-typed ending")
        dialog = VersionHistoryDialog(self.app, self.panel)
        dialog._on_restore()
        self.assertIn("current draft plus a hand-typed ending", self.panel.chapter.history)
        self.assertEqual(self.panel.chapter.content, "second draft")

    def test_most_recent_version_is_shown_first_and_previewed_by_default(self):
        dialog = VersionHistoryDialog(self.app, self.panel)
        try:
            self.assertIn("Versión 2", dialog._labels[0])
            self.assertEqual(dialog.preview_box.get("1.0", "end-1c"), "second draft")
        finally:
            dialog.destroy()

    def test_restore_replaces_content_and_preserves_it_in_history(self):
        dialog = VersionHistoryDialog(self.app, self.panel)
        try:
            dialog._on_restore()  # restaura la version seleccionada por defecto (la mas reciente)
        finally:
            pass  # _on_restore ya se encarga de destroy()
        self.assertEqual(self.panel.chapter.content, "second draft")
        self.assertEqual(self.panel.content_box.get("1.0", "end-1c"), "second draft")
        # "current draft" (lo que habia antes de restaurar) queda preservado
        self.assertIn("current draft", self.panel.chapter.history)

    def test_history_button_opens_dialog_only_when_history_exists(self):
        self.app.project.add_chapter("Cap sin historial")
        self.app._render_chapters()
        empty_panel = self.app.chapter_panels[1]
        with mock.patch("app.gui.messagebox.showinfo") as mock_info:
            empty_panel._on_show_history()
            mock_info.assert_called_once()


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestLorebookPanel(unittest.TestCase):
    """
    The Lorebook tab's list-editor (LoreEntryPanel/_render_lore_entries),
    following the same add/edit/remove-via-panel pattern already used for
    chapters (ChapterPanel/_render_chapters).
    """

    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_starts_with_no_entries(self):
        self.assertEqual(self.app.project.lore_entries, [])
        self.assertEqual(self.app.lore_panels, [])

    def test_add_entry_creates_a_panel(self):
        self.app.add_lore_entry()
        self.assertEqual(len(self.app.project.lore_entries), 1)
        self.assertEqual(len(self.app.lore_panels), 1)

    def test_editing_fields_and_syncing_updates_the_model(self):
        self.app.add_lore_entry()
        panel = self.app.lore_panels[0]
        panel.name_entry.insert(0, "Elena")
        panel.keywords_entry.insert(0, "Elena, the queen")
        panel.text_box.insert("1.0", "Ruler of the kingdom.")

        panel.sync_to_model()

        self.assertEqual(panel.entry.name, "Elena")
        self.assertEqual(panel.entry.keyword_list(), ["Elena", "the queen"])
        self.assertEqual(panel.entry.text, "Ruler of the kingdom.")

    def test_app_sync_all_syncs_lore_panels_too(self):
        self.app.add_lore_entry()
        panel = self.app.lore_panels[0]
        panel.name_entry.insert(0, "Elena")

        self.app._sync_all()

        self.assertEqual(self.app.project.lore_entries[0].name, "Elena")

    def test_remove_lore_entry_removes_the_right_one(self):
        self.app.add_lore_entry()
        self.app.add_lore_entry()
        first_entry = self.app.project.lore_entries[0]
        second_entry = self.app.project.lore_entries[1]

        self.app.remove_lore_entry(0)

        self.assertEqual(len(self.app.project.lore_entries), 1)
        self.assertIs(self.app.project.lore_entries[0], second_entry)
        self.assertIsNot(self.app.project.lore_entries[0], first_entry)

    def test_remove_button_requires_confirmation(self):
        self.app.add_lore_entry()
        panel = self.app.lore_panels[0]
        with mock.patch("app.gui.messagebox.askyesno", return_value=False) as mock_confirm:
            panel._on_remove()
            mock_confirm.assert_called_once()
        # confirmacion rechazada -> la entrada sigue ahi
        self.assertEqual(len(self.app.project.lore_entries), 1)

    def test_cannot_add_more_than_max_lore_entries(self):
        self.app.project.lore_entries = [LoreEntry() for _ in range(MAX_LORE_ENTRIES)]
        with mock.patch("app.gui.messagebox.showinfo") as mock_info:
            self.app.add_lore_entry()
            mock_info.assert_called_once()
        self.assertEqual(len(self.app.project.lore_entries), MAX_LORE_ENTRIES)

    def test_load_into_ui_renders_the_projects_lore_entries(self):
        self.app.project.add_lore_entry(name="Elena", keywords="Elena", text="Ruler.")
        self.app._load_into_ui()
        self.assertEqual(len(self.app.lore_panels), 1)
        self.assertEqual(self.app.lore_panels[0].name_entry.get(), "Elena")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestChapterStreamingDisplay(unittest.TestCase):
    """
    LocalStoryEngine.generate_chapter() now calls progress_callback much
    more often (token-level streaming -- see app/engine.py) instead of once
    per ~900-word section. ChapterPanel._on_generate()'s `progress` closure
    throttles how often it actually schedules a screen update (see
    CHAPTER_STREAM_UI_INTERVAL_SECONDS in app/ui_chapter_editor.py) so a fast burst of
    calls -- as happens here, since the worker runs synchronously -- doesn't
    flood the Tk event queue. This must never cause the FINAL displayed text
    to be a stale, throttled-away partial update instead of the engine's
    real final result.
    """

    def setUp(self):
        _clear_autosave()
        self._thread_patcher = mock.patch("app.gui.threading.Thread", _SynchronousThread)
        self._thread_patcher.start()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()
        self.app.project.add_chapter("Cap 1", target_words=50)
        self.app._render_chapters()
        self.panel = self.app.chapter_panels[0]

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()
        self._thread_patcher.stop()

    def test_final_content_matches_result_despite_throttled_partial_updates(self):
        class FakeEngine:
            is_loaded = True

            def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None):
                # Simula una rafaga de actualizaciones de streaming, como
                # llegarian token a token en una generacion real -- todas
                # ocurren practicamente al mismo tiempo (ejecucion
                # sincronica), asi que el throttle de la UI debe descartar
                # la mayoria de ellas sin perder el resultado final.
                for i in range(1, 6):
                    progress_callback(f"partial {i}", i * 10, 50)
                return "FINAL COMPLETE CHAPTER TEXT"

            def summarize(self, text, max_words=150):
                return "a summary"

        self.app.engine = FakeEngine()

        self.panel._on_generate()
        self.app.update()

        self.assertEqual(self.panel.content_box.get("1.0", "end-1c"), "FINAL COMPLETE CHAPTER TEXT")
        self.assertEqual(self.panel.chapter.content, "FINAL COMPLETE CHAPTER TEXT")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestChapterStreamingAppend(unittest.TestCase):
    """
    ChapterPanel._on_generate()'s `progress` closure used to do a full
    content_box.delete("1.0", "end") + insert("1.0", text) on every
    throttled update -- a flash-and-reset that snapped the view back to the
    top if the user had scrolled down mid-generation. It now tracks how
    much text is already shown and only appends the new suffix at "end",
    auto-following with content_box.see("end"); a full delete+reinsert is
    kept only for the guaranteed-correct final redraw (see
    TestChapterStreamingDisplay above, which already covers that the FINAL
    text is always correct regardless of throttling).

    The interval throttle is patched to 0 here so every progress_callback
    call actually reaches the UI instead of being throttled away -- this
    test is specifically about the append-vs-replace mechanics of each
    individual update, not the throttling itself.
    """

    def setUp(self):
        _clear_autosave()
        self._thread_patcher = mock.patch("app.gui.threading.Thread", _SynchronousThread)
        self._thread_patcher.start()
        self._interval_patcher = mock.patch("app.ui_chapter_editor.CHAPTER_STREAM_UI_INTERVAL_SECONDS", 0.0)
        self._interval_patcher.start()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()
        self.app.project.add_chapter("Cap 1", target_words=50)
        self.app._render_chapters()
        self.panel = self.app.chapter_panels[0]

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()
        self._interval_patcher.stop()
        self._thread_patcher.stop()

    def test_incremental_updates_append_instead_of_replacing_everything(self):
        class FakeEngine:
            is_loaded = True

            def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None):
                progress_callback("Once", 1, 50)
                progress_callback("Once upon", 2, 50)
                progress_callback("Once upon a time", 4, 50)
                return "Once upon a time"

            def summarize(self, text, max_words=150):
                return "a summary"

        self.app.engine = FakeEngine()
        insert_calls = []
        real_insert = self.panel.content_box.insert

        def spy_insert(index, text, *a, **k):
            insert_calls.append((index, text))
            return real_insert(index, text, *a, **k)

        self.panel.content_box.insert = spy_insert

        self.panel._on_generate()
        self.app.update()

        end_inserts = [text for index, text in insert_calls if index == "end"]
        start_inserts = [text for index, text in insert_calls if index == "1.0"]

        # Cada actualizacion incremental durante el streaming debe ser un
        # append pequeno en "end" -- nunca el texto completo reinsertado
        # desde "1.0".
        self.assertEqual(len(end_inserts), 3)
        self.assertEqual(end_inserts, ["Once", " upon", " a time"])
        # Solo el redibujado final (show_final) puede insertar desde "1.0",
        # y debe hacerlo exactamente una vez.
        self.assertEqual(start_inserts, ["Once upon a time"])
        self.assertEqual(self.panel.content_box.get("1.0", "end-1c"), "Once upon a time")
        self.assertEqual(self.panel.chapter.content, "Once upon a time")

    def test_auto_follows_to_the_end_on_each_incremental_update(self):
        # Documenta la eleccion deliberada: el cuadro siempre sigue el texto
        # nuevo automaticamente (comportamiento habitual de streaming),
        # en vez de intentar detectar si el usuario scrolleo manualmente.
        class FakeEngine:
            is_loaded = True

            def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None):
                progress_callback("Once upon a time", 4, 50)
                return "Once upon a time"

            def summarize(self, text, max_words=150):
                return "a summary"

        self.app.engine = FakeEngine()
        see_calls = []
        real_see = self.panel.content_box.see

        def spy_see(index):
            see_calls.append(index)
            return real_see(index)

        self.panel.content_box.see = spy_see

        self.panel._on_generate()
        self.app.update()

        self.assertIn("end", see_calls)


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestLorebookSearchFilter(unittest.TestCase):
    """
    Pure filter-matching logic (_lore_entry_matches_search) plus the search
    box wired into _render_lore_entries().
    """

    def test_matches_name_case_insensitively(self):
        entry = LoreEntry(name="Elena Vasquez", keywords="")
        self.assertTrue(_lore_entry_matches_search(entry, "elena"))
        self.assertTrue(_lore_entry_matches_search(entry, "VASQUEZ".lower()))
        self.assertFalse(_lore_entry_matches_search(entry, "marco"))

    def test_matches_keyword_substring(self):
        entry = LoreEntry(name="Dark Forest", keywords="forest, ancient woods")
        self.assertTrue(_lore_entry_matches_search(entry, "wood"))
        self.assertTrue(_lore_entry_matches_search(entry, "forest"))
        self.assertFalse(_lore_entry_matches_search(entry, "ocean"))

    def test_empty_query_matches_everything(self):
        entry = LoreEntry(name="Anyone", keywords="")
        self.assertTrue(_lore_entry_matches_search(entry, ""))

    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_search_entry_filters_the_rendered_panels_by_name(self):
        self.app.project.add_lore_entry(name="Elena Vasquez", keywords="Elena")
        self.app.project.add_lore_entry(name="Dark Forest", keywords="forest, woods")
        self.app._render_lore_entries()
        self.assertEqual(len(self.app.lore_panels), 2)

        self.app.lore_search_entry.insert(0, "elena")
        self.app._render_lore_entries()

        self.assertEqual(len(self.app.lore_panels), 1)
        self.assertEqual(self.app.lore_panels[0].entry.name, "Elena Vasquez")

    def test_search_entry_filters_the_rendered_panels_by_keyword(self):
        self.app.project.add_lore_entry(name="Elena Vasquez", keywords="the queen")
        self.app.project.add_lore_entry(name="Dark Forest", keywords="forest, woods")
        self.app._render_lore_entries()

        self.app.lore_search_entry.insert(0, "wood")
        self.app._render_lore_entries()

        self.assertEqual(len(self.app.lore_panels), 1)
        self.assertEqual(self.app.lore_panels[0].entry.name, "Dark Forest")

    def test_no_matches_shows_placeholder_instead_of_erroring(self):
        self.app.project.add_lore_entry(name="Elena Vasquez", keywords="Elena")
        self.app._render_lore_entries()

        self.app.lore_search_entry.insert(0, "nonexistent-xyz")
        self.app._render_lore_entries()

        self.assertEqual(self.app.lore_panels, [])

    def test_editing_a_field_survives_a_search_triggered_rerender(self):
        # _render_lore_entries() now runs on every keystroke in the search
        # box (destroying and recreating every panel) -- it must sync
        # pending edits from the currently-visible panels into the model
        # first, or typing a search term while another entry has unsaved
        # edits would silently discard them.
        self.app.project.add_lore_entry(name="Elena Vasquez", keywords="Elena")
        self.app._render_lore_entries()
        panel = self.app.lore_panels[0]
        panel.name_entry.delete(0, "end")
        panel.name_entry.insert(0, "Elena Renamed")

        self.app.lore_search_entry.insert(0, "x")  # no matches, forces a rerender
        self.app._render_lore_entries()

        self.assertEqual(self.app.project.lore_entries[0].name, "Elena Renamed")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestLorebookMatchedLastGeneration(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_badge_shown_only_for_entries_in_last_lore_match_ids(self):
        matched_entry = self.app.project.add_lore_entry(name="Elena", keywords="Elena")
        self.app.project.add_lore_entry(name="Marco", keywords="Marco")
        self.app.last_lore_match_ids = {id(matched_entry)}
        self.app._render_lore_entries()

        by_name = {p.entry.name: p for p in self.app.lore_panels}
        self.assertTrue(by_name["Elena"].matched_last_generation)
        self.assertFalse(by_name["Marco"].matched_last_generation)

    def test_generating_a_chapter_records_and_surfaces_lore_matches(self):
        entry = self.app.project.add_lore_entry(name="Elena", keywords="Elena")
        self.app.project.add_chapter("Cap 1", target_words=50, outline="Elena arrives at the castle.")
        self.app._render_chapters()
        panel = self.app.chapter_panels[0]

        class FakeEngine:
            is_loaded = True

            def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None):
                return "Elena walked in."

            def summarize(self, text, max_words=150):
                return "a summary"

        self.app.engine = FakeEngine()
        with mock.patch("app.gui.threading.Thread", _SynchronousThread):
            panel._on_generate()
        self.app.update()

        self.assertIn(id(entry), self.app.last_lore_match_ids)
        self.app._render_lore_entries()
        self.assertTrue(self.app.lore_panels[0].matched_last_generation)

    def test_new_project_clears_previous_matches(self):
        entry = self.app.project.add_lore_entry(name="Elena", keywords="Elena")
        self.app.last_lore_match_ids = {id(entry)}

        self.app.project = self.app.project.__class__()
        self.app.current_path = None
        self.app._load_into_ui()

        self.assertEqual(self.app.last_lore_match_ids, set())


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestChapterSidebar(unittest.TestCase):
    """
    A slim, persistent chapter list next to the main scrollable chapter
    panels (_render_chapters() stacks every chapter's full 220px+6-button
    panel expanded, which becomes a long scroll with no way to jump
    directly to one) -- clicking an entry here jumps chapters_scroll to
    that chapter's panel via _jump_to_chapter().
    """

    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=False)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def _sidebar_buttons(self):
        return [
            w for w in self.app.chapter_sidebar.winfo_children()
            if isinstance(w, customtkinter.CTkButton)
        ]

    def test_no_chapters_shows_placeholder_and_no_buttons(self):
        self.assertEqual(self._sidebar_buttons(), [])

    def test_sidebar_lists_one_entry_per_chapter_with_its_title(self):
        self.app.project.add_chapter("Intro")
        self.app.project.add_chapter("Middle")
        self.app._render_chapters()

        buttons = self._sidebar_buttons()
        self.assertEqual(len(buttons), 2)
        self.assertIn("Intro", buttons[0].cget("text"))
        self.assertIn("Middle", buttons[1].cget("text"))

    def test_clicking_a_sidebar_entry_jumps_to_the_right_chapter(self):
        self.app.project.add_chapter("Intro")
        self.app.project.add_chapter("Middle")
        self.app._render_chapters()

        with mock.patch.object(self.app, "_jump_to_chapter") as mock_jump:
            self._sidebar_buttons()[1].cget("command")()
        mock_jump.assert_called_once_with(1)

    def test_jump_to_chapter_scrolls_without_raising(self):
        self.app.project.add_chapter("Intro")
        self.app.project.add_chapter("Middle")
        self.app.project.add_chapter("End")
        self.app._render_chapters()
        self.app.update()

        try:
            self.app._jump_to_chapter(2)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_jump_to_chapter raised: {exc}")

    def test_jump_to_chapter_ignores_out_of_range_index(self):
        self.app.project.add_chapter("Intro")
        self.app._render_chapters()
        try:
            self.app._jump_to_chapter(5)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_jump_to_chapter raised for an out-of-range index: {exc}")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestChapterAddRemoveKeepsUnsavedEdits(unittest.TestCase):
    """add_chapter()/remove_chapter() destroy and rebuild every chapter and
    outline panel from project.chapters -- without a _sync_all() first, any
    text typed since the last sync was silently thrown away."""

    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()
        self.app.project.add_chapter("Cap 1")
        self.app.project.add_chapter("Cap 2")
        self.app._render_chapters()
        self.app._render_outline_panels()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_add_chapter_keeps_unsynced_content_and_outline(self):
        self.app.chapter_panels[0].content_box.insert("1.0", "typed but never synced")
        self.app.outline_panels[1].outline_box.insert("1.0", "outline typed by hand")
        self.app.add_chapter()
        self.assertEqual(self.app.project.chapters[0].content, "typed but never synced")
        self.assertEqual(self.app.chapter_panels[0].content_box.get("1.0", "end-1c"), "typed but never synced")
        self.assertEqual(self.app.project.chapters[1].outline, "outline typed by hand")
        self.assertEqual(len(self.app.chapter_panels), 3)

    def test_remove_chapter_keeps_unsynced_edits_in_other_chapters(self):
        self.app.chapter_panels[0].content_box.insert("1.0", "keep me")
        self.app.remove_chapter(1)
        self.assertEqual(len(self.app.project.chapters), 1)
        self.assertEqual(self.app.chapter_panels[0].content_box.get("1.0", "end-1c"), "keep me")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestSaveErrors(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self._info_patcher = mock.patch("app.gui.messagebox.showinfo")
        self._info_patcher.start()
        self._warn_patcher = mock.patch("app.gui.messagebox.showwarning")
        self.mock_warning = self._warn_patcher.start()
        self._error_patcher = mock.patch("app.gui.messagebox.showerror")
        self.mock_error = self._error_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        for patcher in (self._error_patcher, self._warn_patcher, self._info_patcher, self._askyesno_patcher):
            patcher.stop()

    def test_failed_save_shows_an_error_and_reports_failure(self):
        self.app.current_path = os.path.join(tempfile.gettempdir(), "storyforge-test.json")
        with mock.patch.object(self.app.project, "save", side_effect=PermissionError("read-only")):
            self.assertFalse(self.app.save_project())
        self.mock_error.assert_called_once()
        self.assertIn("read-only", self.mock_error.call_args[0][1])

    def test_failed_save_as_does_not_switch_current_path(self):
        with mock.patch("app.gui.filedialog.asksaveasfilename", return_value="Z:/nope/project.json"), \
                mock.patch.object(self.app.project, "save", side_effect=OSError("no such drive")):
            self.assertFalse(self.app.save_project_as())
        self.assertIsNone(self.app.current_path)

    def test_close_is_aborted_when_save_fails(self):
        self.app.current_path = os.path.join(tempfile.gettempdir(), "storyforge-test.json")
        self.app.plot_box.set("unsaved change")  # F10: only a dirty project asks to save
        with mock.patch("app.gui.messagebox.askyesnocancel", return_value=True), \
                mock.patch.object(self.app.project, "save", side_effect=OSError("disk full")), \
                mock.patch.object(self.app, "destroy") as mock_destroy:
            self.app._on_close()
        mock_destroy.assert_not_called()

    def test_successful_save_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            self.app.current_path = path
            self.assertTrue(self.app.save_project())
            self.assertTrue(os.path.isfile(path))

    def test_autosave_failure_is_reported_once_not_swallowed(self):
        # The autosave is serialized on the Tk thread and written on a worker
        # (run synchronously here).
        with mock.patch("app.gui.save_json_text", side_effect=OSError("denied")), \
                mock.patch("app.gui.threading.Thread", _SynchronousThread), \
                self.assertLogs("app.gui", level="ERROR"):
            self.app._autosave()
            self.app._autosave()
        self.assertEqual(self.mock_warning.call_count, 1)


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestOverLengthChapterDoesNotBlockGeneration(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._askyesno_patcher = mock.patch("app.gui.messagebox.askyesno", return_value=True)
        self._askyesno_patcher.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        self._askyesno_patcher.stop()

    def test_other_chapter_can_still_be_generated(self):
        from app.project import MAX_WORDS_PER_CHAPTER
        calls = []

        class FakeEngine:
            is_loaded = True

            def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None):
                calls.append(chapter_index)
                return "new text"

            def summarize(self, text, max_words=150):
                return "summary"

        self.app.engine = FakeEngine()
        self.app.project.add_chapter("Cap 1")
        self.app.project.add_chapter("Cap 2")
        self.app._render_chapters()
        self.app.chapter_panels[0].content_box.insert("1.0", "word " * (MAX_WORDS_PER_CHAPTER + 5))
        with mock.patch("app.gui.threading.Thread", _SynchronousThread), \
                mock.patch("app.gui.messagebox.showwarning") as mock_warning:
            self.app.chapter_panels[1]._on_generate()
        self.app.update()
        mock_warning.assert_not_called()
        self.assertEqual(calls, [1])


class _RecordingEngine:
    """GUI-level engine double: records calls, and lets a test inspect the
    UI state at the moment the engine is running (see `during`)."""

    is_loaded = True

    def __init__(self, result="Generated chapter text.", summary="A summary.", during=None):
        self.result = result
        self.summary = summary
        self.during = during
        self.generate_calls = []
        self.summarize_calls = []
        self.model_path = None

    def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None, resume_from=None):
        self.generate_calls.append({"index": chapter_index, "resume_from": resume_from})
        if self.during:
            self.during()
        base = resume_from or ""
        return base + self.result if base else self.result

    def summarize(self, text, max_words=150):
        self.summarize_calls.append(text)
        if isinstance(self.summary, Exception):
            raise self.summary
        return self.summary

    def refine_chapter(self, project, chapter_index, instruction):
        if self.during:
            self.during()
        return "REFINED TEXT"


class _GuiTestCase(unittest.TestCase):
    ASKYESNO = True

    def setUp(self):
        _clear_autosave()
        self._patchers = [
            mock.patch("app.gui.messagebox.askyesno", return_value=self.ASKYESNO),
            mock.patch("app.gui.threading.Thread", _SynchronousThread),
        ]
        for p in self._patchers:
            p.start()
        self.app = StoryForgeApp()

    def tearDown(self):
        self.app.destroy()
        for p in reversed(self._patchers):
            p.stop()

    def _chapter(self, title="Cap 1", content=""):
        ch = self.app.project.add_chapter(title, target_words=100)
        ch.content = content
        self.app._render_chapters()
        return self.app.chapter_panels[len(self.app.project.chapters) - 1]


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestUserDataIsolation(_GuiTestCase):
    """T1: the tests must never touch the user's real autosave."""

    def test_autosave_path_is_the_temporary_test_dir(self):
        self.assertTrue(self.app.autosave_path.startswith(_TEST_USER_DATA.name))
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(self.app.autosave_path.startswith(os.path.join(repo_root, "autosave")))

    def test_autosave_writes_only_inside_the_override_dir(self):
        self.app._autosave()
        self.assertTrue(os.path.isfile(self.app.autosave_path))
        _clear_autosave()


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestUnexpectedErrorReporting(_GuiTestCase):
    """R1: Tk callback and worker-thread exceptions are logged and shown."""

    def test_tk_callback_exception_is_logged_and_shown(self):
        # A fresh app (the base fixture doesn't override report_callback_exception).
        with mock.patch("app.gui.messagebox.showerror") as mock_error, \
                self.assertLogs("app.gui", level="ERROR") as logs:
            try:
                raise ValueError("boom in a callback")
            except ValueError:
                self.app.report_callback_exception(*sys.exc_info())
        mock_error.assert_called_once()
        self.assertIn("boom in a callback", mock_error.call_args[0][1])
        self.assertIn("boom in a callback", "\n".join(logs.output))

    def test_errors_raised_by_a_real_after_callback_reach_the_handler(self):
        with mock.patch("app.gui.messagebox.showerror") as mock_error, \
                self.assertLogs("app.gui", level="ERROR"):
            self.app.after(0, lambda: 1 / 0)
            self.app.update()
        mock_error.assert_called_once()
        self.assertIn("ZeroDivisionError", mock_error.call_args[0][1])

    def test_thread_exceptions_are_marshalled_to_the_main_thread(self):
        import types as _types
        try:
            raise RuntimeError("worker died")
        except RuntimeError:
            exc_type, exc, tb = sys.exc_info()
        args = _types.SimpleNamespace(exc_type=exc_type, exc_value=exc, exc_traceback=tb, thread=None)
        with mock.patch("app.gui.messagebox.showerror") as mock_error, \
                self.assertLogs("app.gui", level="ERROR"):
            self.app._thread_excepthook(args)  # what threading.excepthook calls (see gui.run())
            mock_error.assert_not_called()  # shown later, from the Tk main thread
            self.app.update()
        mock_error.assert_called_once()
        self.assertIn("worker died", mock_error.call_args[0][1])

    def test_main_excepthook_logs(self):
        from app.main import _log_uncaught_exception
        with self.assertLogs("storyforge", level="CRITICAL"):
            try:
                raise KeyError("startup")
            except KeyError:
                _log_uncaught_exception(*sys.exc_info())


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestUndoShortcutsAndSingleEditor(_GuiTestCase):
    """F1: undo, keyboard shortcuts, one chapter editor at a time."""

    def test_all_text_boxes_have_undo(self):
        panel = self._chapter()
        self.app._render_outline_panels()
        for box in (panel.content_box, panel.summary_box, self.app.plot_box.textbox,
                    self.app.outline_panels[0].outline_box):
            self.assertTrue(int(str(box.cget("undo"))))

    def test_undo_restores_edited_text_but_not_into_the_loaded_content(self):
        panel = self._chapter(content="Loaded text.")
        panel.content_box.insert("end", " typed")
        panel.content_box.edit_separator()
        panel.content_box.edit_undo()
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), "Loaded text.")
        try:
            panel.content_box.edit_undo()  # nothing left: loading isn't undoable
        except Exception:  # noqa: BLE001 - Tk raises "nothing to undo"
            pass
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), "Loaded text.")

    def test_expand_with_ai_is_undoable(self):
        class FakeEngine:
            is_loaded = True

            def expand_field(self, field_key, text, max_words=400):
                return "EXPANDED"

        self.app.engine = FakeEngine()
        self.app.plot_box.set("a short idea")
        self.app._expand_field(self.app.plot_box, "plot", "Plot", 50_000)
        self.app.update()
        self.assertEqual(self.app.plot_box.get(), "EXPANDED")
        self.app.plot_box.textbox.edit_undo()
        self.assertEqual(self.app.plot_box.get(), "a short idea")

    def test_shortcuts_are_bound_and_menu_shows_accelerators(self):
        for sequence in ("<Control-n>", "<Control-o>", "<Control-s>", "<Control-S>", "<Escape>"):
            self.assertTrue(self.app.bind(sequence), sequence)
        self.assertEqual(self.app.bind_class("Text", "<Control-o>"), "")  # no stray newline on Ctrl+O
        panel = self._chapter()
        self.assertTrue(panel.content_box._textbox.bind("<Control-Return>"))

    def test_ctrl_enter_generates_an_empty_chapter_and_continues_a_written_one(self):
        engine = _RecordingEngine()
        self.app.engine = engine
        panel = self._chapter()
        panel._on_ctrl_enter()
        self.app.update()
        self.assertIsNone(engine.generate_calls[-1]["resume_from"])
        panel._on_ctrl_enter()
        self.app.update()
        self.assertEqual(engine.generate_calls[-1]["resume_from"], "Generated chapter text.")

    def test_escape_cancels_the_running_generation(self):
        panel = self._chapter()
        panel._cancel_flag = {"cancel": False}
        self.app.cancel_running_generation()
        self.assertTrue(panel._cancel_flag["cancel"])

    def test_only_the_selected_chapter_is_shown(self):
        self._chapter("A")
        self._chapter("B")
        self._chapter("C")
        self.app.update()
        shown = [p for p in self.app.chapter_panels if p.winfo_manager()]
        self.assertEqual(shown, [self.app.chapter_panels[self.app.selected_chapter_index]])
        self.app.select_chapter(0)
        self.assertEqual([p.index for p in self.app.chapter_panels if p.winfo_manager()], [0])

    def test_adding_a_chapter_selects_it(self):
        self._chapter("A")
        self.app.add_chapter()
        self.assertEqual(self.app.selected_chapter_index, 1)


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestChapterReadOnlyWhileGenerating(_GuiTestCase):
    """F3: typing into a chapter while the model writes into it was lost."""

    def test_content_box_is_read_only_during_generation_and_editable_after(self):
        panel = self._chapter()
        seen = {}
        self.app.engine = _RecordingEngine(during=lambda: seen.update(
            content=panel.content_box.cget("state"), title=panel.title_entry.cget("state"),
        ))
        panel._on_generate()
        self.app.update()
        self.assertEqual(seen, {"content": "disabled", "title": "disabled"})
        self.assertEqual(panel.content_box.cget("state"), "normal")
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), "Generated chapter text.")

    def test_read_only_during_refine_too(self):
        panel = self._chapter(content="Original.")
        panel.refine_entry.insert(0, "darker")
        seen = {}
        self.app.engine = _RecordingEngine(during=lambda: seen.update(content=panel.content_box.cget("state")))
        panel._on_refine()
        self.app.update()
        self.assertEqual(seen["content"], "disabled")
        self.app.last_preview.accept()
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), "REFINED TEXT")
        self.assertEqual(panel.content_box.cget("state"), "normal")


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestSummaryVisibilityAndStaleness(_GuiTestCase):
    """B2: summaries are visible, editable, marked stale, and regenerated."""

    def test_generated_summary_is_shown_and_fresh(self):
        panel = self._chapter()
        self.app.engine = _RecordingEngine(summary="The hero left.")
        panel._on_generate()
        self.app.update()
        self.assertEqual(panel.summary_box.get("1.0", "end-1c"), "The hero left.")
        self.assertFalse(panel.chapter.summary_is_stale())
        self.assertEqual(panel.summary_state(), "ok")

    def test_editing_the_chapter_marks_the_summary_stale(self):
        panel = self._chapter(content="Text.")
        panel.chapter.set_summary("S")
        self.app._render_chapters()
        panel = self.app.chapter_panels[0]
        panel.content_box.insert("end", " More text typed by hand.")
        panel._on_content_edited()
        self.assertEqual(panel.summary_state(), "stale")
        self.assertIn("desactualizado", panel.summary_status_label.cget("text"))

    def test_refine_and_restore_leave_the_summary_stale(self):
        panel = self._chapter(content="Original.")
        panel.chapter.set_summary("S")
        self.app._render_chapters()
        panel = self.app.chapter_panels[0]
        panel.refine_entry.insert(0, "darker")
        self.app.engine = _RecordingEngine()
        panel._on_refine()
        self.app.update()
        self.app.last_preview.accept()
        self.assertTrue(panel.chapter.summary_is_stale())

    def test_hand_edited_summary_is_saved_as_fresh(self):
        panel = self._chapter(content="Text.")
        panel.summary_box.insert("1.0", "My own summary.")
        self.app._sync_all()
        self.assertEqual(panel.chapter.summary, "My own summary.")
        self.assertFalse(panel.chapter.summary_is_stale())

    def test_summary_failure_is_logged_and_reported_not_swallowed(self):
        panel = self._chapter()
        self.app.engine = _RecordingEngine(summary=RuntimeError("summary exploded"))
        with self.assertLogs("app.gui", level="ERROR") as logs:
            panel._on_generate()
            self.app.update()
        self.assertIn("summary exploded", "\n".join(logs.output))
        self.assertIn("Regenerar resumen", panel.status_label.cget("text"))
        self.assertEqual(panel.chapter.content, "Generated chapter text.")

    def test_regenerate_summary_button(self):
        panel = self._chapter(content="Some text.")
        engine = _RecordingEngine(summary="Fresh summary.")
        self.app.engine = engine
        panel._on_regenerate_summary()
        self.app.update()
        self.assertEqual(engine.summarize_calls, ["Some text."])
        self.assertEqual(panel.chapter.summary, "Fresh summary.")
        self.assertFalse(panel.chapter.summary_is_stale())

    def test_stale_previous_summaries_are_regenerated_before_generating(self):
        first = self._chapter("A", content="Chapter one text.")
        first.chapter.set_summary("old")
        first.chapter.content = "Chapter one text, refined."
        self.app._render_chapters()
        second = self._chapter("B")
        engine = _RecordingEngine(summary="new summary")
        self.app.engine = engine
        second._on_generate()
        self.app.update()
        self.assertEqual(engine.summarize_calls[0], "Chapter one text, refined.")
        self.assertEqual(self.app.project.chapters[0].summary, "new summary")
        self.assertFalse(self.app.project.chapters[0].summary_is_stale())


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestContinueButtons(_GuiTestCase):
    """B5: Continuar / Continuar desde el cursor."""

    def test_continue_resumes_from_the_current_text(self):
        panel = self._chapter(content="Existing prose.")
        engine = _RecordingEngine(result=" And more.")
        self.app.engine = engine
        panel._on_continue()
        self.app.update()
        self.assertEqual(engine.generate_calls[0]["resume_from"], "Existing prose.")
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), "Existing prose. And more.")
        self.assertEqual(panel.chapter.history, ["Existing prose."])

    def test_continue_from_cursor_drops_the_text_after_it(self):
        panel = self._chapter(content="Keep this. Drop this.")
        panel.content_box.mark_set("insert", "1.10")
        engine = _RecordingEngine(result=" New ending.")
        self.app.engine = engine
        panel._on_continue(from_cursor=True)
        self.app.update()
        self.assertEqual(engine.generate_calls[0]["resume_from"], "Keep this.")
        self.assertEqual(panel.chapter.content, "Keep this. New ending.")
        self.assertIn("Keep this. Drop this.", panel.chapter.history)

    def test_continue_on_an_empty_chapter_generates(self):
        panel = self._chapter()
        engine = _RecordingEngine()
        self.app.engine = engine
        panel._on_continue()
        self.app.update()
        self.assertIsNone(engine.generate_calls[0]["resume_from"])


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestChatFormatSetting(_GuiTestCase):
    """B3: the Modelo tab's chat-format choice reaches the engine and is remembered per model."""

    def test_load_passes_the_choice_and_remembers_it(self):
        loads = []

        class FakeEngine:
            is_loaded = False
            model_path = None

            def load(self, path, **kwargs):
                loads.append((path, kwargs))

        self.app.engine = FakeEngine()
        self.app.model_combo.set("some-model.gguf")
        self.app.chat_format_menu.set("ChatML (Qwen, etc.)")
        self.app._load_model()
        self.app.update()
        self.assertEqual(loads[0][1]["chat_format"], "chatml")

        self.app.chat_format_menu.set("Auto (desde el GGUF)")
        self.app._on_model_selected("some-model.gguf")
        self.assertEqual(self.app.chat_format_menu.get(), "ChatML (Qwen, etc.)")
        from app.settings import settings_path
        self.assertTrue(settings_path().startswith(_TEST_USER_DATA.name))


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class TestOutlineWarnings(_GuiTestCase):
    """B4/B7: truncated or unparseable outlines are reported, not applied silently."""

    def _prepare(self, engine):
        self.app.engine = engine
        self.app.plot_box.set("a story")
        self.app.outline_count_entry.delete(0, "end")
        self.app.outline_count_entry.insert(0, "3")

    def test_fewer_chapters_than_requested_is_flagged(self):
        class FakeEngine:
            is_loaded = True
            last_finish_reason = "length"

            def generate_outline(self, project, n):
                return [("A", "a"), ("B", "b")]

        self._prepare(FakeEngine())
        self.app._on_generate_outline()
        self.app.update()
        status = self.app.outline_status.cget("text")
        self.assertIn("incompleto", status)
        self.assertIn("2 de 3", status)

    def test_unparseable_outline_shows_an_error_and_changes_nothing(self):
        from app.prompts import OutlineParseError

        class FakeEngine:
            is_loaded = True

            def generate_outline(self, project, n):
                raise OutlineParseError("bad format", raw_text="Just a paragraph.")

        self._prepare(FakeEngine())
        with mock.patch("app.gui.messagebox.showerror") as mock_error:
            self.app._on_generate_outline()
            self.app.update()
        mock_error.assert_called_once()
        self.assertIn("Just a paragraph.", mock_error.call_args[0][1])
        self.assertEqual(self.app.project.chapters, [])


if __name__ == "__main__":
    unittest.main()
