"""
GUI regressions for the P2 round (real CTk window, no mainloop, no simulated
input: handlers are called directly, after() callbacks flushed with update()).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Everything the app writes goes to a temp dir (conftest.py sets the same
# variable for pytest; this covers `python -m unittest`).
_TEST_USER_DATA = tempfile.TemporaryDirectory(prefix="storyforge-test-p2-")
if not os.environ.get("STORYFORGE_USER_DATA_DIR"):
    os.environ["STORYFORGE_USER_DATA_DIR"] = _TEST_USER_DATA.name


def _user_data():
    """The override is read on every call (tests/test_gui.py restores it in its
    tearDownModule), but it must always be a temp dir, never real user data."""
    current = os.environ["STORYFORGE_USER_DATA_DIR"]
    assert os.path.abspath(current).startswith(os.path.abspath(tempfile.gettempdir())), current
    return current

GUI_AVAILABLE = True
_SKIP_REASON = ""
try:
    import tkinter as _tk

    _probe = _tk.Tk()
    _probe.destroy()
    from app.engine import GenerationStats
    from app.gui import StoryForgeApp, default_autosave_path
    from app.project import Project
    from app.sampling import PRESET_CUSTOM, PRESET_PRECISE
    from app.ui_dialogs import find_in_project, word_diff
    from app.ui_status import describe_context, describe_stats
except Exception as _exc:  # pragma: no cover - environment dependent
    GUI_AVAILABLE = False
    _SKIP_REASON = f"GUI dependencies not available: {_exc}"


class _SynchronousThread:
    """Runs the worker immediately on the calling thread (see tests/test_gui.py)."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def _clear_autosave():
    path = default_autosave_path()
    assert path.startswith(_user_data()), path  # never the user's real autosave
    for p in (path, path + ".bak"):
        try:
            os.remove(p)
        except OSError:
            pass


class FakeEngine:
    is_loaded = True
    model_path = None

    def __init__(self):
        self.results = iter(["First take.", "Second take.", "Third take."])
        self.stop_calls = 0
        self.last_seed = 7
        self.stats = GenerationStats(operation="x")

    def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None, resume_from=None):
        return next(self.results)

    def summarize(self, text, max_words=150, cancel_check=None):
        return "summary"

    def refine_chapter(self, project, chapter_index, instruction, cancel_check=None, progress_callback=None):
        return "Refined text."

    def rewrite_span(self, project, chapter_index, before, selection, after, mode="rewrite", instruction="",
                     cancel_check=None):
        self.span = (before, selection, after, mode)
        return "NEW BIT"

    def complete_outline(self, project, n, existing, cancel_check=None):
        self.existing = existing
        return [("Third", "c"), ("Fourth", "d")]

    def generate_outline(self, project, n, cancel_check=None):
        return [("First", "a"), ("Second", "b")]

    last_finish_reason = "length"

    def request_stop(self):
        self.stop_calls += 1

    def clear_stop(self):
        pass


@unittest.skipUnless(GUI_AVAILABLE, _SKIP_REASON)
class _Base(unittest.TestCase):
    def setUp(self):
        _clear_autosave()
        self._patchers = [
            mock.patch("app.gui.messagebox.askyesno", return_value=True),
            mock.patch("app.gui.messagebox.showinfo"),
            mock.patch("app.gui.messagebox.showwarning"),
            mock.patch("app.gui.threading.Thread", _SynchronousThread),
        ]
        for p in self._patchers:
            p.start()
        self.app = StoryForgeApp()
        self.engine = FakeEngine()
        self.app.engine = self.engine

    def tearDown(self):
        self.app.destroy()
        for p in reversed(self._patchers):
            p.stop()

    def _chapter(self, content=""):
        ch = self.app.project.add_chapter("Cap", target_words=100)
        ch.content = content
        self.app._render_chapters()
        return self.app.chapter_panels[-1]


class TestRefinePreviewF4(_Base):
    def test_discard_keeps_the_chapter_and_history_untouched(self):
        panel = self._chapter("Original.")
        panel.refine_entry.insert(0, "darker")
        panel._on_refine()
        self.app.update()
        self.app.last_preview.discard()
        self.assertEqual(panel.chapter.content, "Original.")
        self.assertEqual(panel.chapter.history, [])

    def test_accept_and_continue_labels_history(self):
        panel = self._chapter("Original.")
        panel.refine_entry.insert(0, "darker")
        panel._on_refine()
        self.app.update()
        self.app.last_preview.accept_and_continue()
        self.assertEqual(panel.chapter.content, "Refined text.")
        self.assertEqual(panel.chapter.history_entries()[0]["source"], "refine: darker")
        self.assertEqual(panel.refine_entry.get(), "")

    def test_word_diff(self):
        ops = word_diff("the old cat", "the new cat")
        self.assertIn(("delete", "old"), ops)
        self.assertIn(("insert", "new"), ops)


