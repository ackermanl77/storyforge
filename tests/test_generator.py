"""Generador de historias (app/generator.py and its /api/generador routes): the
form validation, the prompt, the history/saved/preset storage, and the service
job that writes a story with a fake engine."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_web_server import FakeEngine, wait_for_job  # noqa: E402

from app import generator  # noqa: E402
from app.web_server import ApiError, StoryForgeService, create_server  # noqa: E402

FORM = {"plot": "A fox crosses the forest.", "genre": "Fantasía", "tone": "Épico", "point_of_view": "Primera persona",
        "purpose": "opening", "format": "screenplay", "length": "medium", "dialogue": 90}


class IsolatedData(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"STORYFORGE_USER_DATA_DIR": self.data.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.data.cleanup)


class TestForm(unittest.TestCase):
    def test_clean_form_trims_fills_defaults_and_rejects_bad_input(self):
        form = generator.clean_form({"plot": "  A plot.  ", "tone": "x" * 400})
        self.assertEqual(form["plot"], "A plot.")
        self.assertEqual(len(form["tone"]), generator.FIELD_LIMITS["tone"])
        self.assertEqual((form["purpose"], form["format"], form["length"], form["dialogue"]),
                         ("complete", "prose", "short", -1))
        for bad in (None, {"plot": ""}, {"plot": "x", "format": "opera"}, {"plot": 5}):
            with self.assertRaises(generator.GeneratorError):
                generator.clean_form(bad)
        self.assertEqual(generator.clean_form({"plot": "x", "dialogue": 500})["dialogue"], -1)
        self.assertEqual(generator.clean_form({"plot": "x", "dialogue": True})["dialogue"], -1)

    def test_dialogue_slider_maps_to_the_story_settings_levels(self):
        self.assertEqual(generator.dialogue_key(-1), "")
        self.assertEqual(generator.dialogue_key(0), "mucha_narracion")
        self.assertEqual(generator.dialogue_key(50), "equilibrado")
        self.assertEqual(generator.dialogue_key(100), "mucho_dialogo")

    def test_the_prompt_carries_every_choice_in_english(self):
        prompt = generator.build_prompt(generator.clean_form(dict(FORM, characters="Pip: a fox.")))
        self.assertIn("the opening of the story", prompt)
        self.assertIn("as a screenplay, about 1500 words", prompt)
        self.assertIn("Genre: fantasy", prompt)
        self.assertIn("Point of view:", prompt)
        self.assertIn("Dialogue:", prompt)
        self.assertIn("CHARACTERS:\nPip: a fox.", prompt)
        self.assertNotIn("SETTING:", prompt)  # empty fields are left out
        self.assertIn("INT. or EXT.", prompt)
        self.assertIn("do not summarize the rest", prompt)

    def test_builtin_presets_are_valid_forms(self):
        for name, preset in generator.BUILTIN_PRESETS.items():
            self.assertEqual(generator.clean_form(preset)["plot"], preset["plot"], name)


class TestStorage(IsolatedData):
    def test_history_saved_entries_and_deletion(self):
        form = generator.clean_form(FORM)
        first = generator.add_to_history(form, "One two three.", 1.0, 7)
        second = generator.add_to_history(form, "Four.", 1.0, None)
        self.assertEqual([e["id"] for e in generator.history()], [second["id"], first["id"]])
        self.assertTrue(generator.set_saved(first["id"], True)["saved"])
        self.assertIsNone(generator.set_saved("0" * 12, True))
        self.assertTrue(generator.delete_entry(second["id"]))
        self.assertFalse(generator.delete_entry(second["id"]))
        self.assertEqual(generator.history()[0]["words"], 3)

    def test_the_history_limit_never_drops_a_saved_story(self):
        form = generator.clean_form(FORM)
        keep = generator.add_to_history(form, "Keep me.", 1.0, None)
        generator.set_saved(keep["id"], True)
        with mock.patch.object(generator, "HISTORY_LIMIT", 3):
            for i in range(5):
                generator.add_to_history(form, f"Story {i}.", 1.0, None)
        items = generator.history()
        self.assertEqual(len(items), 4)
        self.assertIn(keep["id"], [e["id"] for e in items])

    def test_user_presets_are_saved_and_deleted_but_examples_are_fixed(self):
        form = generator.clean_form(FORM)
        self.assertEqual(generator.save_preset("  Mine ", form), "Mine")
        self.assertEqual(generator.presets()["Mine"]["format"], "screenplay")
        with self.assertRaises(generator.GeneratorError):
            generator.save_preset(next(iter(generator.BUILTIN_PRESETS)), form)
        with self.assertRaises(generator.GeneratorError):
            generator.save_preset("  ", form)
        self.assertFalse(generator.delete_preset(next(iter(generator.BUILTIN_PRESETS))))
        self.assertTrue(generator.delete_preset("Mine"))
        self.assertNotIn("Mine", generator.presets())

    def test_options_describe_the_form(self):
        options = generator.options()
        self.assertEqual([o["valor"] for o in options["formatos"]], list(generator.FORMATS))
        self.assertIn("genre", options["sugerencias"])
        self.assertIn(next(iter(generator.BUILTIN_PRESETS)), options["presets"])


class RecordingEngine(FakeEngine):
    def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None, resume_from=None):
        self.chapter = project.chapters[chapter_index]
        return super().generate_chapter(project, chapter_index, progress_callback, cancel_check, resume_from)


class TestService(IsolatedData):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = RecordingEngine()
        self.service = StoryForgeService(self.engine, self.tmp.name)

    def test_a_story_is_written_with_the_form_prompt_and_kept_in_the_history(self):
        snapshot = self.service.start_story(dict(FORM, context="Use {plot} literally."))
        self.assertEqual(snapshot["tipo"], "story")
        job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "ok", job)
        self.assertEqual(job["texto"], "First words. More words follow.")
        self.assertEqual(self.engine.chapter.target_words, 1500)
        # The user's braces are not read as prompt placeholders.
        self.assertIn("{​plot}", self.engine.chapter.custom_prompt)
        entry = generator.history()[0]
        self.assertEqual((entry["text"], entry["form"]["format"], entry["seed"]),
                         ("First words. More words follow.", "screenplay", 7))
        # No project file is written for a generator story.
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_stopping_keeps_what_was_written(self):
        self.engine.release.clear()
        self.service.start_story(FORM)
        self.service.stop()
        self.engine.release.set()
        job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "cancelled")
        self.assertEqual(generator.history()[0]["text"], "First words.")

    def test_invalid_forms_and_a_missing_model_are_refused(self):
        with self.assertRaises(ApiError):
            self.service.start_story({"plot": ""})
        self.engine.is_loaded = False
        with self.assertRaises(ApiError):
            self.service.start_story(FORM)


class TestHttp(IsolatedData):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = create_server(FakeEngine(), self.tmp.name, port=0, host="127.0.0.1", token="k" * 24)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(self.conn.close)

    def request(self, method, path, body=None, token="k" * 24):
        headers = {"Content-Type": "application/json", "X-StoryForge-Token": token}
        self.conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = self.conn.getresponse()
        data = response.read()
        return response.status, json.loads(data) if data and path.startswith("/api/") else data

    def test_the_page_and_its_api(self):
        for path in ("/generador", "/generador.js", "/generador.css"):
            status, _ = self.request("GET", path, token="")
            self.assertEqual(status, 200, path)
        self.assertEqual(self.request("GET", "/api/generador", token="")[0], 401)
        status, options = self.request("GET", "/api/generador")
        self.assertEqual(status, 200)
        self.assertIn("presets", options)

        status, job = self.request("POST", "/api/generador/generar", FORM)
        self.assertEqual((status, job["tipo"]), (200, "story"))
        wait_for_job(self.server.service)
        status, items = self.request("GET", "/api/generador/historial")
        entry_id = items[0]["id"]
        status, entry = self.request("POST", f"/api/generador/historial/{entry_id}/guardar", {"guardado": True})
        self.assertTrue(entry["saved"])
        self.assertEqual(self.request("DELETE", f"/api/generador/historial/{entry_id}")[0], 200)
        self.assertEqual(self.request("DELETE", f"/api/generador/historial/{entry_id}")[0], 404)

        status, result = self.request("POST", "/api/generador/presets", {"nombre": "Mio", "formulario": FORM})
        self.assertEqual((status, result["nombre"]), (200, "Mio"))
        self.assertEqual(self.request("POST", "/api/generador/presets", {"nombre": "x", "formulario": {}})[0], 400)
        status, result = self.request("POST", "/api/generador/presets/borrar", {"nombre": "Mio"})
        self.assertNotIn("Mio", result["presets"])

    def test_generator_flag_opens_the_generator_page(self):
        from app.main import _parse_args
        self.assertTrue(_parse_args(["--generador"]).generador)
        self.assertTrue(self.server.generator_url.endswith("/generador?t=" + "k" * 24))


if __name__ == "__main__":
    unittest.main()
