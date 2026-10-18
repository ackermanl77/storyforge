"""Modelo en un servidor compatible con OpenAI (B14), contra un servidor falso en un hilo.
(Probado a mano con el servidor real de llama-cpp-python y daredevil-8b: un capitulo de 1500
palabras salio con 1554, transmitido, en 32 s.)"""

import _thread
import json
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.engine import LocalStoryEngine
from app.project import Project, count_words
from app.server_backend import ServerError, ServerLlama

TEMPLATE = "{% for m in messages %}<|start_header_id|>{{ m.role }}<|end_header_id|>\n\n{{ m.content }}<|eot_id|>{% endfor %}"


class FakeServer:
    """/v1/models, /props, /tokenize and /v1/completions (streamed or not)."""

    def __init__(self, strict=False, api_key="", props=True, words=120):
        self.payloads = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, data):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self):
                return not api_key or self.headers.get("Authorization") == f"Bearer {api_key}"

            def do_GET(self):
                if not self._authorized():
                    return self._send(401, {"error": "bad key"})
                if self.path == "/v1/models":
                    return self._send(200, {"data": [{"id": "fake-70b"}, {"id": "other"}]})
                if self.path == "/props" and props:
                    return self._send(200, {"chat_template": TEMPLATE, "default_generation_settings": {"n_ctx": 16384}})
                self._send(404, {})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/tokenize":
                    return self._send(200, {"tokens": list(range(len(payload["content"].split())))})
                if self.path != "/v1/completions":
                    return self._send(404, {})
                owner.payloads.append(payload)
                if strict and "min_p" in payload:
                    return self._send(400, {"error": "unknown parameter min_p"})
                # Different words in every reply: identical ones would read as the model copying the
                # chapter's ending back (app/output_guard.py drops that).
                n = len(owner.payloads)
                pieces = [f" w{n}x{i}" for i in range(words)] + ["."]
                text = "".join(pieces)
                if not payload.get("stream"):
                    return self._send(200, {"choices": [{"text": text, "finish_reason": "stop"}], "usage": {"completion_tokens": words}})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in pieces:
                    self.wfile.write(f"data: {json.dumps({'choices': [{'text': piece, 'finish_reason': None}]})}\n\n".encode())
                self.wfile.write(f"data: {json.dumps({'choices': [{'text': '', 'finish_reason': 'stop'}]})}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)  # one request at a time: no per-request threads
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        # _thread, not threading.Thread: the GUI tests patch threading.Thread to run synchronously,
        # which would run serve_forever() in the test's own thread (and this module may be imported
        # only after that patch is active).
        _thread.start_new_thread(self.httpd.serve_forever, ())

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestServerBackend(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)

    def test_connecting_reads_the_model_context_and_chat_template(self):
        llm = ServerLlama(self.server.url)
        self.assertEqual((llm.model, llm.n_ctx(), llm.root), ("fake-70b", 16384, self.server.url[:-3]))
        self.assertEqual(llm.metadata["tokenizer.chat_template"], TEMPLATE)
        self.assertEqual(llm.tokenize("tres palabras aqui".encode()), [0, 1, 2])
        self.assertEqual(ServerLlama(self.server.url, model="other", n_ctx=4096).n_ctx(), 4096)

    def test_a_chapter_streams_through_the_server_with_the_rendered_prompt(self):
        engine = LocalStoryEngine()
        engine.connect_server(self.server.url, chat_format="llama3")
        self.assertTrue(engine.is_server and engine.is_loaded)
        project = Project(plot="A hero's journey.", characters="Hero", setting="A village")
        project.add_chapter("One", target_words=200)
        shown = []
        text = engine.generate_chapter(project, 0, progress_callback=lambda t, w, total: shown.append(w))
        self.assertGreaterEqual(count_words(text), 160)
        self.assertTrue(shown)  # streamed
        first = self.server.payloads[0]
        self.assertTrue(first["stream"] and first["model"] == "fake-70b")
        self.assertIn("<|start_header_id|>assistant<|end_header_id|>", first["prompt"])  # StoryForge's own rendering
        self.assertIn("min_p", first)  # llama.cpp-style sampling goes along
        self.assertNotIn("logits_processor", first)

    def test_a_strict_server_gets_only_openais_own_parameters(self):
        strict = FakeServer(strict=True)
        self.addCleanup(strict.close)
        llm = ServerLlama(strict.url)
        result = llm("Hello", max_tokens=5, temperature=0.8, min_p=0.05, top_k=40)
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertIn("min_p", strict.payloads[0])
        self.assertNotIn("min_p", strict.payloads[1])  # retried without the extras
        self.assertEqual(strict.payloads[1]["temperature"], 0.8)

    def test_keys_and_unreachable_servers_give_clear_errors(self):
        keyed = FakeServer(api_key="s3cret", props=False)
        self.addCleanup(keyed.close)
        with self.assertRaisesRegex(ServerError, "clave"):
            ServerLlama(keyed.url)
        self.assertEqual(ServerLlama(keyed.url, api_key="s3cret").model, "fake-70b")
        with self.assertRaisesRegex(ServerError, "No se pudo conectar"):
            ServerLlama("http://127.0.0.1:9/v1")
        with self.assertRaisesRegex(ServerError, "http"):
            ServerLlama("localhost:1234")

    def test_tokens_are_estimated_when_the_server_cannot_count_them(self):
        bare = FakeServer(props=False)
        self.addCleanup(bare.close)
        llm = ServerLlama(bare.url)
        llm._tokenize_with = lambda *a: (_ for _ in ()).throw(ValueError("no endpoint"))
        self.assertEqual(len(llm.tokenize(b"x" * 36)), 10)
        self.assertEqual(llm._tokenize_style, "estimate")


if __name__ == "__main__":
    unittest.main()