class TestSelectionRewriteF7(_Base):
    def test_rewrites_only_the_selection_after_accepting(self):
        panel = self._chapter("Keep this. Change me. Keep end.")
        panel.content_box.tag_add("sel", "1.11", "1.21")
        panel.rewrite_selection("shorten")
        self.app.update()
        self.assertEqual(self.engine.span[1], "Change me.")
        self.assertEqual(self.engine.span[3], "shorten")
        self.app.last_preview.accept()
        self.assertEqual(panel.chapter.content, "Keep this. NEW BIT Keep end.")
        self.assertTrue(panel.chapter.history_entries()[-1]["source"].startswith("rewrite"))

    def test_author_note_syncs(self):
        panel = self._chapter()
        panel.author_note_entry.insert(0, "Ana is wounded.")
        self.app.project_note_entry.insert(0, "Grim tone.")
        self.app._sync_all()
        self.assertEqual(panel.chapter.author_note, "Ana is wounded.")
        self.assertEqual(self.app.project.author_note, "Grim tone.")


    def test_custom_prompt_syncs_and_marks_its_button(self):
        panel = self._chapter()
        self.assertEqual(panel.custom_prompt_btn.cget("text"), "Prompt propio")
        panel._toggle_custom_prompt()
        panel._insert_prompt_template()
        panel._refresh_custom_prompt_btn()
        self.assertEqual(panel.custom_prompt_btn.cget("text"), "Prompt propio ●")
        self.app._sync_all()
        self.assertTrue(panel.chapter.custom_prompt.startswith("Write chapter {capítulo}"))
        panel.custom_prompt_box.delete("1.0", "end")
        self.app._sync_all()
        self.assertEqual(panel.chapter.custom_prompt, "")

class TestRetryAlternatives(_Base):
    def test_retry_adds_alternatives_and_cycles(self):
        panel = self._chapter()
        panel._on_generate()
        self.app.update()
        self.assertEqual(panel.retry_btn.cget("state"), "normal")
        panel._on_retry()
        self.app.update()
        self.assertEqual(panel.alternatives, ["First take.", "Second take."])
        self.assertEqual(panel.chapter.content, "Second take.")
        panel._cycle_alternative(-1)
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), "First take.")
        self.assertEqual(panel.chapter.content, "First take.")
        self.assertIn("1/2", panel.alt_label.cget("text"))


class TestRetryLastSection(_Base):
    def test_retry_section_keeps_the_text_before_the_last_section(self):
        panel = self._chapter()
        calls = []

        def generate_chapter(project, chapter_index, progress_callback=None, cancel_check=None, resume_from=None):
            calls.append(resume_from)
            if resume_from is None:
                self.engine.last_section_start = len("Part one. ")
                return "Part one. Part two."
            self.engine.last_section_start = len(resume_from.rstrip())
            return resume_from.rstrip() + " Another ending."

        self.engine.generate_chapter = generate_chapter
        self.assertEqual(panel.retry_section_btn.cget("state"), "disabled")
        panel._on_generate()
        self.app.update()
        self.assertEqual(panel.retry_section_btn.cget("state"), "normal")
        panel._on_retry_section()
        self.app.update()
        self.assertEqual(calls, [None, "Part one."])  # handed over like Continuar: trailing space trimmed
        self.assertEqual(panel.chapter.content, "Part one. Another ending.")
        self.assertEqual(panel.alternatives, ["Part one. Part two.", "Part one. Another ending."])
        self.assertEqual(panel.chapter.history_entries()[-1]["source"], "retry-section")
        # Whole-run Retry still starts from the original point (scratch), not from the prefix.
        panel._on_retry()
        self.app.update()
        self.assertIsNone(calls[-1])
        # Another alternative on screen: the offset belongs to the newest result only.
        panel._cycle_alternative(-1)
        self.assertEqual(panel.retry_section_btn.cget("state"), "disabled")


