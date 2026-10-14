"""Story settings (genre, theme, tone, point of view, dialogue balance) and
their presets: app/story_settings.py, the prompts, the project file, the
phone server and the Plot tab."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import story_settings as ss
from app.project import Project
from app.prompts import build_chapter_start_chat, build_writing_style_instruction, render_custom_prompt

BUDGET = dict(max_plot_words=1200, max_characters_words=600, max_setting_words=600,
              max_previous_words=500, max_outline_words=300, max_lore_words=200)


def _project(**settings):
    project = Project(plot="A heist.", characters="Ana.", setting="Madrid.")
    project.add_chapter("Uno", target_words=500)
    for key, value in settings.items():
        setattr(project, key, value)
    return project


class SettingsToPromptTests(unittest.TestCase):
    def test_known_suggestions_become_precise_english_and_free_text_stays(self):
        self.assertEqual(ss.english_value("genre", "ciencia FICCIÓN"), "science fiction")
        self.assertTrue(ss.english_value("point_of_view", "Primera persona").startswith('first person ("I")'))
        self.assertEqual(ss.english_value("tone", "noir con humor negro"), "noir con humor negro")
        self.assertEqual(ss.english_value("theme", "  "), "")

    def test_no_settings_leave_the_prompt_exactly_as_before(self):
        plain = _project()
        self.assertEqual(ss.build_story_settings_block(plain), "")
        self.assertEqual(build_writing_style_instruction(plain), "")
        styled = _project(writing_style="Dialogo")
        self.assertTrue(build_writing_style_instruction(styled).startswith("WRITING STYLE EMPHASIS:"))

    def test_the_chapter_prompt_carries_every_setting(self):
        project = _project(genre="Terror", theme="Venganza", tone="Inquietante",
                           point_of_view="Tercera persona limitada", dialogue_balance="mas_dialogo",
                           writing_style="Descriptiva")
        prompt = build_chapter_start_chat(project, 0, BUDGET)
        text = prompt.system + prompt.user
        self.assertIn("STORY SETTINGS (follow them throughout):", text)
        for expected in ("Genre: horror", "Theme: revenge", "Tone: eerie and unsettling",
                         "Point of view: third person limited", "Keep this point of view consistently",
                         "Dialogue: More dialogue than narration", "WRITING STYLE EMPHASIS:"):
            self.assertIn(expected, text)
        self.assertLess(text.index("STORY SETTINGS"), text.index("WRITING STYLE EMPHASIS"))

    def test_custom_prompts_can_use_the_settings(self):
        project = _project(genre="Romance", point_of_view="Segunda persona")
        project.chapters[0].custom_prompt = "A {genero} story, {género}, told in {punto_de_vista}. Tone: {tono}."
        self.assertEqual(render_custom_prompt(project, 0),
                         'A romance story, romance, told in second person ("you"), present tense. Tone: .')


class ProjectFileTests(unittest.TestCase):
    def test_settings_round_trip_and_bad_values_are_dropped(self):
        project = _project(genre="Fantasía", tone="x" * 500, dialogue_balance="mucho_dialogo")
        loaded = Project.from_dict(project.to_dict())
        self.assertEqual(loaded.genre, "Fantasía")
        self.assertEqual(len(loaded.tone), ss.MAX_SETTING_CHARS)
        self.assertEqual(loaded.dialogue_balance, "mucho_dialogo")
        data = project.to_dict()
        data.update(dialogue_balance="a lot", theme=7)
        loaded = Project.from_dict(data)
        self.assertEqual((loaded.dialogue_balance, loaded.theme), ("", ""))
        old = project.to_dict()
        for key in ss.STORY_SETTING_FIELDS:
            old.pop(key)
        self.assertEqual(Project.from_dict(old).genre, "")  # projects from before the settings


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"STORYFORGE_USER_DATA_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_builtin_presets_are_complete_and_apply_to_a_project(self):
        presets = ss.all_presets()
        self.assertIn("Thriller", presets)
        for name, values in ss.BUILTIN_PRESETS.items():
            self.assertEqual(set(values), set(ss.PRESET_FIELDS), name)
            self.assertIn(values["dialogue_balance"], ss.DIALOGUE_BALANCES)
        project = _project()
        ss.apply_preset(project, presets["Terror"])
        self.assertEqual((project.genre, project.tone, project.writing_style), ("Terror", "Inquietante", "Descriptiva"))

    def test_user_presets_are_saved_replaced_and_deleted(self):
        project = _project(genre="Western", dialogue_balance="equilibrado", writing_style="Narrativa")
        self.assertEqual(ss.save_user_preset("  Mi western  ", ss.preset_from_project(project)), "Mi western")
        self.assertEqual(ss.all_presets()["Mi western"]["genre"], "Western")
        project.genre = "Space western"
        ss.save_user_preset("Mi western", ss.preset_from_project(project))
        self.assertEqual(ss.user_presets()["Mi western"]["genre"], "Space western")
        self.assertFalse(ss.delete_user_preset("Thriller"))  # built in: stays
        self.assertTrue(ss.delete_user_preset("Mi western"))
        self.assertNotIn("Mi western", ss.all_presets())
        with self.assertRaises(ValueError):
            ss.save_user_preset("   ", {})


class PhoneServerTests(unittest.TestCase):
    def setUp(self):
        from tests.test_web_server import FakeEngine
        from app.web_server import StoryForgeService

        self.tmp = tempfile.TemporaryDirectory()
        self.engine = FakeEngine()
        self.service = StoryForgeService(self.engine, self.tmp.name)
        self.service.create_project("Historia")

    def tearDown(self):
        self.engine.release.set()
        self.tmp.cleanup()

    def test_the_settings_are_shown_and_saved_from_the_phone(self):
        from app.web_server import ApiError

        view = self.service.update_project({"genero": "Misterio", "punto_de_vista": "Primera persona",
                                            "dialogo": "mas_narracion"})
        self.assertEqual((view["genero"], view["punto_de_vista"], view["dialogo"]),
                         ("Misterio", "Primera persona", "mas_narracion"))
        self.assertIn("Primera persona", view["sugerencias"]["punto_de_vista"])
        self.assertIn("Thriller", view["presets"])
        self.assertEqual(self.service.project.genre, "Misterio")
        with self.assertRaises(ApiError):
            self.service.update_project({"dialogo": "mucho"})


if __name__ == "__main__":
    unittest.main()
