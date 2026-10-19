"""Lorebook progressions (F17), the story matrix (F18), project notes / snippets (F19) and prompt
components (F20)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import generator, prompt_components, prompts  # noqa: E402
from app.project import (  # noqa: E402
    MAX_SNIPPET_PROMPT_WORDS, Chapter, LoreEntry, Project, Snippet, format_progressions, parse_progressions,
)
from app.story_matrix import build_story_matrix, character_names  # noqa: E402


def _project():
    project = Project(name="Salt", plot="A keeper and a queen.", characters="Mara Vell: the keeper.\nTomas - her brother.")
    project.chapters = [Chapter(title=f"Ch {n}", outline=f"Outline {n}.") for n in range(1, 4)]
    return project


class TestProgressions(unittest.TestCase):
    def test_text_for_chapter_and_round_trip(self):
        entry = LoreEntry(name="Ana", keywords="Ana", text="A girl.",
                          progressions=parse_progressions("== Desde el capítulo 3 ==\nThe queen.\n\n== desde el capitulo 2 ==\nA princess."))
        self.assertEqual([entry.text_for_chapter(n) for n in (1, 2, 3, 9, None)],
                         ["A girl.", "A princess.", "The queen.", "The queen.", "A girl."])
        self.assertEqual(parse_progressions(format_progressions(entry.progressions)), entry.progressions)
        restored = LoreEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.progressions, entry.progressions)
        self.assertNotIn("progressions", LoreEntry(name="x").to_dict())  # old files stay identical
        bad = LoreEntry.from_dict({"name": "x", "progressions": [{"from_chapter": 0, "text": "no"}, {"from_chapter": "2"}, "x",
                                                                 {"from_chapter": 4, "text": "ok"}]})
        self.assertEqual(bad.progressions, [{"from_chapter": 4, "text": "ok"}])

    def test_the_chapter_prompt_uses_the_version_for_that_chapter(self):
        project = _project()
        project.lore_entries = [LoreEntry(name="Ana", keywords="Outline", text="A girl.",
                                          progressions=[{"from_chapter": 3, "text": "The crowned queen."}])]
        early = prompts.build_chapter_system_prompt(project, 0)
        late = prompts.build_chapter_system_prompt(project, 2)
        self.assertIn("Ana: A girl.", early)
        self.assertIn("Ana: The crowned queen.", late)
        self.assertNotIn("crowned", early)

    def test_a_long_progression_is_a_validation_error(self):
        project = _project()
        project.lore_entries = [LoreEntry(name="Ana", progressions=[{"from_chapter": 2, "text": "word " * 600}])]
        self.assertTrue(any("capítulo 2" in error for error in project.validate_inputs()))


class TestSnippets(unittest.TestCase):
    def test_only_marked_notes_reach_the_prompt_within_the_budget(self):
        project = _project()
        baseline = prompts.build_chapter_system_prompt(project, 1)
        project.snippets = [Snippet("Rule", "Magic always costs a memory.", True), Snippet("Private", "Kill Tomas?", False)]
        prompt = prompts.build_chapter_system_prompt(project, 1)
        self.assertIn("AUTHOR'S NOTES ON THIS STORY", prompt)
        self.assertIn("- Rule: Magic always costs a memory.", prompt)
        self.assertNotIn("Kill Tomas", prompt)
        project.snippets[0].in_prompt = False
        self.assertEqual(prompts.build_chapter_system_prompt(project, 1), baseline)  # nothing marked: unchanged
        project.snippets = [Snippet("Long", "word " * 1000, True), Snippet("Next", "never fits", True)]
        text = prompts.snippets_text(project)
        self.assertLessEqual(len(text.split()), MAX_SNIPPET_PROMPT_WORDS + 3)
        self.assertNotIn("never fits", text)

    def test_round_trip_validation_and_custom_prompt_placeholder(self):
        project = _project()
        project.add_snippet("Rule", "Keep it cold.", in_prompt=True)
        restored = Project.from_dict(project.to_dict())
        self.assertEqual([(s.title, s.text, s.in_prompt) for s in restored.snippets], [("Rule", "Keep it cold.", True)])
        self.assertEqual(Project.from_dict({k: v for k, v in project.to_dict().items() if k != "snippets"}).snippets, [])
        project.chapters[0].custom_prompt = "Notes:\n{notas}\nWrite."
        self.assertIn("- Rule: Keep it cold.", prompts.render_custom_prompt(project, 0))
        project.snippets[0].text = "word " * 2100
        self.assertTrue(any("Rule" in error for error in project.validate_inputs()))


class TestPromptComponents(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {"STORYFORGE_USER_DATA_DIR": self.folder})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_expand_rename_and_delete(self):
        name = prompt_components.save_component("noir style", "Short sentences. Rain. {plot}")
        self.assertEqual(name, "noir_style")
        self.assertEqual(prompt_components.expand_components("Use {@noir_style} and {@missing}."),
                         "Use Short sentences. Rain. {plot} and {@missing}.")
        with self.assertRaises(ValueError):
            prompt_components.save_component("bad name!", "x")
        with self.assertRaises(ValueError):
            prompt_components.save_component("empty", "  ")
        self.assertTrue(prompt_components.delete_component("noir_style"))
        self.assertEqual(prompt_components.load_components(), {})

    def test_custom_prompts_and_the_generator_expand_components(self):
        prompt_components.save_component("tono", "Keep a dry, ironic tone.")
        project = _project()
        project.chapters[0].custom_prompt = "{@tono}\nPlot: {plot}"
        self.assertEqual(prompts.render_custom_prompt(project, 0), "Keep a dry, ironic tone.\nPlot: A keeper and a queen.")
        form = generator.clean_form({"plot": "A fox crosses the forest. {@tono}", "purpose": "complete", "format": "prose", "length": "short"})
        self.assertIn("Keep a dry, ironic tone.", generator.build_prompt(form))


class TestStoryMatrix(unittest.TestCase):
    def test_counts_per_chapter_planned_rows_gaps_and_csv(self):
        project = _project()
        project.lore_entries = [LoreEntry(name="The Lighthouse", keywords="lamp, tower"),
                                LoreEntry(name="Unused", enabled=False)]
        project.chapters[0].content = "Mara climbed the tower. Mara Vell lit the lamp. Tomas slept."
        project.chapters[1].content = "Tomas left. The Lighthouse stood dark."
        project.chapters[2].outline = "Mara returns."
        matrix = build_story_matrix(project)
        self.assertEqual([c.label for c in matrix.columns], ["Mara Vell", "Tomas", "The Lighthouse"])
        self.assertEqual(matrix.rows[0].counts, [2, 1, 2])  # "Mara Vell" counted once, not as Mara + Mara Vell
        self.assertEqual(matrix.rows[1].counts, [0, 1, 1])
        self.assertTrue(matrix.rows[2].planned)
        self.assertEqual(matrix.rows[2].counts, [1, 0, 0])
        self.assertEqual(matrix.gaps(minimum_chapters=1), {"Mara Vell": 1, "Tomas": 1, "The Lighthouse": 1})
        self.assertEqual(matrix.gaps(), {})  # nobody is missing 3 chapters in a row
        csv_text = matrix.to_csv()
        self.assertIn("Capítulo,Mara Vell,Tomas,The Lighthouse", csv_text)
        self.assertIn("(esquema)", csv_text)

    def test_character_names_from_the_characters_text(self):
        text = "**Elena Ruiz**: captain.\n- Bram — the cook\nIgor, a spy\nshe likes tea: lowercase is not a name"
        self.assertEqual(character_names(text), ["Elena Ruiz", "Bram", "Igor"])


if __name__ == "__main__":
    unittest.main()