class TestStorySettings(_Base):
    def test_plot_tab_settings_presets_and_sync(self):
        app = self.app
        app.story_setting_boxes["genre"].set("Western")
        app.story_setting_boxes["point_of_view"].set("Primera persona")
        app.dialogue_menu.set("Más diálogo")
        app._sync_all()
        self.assertEqual((app.project.genre, app.project.point_of_view, app.project.dialogue_balance),
                         ("Western", "Primera persona", "mas_dialogo"))
        self.assertTrue(app.apply_selected_preset("Terror"))
        self.assertEqual(app.story_setting_boxes["tone"].get(), "Inquietante")
        self.assertEqual(app.preset_menu.get(), "Terror")
        self.assertEqual(app.writing_style_menu.get(), "Descriptiva")
        app._sync_all()
        self.assertEqual((app.project.genre, app.project.writing_style), ("Terror", "Descriptiva"))
        self.assertEqual(app.save_story_preset("Mi terror"), "Mi terror")
        self.assertEqual(app.preset_menu.get(), "Mi terror")
        self.assertTrue(app.delete_story_preset())
        self.assertNotIn("Mi terror", app.preset_menu.cget("values"))
        # Opening another project shows its own settings.
        other = Project(genre="Romance")
        app.project = other
        app._load_into_ui()
        self.assertEqual(app.story_setting_boxes["genre"].get(), "Romance")
        self.assertEqual(app.dialogue_menu.get(), "(Sin indicar)")


class TestFindReplaceF5(_Base):
    def test_chapter_replace_all_pushes_history(self):
        panel = self._chapter("Ana met Ana.")
        panel.show_find_bar()
        panel.find_entry.insert(0, "ana")
        panel.replace_entry.insert(0, "Elena")
        self.assertEqual(panel.highlight_matches(), 2)
        self.assertEqual(panel.replace_all(), 2)
        self.assertEqual(panel.chapter.content, "Elena met Elena.")
        self.assertEqual(panel.chapter.history, ["Ana met Ana."])

    def test_project_search_and_replace(self):
        self.app.plot_box.set("Ana's quest.")
        panel = self._chapter("Ana walks.")
        self.app._sync_all()
        hits = find_in_project(self.app.project, "Ana", whole_word=True)
        self.assertEqual({h.field for h in hits}, {"plot", "chapter"})
        self.assertEqual(self.app.replace_in_project("Ana", "Elena", whole_word=True), 2)
        self.assertEqual(self.app.project.plot, "Elena's quest.")
        self.assertEqual(self.app.chapter_panels[0].content_box.get("1.0", "end-1c"), "Elena walks.")
        self.assertEqual(self.app.project.chapters[0].history, ["Ana walks."])
        self.app.jump_to_search_hit(find_in_project(self.app.project, "walks")[0], "walks")
        self.assertIsNotNone(panel)

    def test_word_totals_and_sidebar_show_progress(self):
        self._chapter("one two three")
        self.app._render_chapter_sidebar()
        self.assertIn("3 palabras en 1", self.app.status_bar.words_label.cget("text"))


