"""Generador de historias, second round (2026-10-18), modelled on toolsaday.com's story generator
(analysed with REA: its form config `story/story-generator` in chunk 9348.*.js): purpose-dependent
fields, an exact word count, several chapters, output language, asking for changes, ratings and
turning a result into a StoryForge project."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_generator import IsolatedData, RecordingEngine  # noqa: E402
from test_web_server import FakeEngine, wait_for_job  # noqa: E402

from app import generator  # noqa: E402
from app.project import Project  # noqa: E402
from app.web_server import ApiError, StoryForgeService, create_server  # noqa: E402

BASE = {"plot": "A fox crosses the forest.", "purpose": "complete", "format": "prose", "length": "short"}


class TestFormRound2(unittest.TestCase):
    def test_purpose_fields_are_kept_only_for_their_purpose(self):
        chapter = generator.clean_form(dict(BASE, purpose="chapter", chapter_plot="She finds the den.",
                                            previous_summary="She left home.", climax_plot="ignored"))
        self.assertEqual((chapter["chapter_plot"], chapter["previous_summary"], chapter["climax_plot"]),
                         ("She finds the den.", "She left home.", ""))
        ending = generator.clean_form({"purpose": "ending", "ending_plot": "She returns home.", "format": "prose"})
        self.assertEqual(ending["ending_plot"], "She returns home.")  # a purpose field can replace the plot
        with self.assertRaises(generator.GeneratorError):
            generator.clean_form({"purpose": "complete", "chapter_plot": "x"})

    def test_words_chapters_and_language(self):
        form = generator.clean_form(dict(BASE, words=2400, chapters=3, language="Spanish"))
        self.assertEqual((form["words"], form["chapters"], form["language"]), (2400, 3, "Spanish"))
        self.assertEqual(generator.chapter_words(form), 800)
        self.assertEqual(generator.clean_form(dict(BASE, words=10))["words"], 50)
        self.assertEqual(generator.clean_form(dict(BASE, words=99999))["words"], 6000)
        self.assertEqual(generator.clean_form(dict(BASE, purpose="opening", chapters=4))["chapters"], 1)
        self.assertEqual(generator.clean_form(dict(BASE, chapters=50))["chapters"], 10)
        self.assertEqual(generator.clean_form(BASE)["words"], 800)  # an old form: from its length
        with self.assertRaises(generator.GeneratorError):
            generator.clean_form(dict(BASE, language="Klingon"))

    def test_prompts_for_chapters_purpose_fields_and_revisions(self):
        form = generator.clean_form(dict(BASE, words=1500, chapters=3, language="Spanish"))
        first = generator.build_prompt(form, chapter=0)
        self.assertIn("Write chapter 1 of 3 now", first)
        self.assertIn("about 500 words long, in Spanish", first)
        self.assertIn("This is not the last chapter", first)
        last = generator.build_prompt(form, chapter=2, story_so_far="Chapter 1: she left.")
        self.assertIn("This is the final chapter", last)
        self.assertIn("THE STORY SO FAR", last)
        self.assertIn("Chapter 1: she left.", last)
        climax = generator.build_prompt(generator.clean_form(dict(BASE, purpose="climax", main_summary="So far…",
                                                                  climax_plot="The duel.")))
        self.assertIn("SUMMARY OF THE STORY SO FAR:\nSo far…", climax)
        self.assertIn("WHAT HAPPENS IN THE CLIMAX:\nThe duel.", climax)
        revision = generator.build_revision_prompt(form, "Once upon a time.", "Make it darker.")
        self.assertIn("THE TEXT:\nOnce upon a time.", revision)
        self.assertIn("THE AUTHOR'S REQUEST:\nMake it darker.", revision)
        self.assertIn("Write in Spanish", revision)
        with self.assertRaises(generator.GeneratorError):
            generator.clean_request("   ")

    def test_a_result_becomes_a_project_with_one_chapter_per_heading(self):
        entry = {"title": "t", "text": "Chapter 1\n\nShe left.\n\nChapter 2\n\nShe came back.",
                 "form": generator.clean_form(dict(BASE, genre="Fantasía", characters="Pip", dialogue=90))}
        project = generator.project_from_entry(entry)
        self.assertEqual([(c.title, c.content) for c in project.chapters],
                         [("Capítulo 1", "She left."), ("Capítulo 2", "She came back.")])
        self.assertEqual((project.plot, project.characters, project.genre), (BASE["plot"], "Pip", "Fantasía"))
        self.assertTrue(project.dialogue_balance)
        single = generator.project_from_entry(dict(entry, text="Just one story."))
        self.assertEqual([c.content for c in single.chapters], ["Just one story."])

    def test_options_describe_the_new_controls(self):
        options = generator.options()
        self.assertEqual(options["palabras"], {"min": 50, "max": 6000})
        self.assertEqual(options["capitulos_max"], 10)
        self.assertIn({"valor": "Spanish", "etiqueta": "Español"}, options["idiomas"])
        self.assertEqual([f["campo"] for f in options["campos_proposito"]["chapter"]], ["chapter_plot", "previous_summary"])


class ChapterEngine(RecordingEngine):
    """Records every chapter prompt and summary call."""

    def __init__(self):
        super().__init__()
        self.prompts = []
        self.summaries = []

    def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None, resume_from=None):
        self.prompts.append(project.chapters[chapter_index].custom_prompt)
        return super().generate_chapter(project, chapter_index, progress_callback, cancel_check, resume_from)

    def summarize(self, text, max_words=150, cancel_check=None):
        self.summaries.append(text)
        return f"summary {len(self.summaries)}"


class TestServiceRound2(IsolatedData):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = ChapterEngine()
        self.service = StoryForgeService(self.engine, self.tmp.name)

    def test_a_multi_chapter_story_carries_the_summaries_forward(self):
        self.service.start_story(dict(BASE, words=1500, chapters=3))
        job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "ok", job)
        self.assertEqual(len(self.engine.prompts), 3)
        self.assertIn("chapter 1 of 3", self.engine.prompts[0])
        self.assertIn("Chapter 1: summary 1", self.engine.prompts[1])
        self.assertIn("Chapter 2: summary 2", self.engine.prompts[2])
        self.assertEqual(len(self.engine.summaries), 2)  # not after the last chapter
        text = generator.history()[0]["text"]
        self.assertTrue(text.startswith("Chapter 1\n\n") and "\n\nChapter 3\n\n" in text)

    def test_asking_for_changes_makes_a_linked_revision(self):
        self.service.start_story(BASE)
        wait_for_job(self.service)
        original = generator.history()[0]
        self.service.start_story_revision(original["id"], "Make it darker.")
        job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "ok", job)
        revision = generator.history()[0]
        self.assertEqual((revision["parent"], revision["request"]), (original["id"], "Make it darker."))
        self.assertTrue(revision["title"].startswith("↳ Make it darker."))
        self.assertIn("THE AUTHOR'S REQUEST:\nMake it darker.", self.engine.prompts[-1])
        with self.assertRaises(ApiError):
            self.service.start_story_revision(original["id"], "")
        with self.assertRaises(ApiError):
            self.service.start_story_revision("0" * 12, "x")

    def test_ratings_and_creating_a_project(self):
        self.service.start_story(BASE)
        wait_for_job(self.service)
        entry_id = generator.history()[0]["id"]
        self.assertEqual(generator.set_rating(entry_id, "like")["rating"], "like")
        self.assertEqual(generator.set_rating(entry_id, "")["rating"], "")
        with self.assertRaises(generator.GeneratorError):
            generator.set_rating(entry_id, "love")
        result = self.service.story_to_project(entry_id)
        path = os.path.join(self.tmp.name, result["archivo"])
        self.assertTrue(os.path.exists(path))
        self.assertEqual(Project.load(path).chapters[0].content, generator.history()[0]["text"])
        second = self.service.story_to_project(entry_id)
        self.assertNotEqual(second["archivo"], result["archivo"])  # never overwrites


class TestHttpRound2(IsolatedData):
    def test_the_new_routes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        server = create_server(FakeEngine(), tmp.name, port=0, host="127.0.0.1", token="k" * 24)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        self.addCleanup(conn.close)

        def request(method, path, body=None):
            conn.request(method, path, body=None if body is None else json.dumps(body),
                         headers={"Content-Type": "application/json", "X-StoryForge-Token": "k" * 24})
            response = conn.getresponse()
            return response.status, json.loads(response.read() or b"{}")

        request("POST", "/api/generador/generar", dict(BASE, words=600, language="Spanish"))
        wait_for_job(server.service)
        entry_id = request("GET", "/api/generador/historial")[1][0]["id"]
        self.assertEqual(request("POST", f"/api/generador/historial/{entry_id}/valorar", {"valor": "dislike"})[1]["rating"],
                         "dislike")
        self.assertEqual(request("POST", f"/api/generador/historial/{entry_id}/valorar", {"valor": "x"})[0], 400)
        status, project = request("POST", f"/api/generador/historial/{entry_id}/proyecto")
        self.assertEqual(status, 200)
        self.assertTrue(project["archivo"].endswith(".storyforge.json"))
        status, job = request("POST", f"/api/generador/historial/{entry_id}/revisar", {"pedido": "Shorter."})
        self.assertEqual((status, job["tipo"]), (200, "story"))
        wait_for_job(server.service)
        self.assertEqual(request("GET", "/api/generador/historial")[1][0]["request"], "Shorter.")


if __name__ == "__main__":
    unittest.main()
