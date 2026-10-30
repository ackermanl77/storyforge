"""StoryForge en el celular (app/web_server.py): the service logic with a fake
engine, and the HTTP layer (access key, static files, keep-alive) on a real
server bound to a free local port."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import web_server
from app.engine import OperationCancelled
from app.main import _parse_args
from app.project import Project
from app.web_server import ApiError, StoryForgeService, create_server


class FakeEngine:
    def __init__(self):
        self.is_loaded = True
        self.model_path = "C:/models/fake.gguf"
        self.n_ctx = 4096
        self.sampling = None
        self.last_seed = 7
        self.stopped = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.summarized = []
        self.loaded = None

    def load(self, path, chat_format=None, **options):
        self.loaded = (path, options)
        self.model_path = path
        self.is_loaded = True

    def unload(self):
        self.is_loaded = False

    def clear_stop(self):
        self.stopped.clear()

    def request_stop(self):
        self.stopped.set()

    def generate_outline(self, project, num_chapters, cancel_check=None):
        return [(f"Title {i + 1}", f"Beats {i + 1}") for i in range(num_chapters)]

    def generate_chapter(self, project, chapter_index, progress_callback=None, cancel_check=None, resume_from=None):
        text = (resume_from + " " if resume_from else "") + "First words."
        progress_callback(text, 2, 100)
        self.release.wait(5)
        if cancel_check():
            return text
        text += " More words follow."
        progress_callback(text, 5, 100)
        return text

    def summarize(self, text, cancel_check=None):
        self.summarized.append(text)
        return f"summary of {len(text.split())} words"


def wait_for_job(service, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = service.job_snapshot()
        if job and job["estado"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("the job did not finish")


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = FakeEngine()
        self.service = StoryForgeService(self.engine, self.tmp.name)

    def tearDown(self):
        self.engine.release.set()
        self.tmp.cleanup()

    def saved(self):
        return Project.load(os.path.join(self.tmp.name, self.service.project_file))

    def test_projects_are_created_listed_reopened_and_saved_on_every_change(self):
        view = self.service.create_project("Mi historia")
        self.assertEqual(view["archivo"], "Mi_historia.storyforge.json")
        self.assertIs(self.engine.sampling, self.service.project.sampling)
        self.service.update_project({"plot": "A plot.", "estilo": "Dialogo"})
        self.assertEqual(self.saved().plot, "A plot.")
        self.assertEqual(self.saved().writing_style, "Dialogo")
        # A second project with the same name gets its own file.
        self.assertEqual(self.service.create_project("Mi historia")["archivo"], "Mi_historia_2.storyforge.json")
        names = [p["archivo"] for p in self.service.list_projects()]
        self.assertCountEqual(names, ["Mi_historia.storyforge.json", "Mi_historia_2.storyforge.json"])
        self.assertEqual(self.service.open_project("Mi_historia.storyforge.json")["plot"], "A plot.")

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ApiError):
            self.service.project_view()  # no project yet
        self.service.create_project("X")
        for bad in ({"estilo": "Nope"}, {"plot": 5}):
            with self.assertRaises(ApiError):
                self.service.update_project(bad)
        self.service.add_chapter({})
        for bad in ({"objetivo": 0}, {"objetivo": "100"}, {"proposito": "Nope"}):
            with self.assertRaises(ApiError):
                self.service.update_chapter(0, bad)
        with self.assertRaises(ApiError):
            self.service.chapter_view(5)
        # Only plain project file names inside the projects folder can be opened.
        for name in ("../secret.storyforge.json", "notes.txt", "missing.storyforge.json"):
            with self.assertRaises(ApiError):
                self.service.open_project(name)

    def test_editing_a_chapters_text_keeps_the_previous_version(self):
        self.service.create_project("X")
        self.service.add_chapter({"titulo": "One", "objetivo": 1500})
        self.service.update_chapter(0, {"texto": "Draft one."})
        self.service.update_chapter(0, {"texto": "Draft two."})
        chapter = self.saved().chapters[0]
        self.assertEqual((chapter.title, chapter.target_words, chapter.content), ("One", 1500, "Draft two."))
        self.assertEqual(chapter.history[-1], "Draft one.")
        self.assertEqual(chapter.history_meta[-1]["source"], "phone-edit")

    def test_a_chapters_custom_prompt_is_saved_and_listed(self):
        self.service.create_project("X")
        self.service.add_chapter({})
        view = self.service.update_chapter(0, {"prompt": "Write {plot}"})
        self.assertEqual(view["prompt"], "Write {plot}")
        self.assertEqual(self.saved().chapters[0].custom_prompt, "Write {plot}")
        project = self.service.project_view()
        self.assertTrue(project["capitulos"][0]["prompt_propio"])
        self.assertIn("{anterior}", project["plantilla_prompt"])

    def test_outline_fills_existing_chapters_and_adds_the_rest(self):
        self.service.create_project("X")
        self.service.add_chapter({"titulo": "Old"})
        self.service.update_chapter(0, {"texto": "Kept prose."})
        self.service.start_outline(3)
        job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "ok")
        chapters = self.saved().chapters
        self.assertEqual([c.title for c in chapters], ["Title 1", "Title 2", "Title 3"])
        self.assertEqual(chapters[0].content, "Kept prose.")
        self.assertEqual(chapters[2].outline, "Beats 3")

    def test_generating_a_chapter_streams_text_then_saves_it_with_a_summary(self):
        self.service.create_project("X")
        self.service.add_chapter({})
        self.service.add_chapter({})
        self.service.update_chapter(0, {"texto": "Earlier chapter text."})  # no summary yet: stale context
        self.engine.release.clear()
        self.service.start_chapter(1)
        deadline = time.time() + 5
        while "First words." not in (self.service.job_snapshot() or {}).get("texto", "") and time.time() < deadline:
            time.sleep(0.01)
        partial = self.service.job_snapshot()
        self.assertEqual(partial["estado"], "running")
        # Edits are refused while the model works.
        with self.assertRaises(ApiError) as ctx:
            self.service.update_project({"plot": "x"})
        self.assertEqual(ctx.exception.status, 409)
        self.engine.release.set()
        job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "ok")
        self.assertIn("7", job["mensaje"])  # the seed
        # Only the new text after `desde` comes back.
        self.assertEqual(self.service.job_snapshot(since=len("First words."))["texto"], " More words follow.")
        project = self.saved()
        self.assertEqual(project.chapters[1].content, "First words. More words follow.")
        self.assertEqual(project.chapters[1].summary, "summary of 5 words")
        self.assertFalse(project.chapters[1].summary_is_stale())
        # The previous chapter's missing summary was generated first.
        self.assertEqual(self.engine.summarized[0], "Earlier chapter text.")
        self.assertEqual(project.chapters[0].summary, "summary of 3 words")

    def test_job_admission_and_project_mutation_share_one_lock(self):
        self.service.create_project("X")
        self.service.add_chapter({})
        self.engine.release.clear()
        original_require_idle = self.service._require_idle
        mutation_checked = threading.Event()
        allow_mutation = threading.Event()
        generation_checked = threading.Event()
        mutation_done = threading.Event()
        generation_done = threading.Event()
        errors = []

        def gate_idle_check():
            if threading.current_thread().name == "project-edit" and not mutation_checked.is_set():
                original_require_idle()
                mutation_checked.set()
                if not allow_mutation.wait(5):
                    errors.append(AssertionError("the mutation barrier timed out"))
                return
            if threading.current_thread().name == "job-start":
                generation_checked.set()
            original_require_idle()

        def edit_project():
            try:
                self.service.update_project({"plot": "Changed before generation."})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                mutation_done.set()

        def start_generation():
            try:
                self.service.start_chapter(0)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                generation_done.set()

        with mock.patch.object(self.service, "_require_idle", side_effect=gate_idle_check):
            mutation = threading.Thread(target=edit_project, name="project-edit")
            mutation.start()
            self.assertTrue(mutation_checked.wait(5))
            generation = threading.Thread(target=start_generation, name="job-start")
            generation.start()
            self.assertFalse(generation_checked.wait(0.1))
            self.assertIsNone(self.service.job)

            allow_mutation.set()
            self.assertTrue(mutation_done.wait(5))
            self.assertTrue(generation_done.wait(5))
            mutation.join(5)
            generation.join(5)

        self.assertEqual(errors, [])
        self.assertEqual(self.saved().plot, "Changed before generation.")
        self.assertEqual(self.service.job_snapshot()["estado"], "running")
        self.engine.release.set()
        self.assertEqual(wait_for_job(self.service)["estado"], "ok")

    def test_continue_resumes_from_the_saved_text(self):
        self.service.create_project("X")
        self.service.add_chapter({})
        self.service.update_chapter(0, {"texto": "Start."})
        self.service.start_chapter(0, resume=True)
        wait_for_job(self.service)
        chapter = self.saved().chapters[0]
        self.assertEqual(chapter.content, "Start. First words. More words follow.")
        self.assertEqual(chapter.history_meta[-1]["source"], "continue")

    def test_stop_keeps_the_partial_chapter_and_reports_cancelled(self):
        self.service.create_project("X")
        self.service.add_chapter({})
        self.engine.release.clear()
        self.service.start_chapter(0)
        time.sleep(0.05)
        self.service.stop()
        self.assertTrue(self.engine.stopped.is_set())
        self.engine.release.set()
        job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "cancelled")
        self.assertEqual(self.saved().chapters[0].content, "First words.")

    def test_generation_needs_a_loaded_model(self):
        self.service.create_project("X")
        self.service.add_chapter({})
        self.engine.is_loaded = False
        with self.assertRaises(ApiError) as ctx:
            self.service.start_chapter(0)
        self.assertEqual(ctx.exception.status, 409)

    def test_engine_errors_end_the_job_with_a_message(self):
        self.service.create_project("X")
        self.service.add_chapter({})
        with mock.patch.object(self.engine, "generate_chapter", side_effect=OperationCancelled()):
            self.service.start_chapter(0)
            self.assertEqual(wait_for_job(self.service)["estado"], "cancelled")
        with mock.patch.object(self.engine, "generate_chapter", side_effect=RuntimeError("boom")):
            self.service.start_chapter(0)
            job = wait_for_job(self.service)
        self.assertEqual(job["estado"], "error")
        self.assertIn("boom", job["mensaje"])

    def test_only_models_from_the_models_folder_can_be_loaded(self):
        models = os.path.join(self.tmp.name, "models")
        os.makedirs(models)
        model = os.path.join(models, "tiny.gguf")
        with open(model, "wb") as fh:
            fh.write(b"GGUF")
        self.service.create_project("X")
        with mock.patch.object(web_server, "models_dirs", return_value=[models]), \
                mock.patch.object(web_server, "list_model_entries",
                                  return_value=[mock.Mock(path=model, label="tiny.gguf", complete=True)]):
            with self.assertRaises(ApiError):
                self.service.load_model(os.path.join(self.tmp.name, "elsewhere.gguf"))
            self.service.load_model(model)
            self.assertEqual(wait_for_job(self.service)["estado"], "ok")
        self.assertEqual(self.engine.loaded[0], model)
        self.assertEqual(self.saved().context_size, 4096)

    def test_every_export_format_produces_a_file(self):
        self.service.create_project("Mi historia")
        self.service.add_chapter({"titulo": "One"})
        self.service.update_chapter(0, {"texto": "Some *prose* here."})
        for fmt in ("txt", "md", "epub", "docx"):
            data, filename, mime = self.service.export(fmt)
            self.assertTrue(data, fmt)
            self.assertEqual(filename, f"Mi_historia.{fmt}")
        with self.assertRaises(ApiError):
            self.service.export("pdf")


class TestHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = create_server(FakeEngine(), self.tmp.name, port=0, host="127.0.0.1", token="k" * 24)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, conn, method, path, body=None, token="k" * 24):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-StoryForge-Token"] = token
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = conn.getresponse()
        return response.status, response.read()

    def test_the_api_needs_the_access_key_and_keep_alive_survives_a_refusal(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        status, _ = self.request(conn, "POST", "/api/proyectos", {"nombre": "x"}, token="wrong")
        self.assertEqual(status, 401)
        # Same connection: the refused request's body must not leak into this one.
        status, body = self.request(conn, "POST", "/api/proyectos", {"nombre": "Hola"})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["nombre"], "Hola")
        status, body = self.request(conn, "GET", "/api/estado")
        self.assertEqual(json.loads(body)["proyecto"]["nombre"], "Hola")
        status, body = self.request(conn, "GET", "/api/capitulo/3")
        self.assertEqual(status, 404)  # the project has no chapter 4
        conn.close()

    def test_static_pages_and_the_connect_page(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        status, body = self.request(conn, "GET", "/", token="")
        self.assertEqual(status, 200)
        self.assertIn(b"StoryForge", body)
        for path in ("/app.js", "/style.css", "/manifest.webmanifest", "/icon.svg", "/conectar"):
            status, _ = self.request(conn, "GET", path, token="")
            self.assertEqual(status, 200, path)
        status, body = self.request(conn, "GET", "/conectar", token="")
        self.assertEqual(status, 200)
        self.assertIn(b"HTTP sin cifrar", body)
        self.assertIn(b"no expongas el puerto a Internet", body)
        self.assertIn(b"solo acepta conexiones desde esta PC", body)
        self.assertIn(b"--servidor --lan", body)
        status, _ = self.request(conn, "GET", "/../app/web_server.py", token="")
        self.assertEqual(status, 404)
        # The connect page's data (with the key) answers the PC itself only.
        status, body = self.request(conn, "GET", "/api/conexion", token="")
        self.assertEqual(status, 200)
        connection = json.loads(body)
        self.assertIn("t=" + "k" * 24, connection["url"])
        self.assertFalse(connection["lan_enabled"])
        conn.close()

    def test_export_downloads_with_a_file_name(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.request(conn, "POST", "/api/proyectos", {"nombre": "Libro"})
        conn.request("GET", "/api/exportar/txt", headers={"X-StoryForge-Token": "k" * 24})
        response = conn.getresponse()
        response.read()
        self.assertEqual(response.status, 200)
        self.assertIn('filename="Libro.txt"', response.getheader("Content-Disposition"))
        conn.close()

    def test_server_binds_to_localhost_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = create_server(FakeEngine(), tmp, port=0, token="k" * 24)
            try:
                self.assertEqual(server.server_address[0], "127.0.0.1")
                self.assertIsNone(server.phone_url)
                self.assertIn("127.0.0.1", server.local_url)
            finally:
                server.server_close()
                server.service.stop()

    def test_server_binds_to_lan_only_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = create_server(FakeEngine(), tmp, port=0, host=web_server.LAN_HOST, token="k" * 24)
            try:
                self.assertEqual(server.server_address[0], web_server.LAN_HOST)
                self.assertIsNotNone(server.phone_url)
                self.assertIn("t=" + "k" * 24, server.phone_url)
            finally:
                server.server_close()
                server.service.stop()


class TestMisc(unittest.TestCase):
    def test_command_line(self):
        args = _parse_args(["--servidor", "--puerto", "9000", "--sin-navegador", "unrelated.txt"])
        self.assertTrue(args.servidor)
        self.assertEqual(args.puerto, 9000)
        self.assertTrue(args.sin_navegador)
        self.assertFalse(_parse_args([]).servidor)
        self.assertFalse(_parse_args(["--servidor"]).lan)
        self.assertTrue(_parse_args(["--servidor", "--lan"]).lan)
        with self.assertRaises(SystemExit):
            _parse_args(["--lan"])

    def test_phone_server_startup_message_warns_about_plain_http(self):
        self.assertIn("HTTP no cifra el tráfico", web_server.S.WEB_SERVIDOR_LISTO)
        self.assertIn("No abras el puerto a Internet", web_server.S.WEB_SERVIDOR_LISTO)
        self.assertIn("HTTP no cifra el tráfico", web_server.S.WEB_SERVIDOR_LOCAL_LISTO)
        self.assertIn("--lan", web_server.S.WEB_SERVIDOR_LOCAL_LISTO)

    def test_cli_passes_lan_opt_in_to_server_startup(self):
        from app.main import main

        old_excepthook = sys.excepthook
        try:
            with mock.patch("app.main._configure_logging"), mock.patch(
                "app.web_server.serve", return_value=0
            ) as serve:
                self.assertEqual(main(["--servidor", "--lan", "--sin-navegador"]), 0)
            self.assertTrue(serve.call_args.kwargs["lan"])
        finally:
            sys.excepthook = old_excepthook

    def test_server_startup_chooses_loopback_or_lan_bind(self):
        with tempfile.TemporaryDirectory() as tmp:
            for lan, expected_host in ((False, web_server.DEFAULT_HOST), (True, web_server.LAN_HOST)):
                server = mock.Mock()
                server.service.projects_dir = tmp
                server.serve_forever.side_effect = KeyboardInterrupt
                with mock.patch("app.engine.LocalStoryEngine"), mock.patch.object(
                    web_server, "create_server", return_value=server
                ) as create, mock.patch.object(web_server, "_show"):
                    self.assertEqual(web_server.serve(projects_dir=tmp, open_browser=False, lan=lan), 0)
                self.assertEqual(create.call_args.kwargs["host"], expected_host)

    def test_models_are_also_found_next_to_the_last_loaded_model_and_in_the_models_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            last_dir = os.path.join(tmp, "last")
            option_dir = os.path.join(tmp, "option")
            os.makedirs(last_dir)
            os.makedirs(option_dir)
            with mock.patch.object(web_server, "get_last_model", return_value=os.path.join(last_dir, "m.gguf")):
                web_server.remember_models_dir(option_dir)
                dirs = web_server.models_dirs()
        self.assertIn(os.path.abspath(last_dir), dirs)
        self.assertIn(os.path.abspath(option_dir), dirs)
        self.assertEqual(len(dirs), len({os.path.normcase(d) for d in dirs}))

    def test_the_access_key_is_generated_once_and_kept(self):
        first = web_server.access_token()
        self.assertGreaterEqual(len(first), 16)
        self.assertEqual(web_server.access_token(), first)


if __name__ == "__main__":
    unittest.main()