class TestDirtyAndTitleF10(_Base):
    def test_title_marks_unsaved_changes_and_save_clears_it(self):
        self.assertFalse(self.app.is_dirty())
        self.app.story_title_entry.insert(0, "Mi novela")
        self.assertTrue(self.app.is_dirty())
        self.assertIn("Mi novela", self.app.title())
        self.assertTrue(self.app.title().endswith("•"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.storyforge.json")
            self.app.current_path = path
            self.assertTrue(self.app.save_project())
            self.assertFalse(self.app.title().endswith("•"))
            self.assertIn("p.storyforge.json", self.app.title())
            self.assertEqual(Project.load(path).name, "Mi novela")

    def test_close_without_changes_does_not_ask(self):
        with mock.patch("app.gui.messagebox.askyesnocancel") as ask, \
                mock.patch.object(self.app, "destroy") as destroy:
            self.app._on_close()
        ask.assert_not_called()
        destroy.assert_called_once()

    def test_idle_autosave_when_dirty(self):
        self.app.plot_box.set("typed by hand")
        self.app._last_autosave = 0
        self.app._autosave_tick()
        self.assertTrue(os.path.isfile(self.app.autosave_path))
        self.assertTrue(self.app.autosave_path.startswith(_user_data()))
        _clear_autosave()

    def test_older_autosave_never_overwrites_newer(self):
        self.app._autosave_written_gen = 5
        self.app._autosave_gen = 3  # a stale write finishing late
        self.app._autosave()  # gen 4 <= 5: skipped
        self.assertFalse(os.path.isfile(self.app.autosave_path))


class TestOpenBackupB11(_Base):
    def test_corrupt_project_offers_the_bak(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            Project(name="Backup copy").save(path)
            Project(name="Backup copy").save(path)  # creates p.json.bak
            with open(path, "w", encoding="utf-8") as f:
                f.write("{broken")
            self.assertTrue(self.app.open_project_path(path))
        self.assertEqual(self.app.project.name, "Backup copy")
        self.assertIsNone(self.app.current_path)


class TestOutlineCompletionB4(_Base):
    def test_complete_missing_chapters(self):
        self.app.plot_box.set("a story")
        self.app.outline_count_entry.delete(0, "end")
        self.app.outline_count_entry.insert(0, "4")
        self.app._on_generate_outline()
        self.app.update()
        self.assertEqual(self.app.complete_outline_btn.cget("state"), "normal")
        self.app._on_complete_outline()
        self.app.update()
        self.assertEqual(self.engine.existing, [("First", "a"), ("Second", "b")])
        self.assertEqual([c.title for c in self.app.project.chapters], ["First", "Second", "Third", "Fourth"])
        self.assertEqual(self.app.complete_outline_btn.cget("state"), "disabled")


class TestLorebookOptionsB8F11(_Base):
    def test_options_sync_and_panels_are_reused_when_filtering(self):
        self.app.project.add_lore_entry(name="Elena", keywords="Elena")
        self.app.project.add_lore_entry(name="Forest", keywords="woods")
        self.app._render_lore_entries()
        elena = self.app.lore_panels[0]
        elena.constant_var.set(True)
        elena.enabled_var.set(False)
        elena.priority_entry.delete(0, "end")
        elena.priority_entry.insert(0, "5")
        self.app.lore_search_entry.insert(0, "wood")
        self.app._render_lore_entries()
        self.assertEqual([p.entry.name for p in self.app.lore_panels], ["Forest"])
        self.app.lore_search_entry.delete(0, "end")
        self.app._render_lore_entries()
        self.assertIs(self.app.lore_panels[0], elena)  # reused, not rebuilt
        entry = self.app.project.lore_entries[0]
        self.assertEqual((entry.constant, entry.enabled, entry.priority), (True, False, 5))

    def test_match_reason_is_shown(self):
        entry = self.app.project.add_lore_entry(name="Elena", keywords="Elena")
        self.app.project.add_chapter("C", 50, outline="Elena arrives.")
        self.app._render_chapters()
        self.app._record_lore_matches(0)
        self.assertIn(id(entry), self.app.last_lore_match_ids)
        self.assertIn('"Elena"', self.app.lore_panels[0].badge_label.cget("text"))


class TestStatusBarAndStopF2B9(_Base):
    def test_describe_stats(self):
        stats = GenerationStats(operation="Capítulo 1", generated_tokens=100, decode_seconds=4.0,
                                words_written=300, target_words=1000, prompt_tokens=1000,
                                max_tokens=1000, n_ctx=8192, budget_level=2, seed=3)
        text = describe_stats(stats, 65)
        for piece in ("Capítulo 1", "1:05", "25.0 tok/s", "300/1,000", "ETA", "semilla 3"):
            self.assertIn(piece, text)
        self.assertIn("nivel 2/3", describe_context(stats))

    def test_stop_button_reaches_the_engine_only_while_running(self):
        self.app.stop_current_task()
        self.assertEqual(self.engine.stop_calls, 0)
        self.app.task_runner.running_label = "x"
        self.app.stop_current_task()
        self.assertEqual(self.engine.stop_calls, 1)
        self.assertTrue(self.app.task_runner.cancel_requested)

    def test_show_last_prompt(self):
        self.engine.stats = GenerationStats(operation="Esquema", prompt_text="THE PROMPT", n_ctx=10)
        with mock.patch("app.gui.TextViewerDialog") as viewer:
            self.app.show_last_prompt()
        self.assertEqual(viewer.call_args[0][2], "THE PROMPT")


class TestModelTabB10P1B6(_Base):
    def test_per_model_options_are_restored_on_selection(self):
        from app import settings
        settings.set_model_settings(os.path.join("x", "m.gguf"), {"n_gpu_layers": 12, "kv_cache_type": "q8_0",
                                                                 "flash_attn": True, "n_batch": 2048})
        self.app._on_model_selected("m.gguf")
        self.assertEqual(self.app.n_gpu_layers_entry.get(), "12")
        self.assertEqual(self.app.kv_cache_menu.get(), "q8_0")
        self.assertEqual(self.app.n_batch_entry.get(), "2048")
        options = self.app._read_load_options()
        self.assertEqual((options["kv_cache_type"], options["flash_attn"]), ("q8_0", True))

    def test_quantized_kv_without_flash_attention_is_rejected(self):
        self.app.kv_cache_menu.set("q4_0")
        self.app.flash_attn_var.set(False)
        self.assertIsNone(self.app._read_load_options())

    def test_sampling_panel_is_saved_with_the_project(self):
        self.app.sampling_preset_menu.set(PRESET_PRECISE)
        self.app.seed_entry.insert(0, "123")
        self.app._sync_all()
        self.assertEqual((self.app.project.sampling.preset, self.app.project.sampling.seed), (PRESET_PRECISE, 123))
        self.app.sampling_entries["temperature"].delete(0, "end")
        self.app.sampling_entries["temperature"].insert(0, "1.4")
        self.app.sampling_preset_menu.set(PRESET_CUSTOM)
        self.app._sync_all()
        self.assertEqual(self.app.project.sampling.prose().temperature, 1.4)

    def test_missing_project_model_is_reported(self):
        self.app.project.model_path = "gone.gguf"
        self.app._restore_project_model()
        self.assertIn("gone.gguf", self.app.model_status.cget("text"))


class TestExportMenu(_Base):
    def test_epub_and_markdown_exports(self):
        self._chapter("Hello *world*.")
        with tempfile.TemporaryDirectory() as tmp:
            for method, name in (("export_epub_file", "s.epub"), ("export_markdown_file", "s.md")):
                path = os.path.join(tmp, name)
                with mock.patch("app.gui.filedialog.asksaveasfilename", return_value=path):
                    getattr(self.app, method)()
                self.assertTrue(os.path.getsize(path) > 0)


class TestFocusModeF1(_Base):
    def test_focus_mode_hides_sidebar_and_panels_extras(self):
        panel = self._chapter("x")
        self.app.update()
        self.app.toggle_focus_mode()
        self.app.update()
        self.assertTrue(self.app.focus_mode)
        self.assertEqual(self.app.tabview.get(), "Capítulos")
        self.assertFalse(panel.refine_row.winfo_manager())
        self.app.toggle_focus_mode()
        self.app.update()
        self.assertTrue(panel.refine_row.winfo_manager())


if __name__ == "__main__":
    unittest.main()


class TestHistoryLimitSetting(_Base):
    """Project.history_limit tiene un control en la pestana Plot (antes solo en el archivo)."""

    def test_the_menu_sets_and_shows_the_project_limit(self):
        self.app.history_limit_menu.set("5")
        self.app._sync_all()
        self.assertEqual(self.app.project.history_limit, 5)
        panel = self._chapter("v0")
        for i in range(1, 8):
            panel.chapter.content = f"v{i - 1}"
            self.app.project.push_chapter_history(panel.chapter, source="regenerar")
        self.assertEqual(len(panel.chapter.history), 5)

    def test_a_limit_from_the_file_outside_the_list_is_shown(self):
        self.app.project.history_limit = 37
        self.app._load_project_meta_into_ui()
        self.assertEqual(self.app.history_limit_menu.get(), "37")
        self.app._sync_all()
        self.assertEqual(self.app.project.history_limit, 37)


class TestSavedAlternatives(_Base):
    def test_a_reopened_chapter_can_still_cycle_its_alternatives(self):
        ch = self.app.project.add_chapter("Cap", target_words=100)
        ch.content = "segunda"
        ch.set_alternatives(["primera", "segunda", "tercera"], 1)
        self.app._render_chapters()
        panel = self.app.chapter_panels[-1]
        self.assertEqual(panel.alt_label.cget("text"), "2/3")
        self.assertEqual(panel.next_alt_btn.cget("state"), "normal")
        panel._cycle_alternative(1)
        self.assertEqual(ch.content, "tercera")
        self.assertEqual(ch.alt_index, 2)  # saved with the project
        panel.content_box.insert("end", " editada")
        panel._on_content_edited()  # a hand edit drops them
        self.assertEqual(ch.alternatives, [])
