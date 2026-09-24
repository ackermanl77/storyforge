import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import LocalStoryEngine, ModelNotLoadedError
from app.project import Project
from app.prompts import build_story_outline_overview, parse_outline_response


SAMPLE_OUTLINE_RESPONSE = """\
Chapter 1: The Arrival
Mara reaches the old harbor town and senses something is wrong. She meets
the innkeeper, who warns her not to go near the lighthouse at night.

Chapter 2: Old Secrets
Mara investigates the lighthouse and finds a hidden journal. She realizes
her grandmother once lived here.

Chapter 3: The Storm
A storm traps Mara in town. She confronts the innkeeper about what he knows.
"""


class FakeLlama:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = 0

    def __call__(self, prompt, max_tokens=0, **kwargs):
        self.calls += 1
        return {"choices": [{"text": self.response_text}]}


class TestParseOutlineResponse(unittest.TestCase):
    def test_parses_well_formatted_response(self):
        result = parse_outline_response(SAMPLE_OUTLINE_RESPONSE, expected_chapters=3)
        self.assertEqual(len(result), 3)
        titles = [t for t, _ in result]
        self.assertEqual(titles, ["The Arrival", "Old Secrets", "The Storm"])
        self.assertIn("innkeeper", result[0][1])
        self.assertIn("journal", result[1][1])

    def test_truncates_to_expected_chapters(self):
        result = parse_outline_response(SAMPLE_OUTLINE_RESPONSE, expected_chapters=2)
        self.assertEqual(len(result), 2)

    def test_tolerates_period_instead_of_colon(self):
        text = "Chapter 1. Beginnings\nSomething happens.\n\nChapter 2. The End\nIt ends."
        result = parse_outline_response(text, expected_chapters=2)
        self.assertEqual(result[0][0], "Beginnings")
        self.assertEqual(result[1][0], "The End")

    def test_falls_back_to_single_chapter_when_unformatted(self):
        text = "This model just wrote a paragraph without following instructions."
        result = parse_outline_response(text, expected_chapters=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "Chapter 1")

    def test_empty_response_returns_empty_list(self):
        self.assertEqual(parse_outline_response("   ", expected_chapters=5), [])


class TestStoryOutlineOverview(unittest.TestCase):
    def test_lists_chapter_titles_in_order(self):
        p = Project()
        p.add_chapter("The Arrival")
        p.add_chapter("Old Secrets")
        overview = build_story_outline_overview(p)
        self.assertIn("1. The Arrival", overview)
        self.assertIn("2. Old Secrets", overview)

    def test_empty_when_no_chapters(self):
        p = Project()
        self.assertEqual(build_story_outline_overview(p), "")


class TestGenerateOutline(unittest.TestCase):
    def test_returns_parsed_chapters(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama(SAMPLE_OUTLINE_RESPONSE)
        project = Project(plot="A mystery in a harbor town.", characters="Mara", setting="A coastal town")
        result = engine.generate_outline(project, num_chapters=3)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], "The Arrival")

    def test_default_chapter_stop_does_not_cut_the_outline_after_chapter_one(self):
        # With the prose default stop ("\n\nChapter"), a stop-honoring model
        # halts right where "Chapter 2:" begins -- the outline had 1 chapter.
        stops = []

        def stop_honoring_llama(prompt, max_tokens=0, stop=None, **kwargs):
            stops.append(stop)
            text = SAMPLE_OUTLINE_RESPONSE
            cut = min((text.find(s) for s in (stop or []) if s in text), default=-1)
            return {"choices": [{"text": text[:cut] if cut >= 0 else text}]}

        engine = LocalStoryEngine()
        engine._llm = stop_honoring_llama
        project = Project(plot="A mystery in a harbor town.", characters="Mara", setting="A coastal town")
        result = engine.generate_outline(project, num_chapters=3)
        self.assertEqual([t for t, _ in result], ["The Arrival", "Old Secrets", "The Storm"])
        self.assertNotIn("\n\nChapter", stops[0])

    def test_without_model_raises(self):
        engine = LocalStoryEngine()
        project = Project()
        with self.assertRaises(ModelNotLoadedError):
            engine.generate_outline(project, num_chapters=3)

    def test_clamps_num_chapters_to_max(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama(SAMPLE_OUTLINE_RESPONSE)
        project = Project(plot="A story.", characters="Someone", setting="Somewhere")
        # no debe explotar ni pedir un numero de capitulos fuera de rango
        result = engine.generate_outline(project, num_chapters=999)
        self.assertLessEqual(len(result), 10)


if __name__ == "__main__":
    unittest.main()
