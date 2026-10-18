"""Alternativas en una palabra (F15): the engine's top next words, the server's logprobs and the editor's
menu. With daredevil-8b on the GPU (2026-10-18) "She knelt beside him and ___" gave turned 25 %,
shook 13 %, felt 10 %, gently 9 %, rolled 7 %... in 1.25 s."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import numpy as np

from app.engine import LocalStoryEngine, ModelNotLoadedError, WordAlternative
from app.server_backend import ServerLlama, _top_logprobs
from tests.test_generation_quality import LLAMA3_SPECIALS, ChatFakeLlama, _chapter_project

VOCAB = {10: " turned", 11: " sh", 12: " felt", 13: " Turned", 14: "—", 3: "<|eot_id|>"}
LOGITS = {10: 3.0, 11: 2.5, 12: 2.0, 13: 1.0, 14: 0.5, 3: 4.0}  # the end of turn is the likeliest


class AltLlama(ChatFakeLlama):
    """Next-token logits through the logits processor; greedy completions for whole words."""

    def __init__(self):
        super().__init__(lambda p, i: "", specials=LLAMA3_SPECIALS)
        self.completions = []

    def detokenize(self, tokens, special=False):
        return VOCAB.get(tokens[0], "").encode("utf-8")

    def __call__(self, prompt, max_tokens=0, stop=None, stream=False, logits_processor=None, **kwargs):
        if logits_processor:
            scores = np.full(64, -50.0, dtype=np.float32)
            for token_id, logit in LOGITS.items():
                scores[token_id] = logit
            for processor in logits_processor:
                scores = processor([1, 2, 3], scores)
            return {"choices": [{"text": "x", "finish_reason": "length"}]}
        self.completions.append((prompt[-12:], max_tokens, kwargs.get("temperature")))
        following = {" sh": "ook his shoulder", " turned": " him over", " felt": " for a pulse"}
        for token, text in following.items():
            if prompt.endswith(token):
                return {"choices": [{"text": text, "finish_reason": "length"}]}
        return {"choices": [{"text": "", "finish_reason": "stop"}]}


class EngineTests(unittest.TestCase):
    def test_top_tokens_become_whole_words_without_the_end_of_turn(self):
        engine = LocalStoryEngine()
        engine._llm = AltLlama()
        project = _chapter_project()
        alts = engine.word_alternatives(project, 0, "She knelt beside him and ", top_k=4)
        words = [a.word for a in alts]
        self.assertEqual(words[:3], [" turned", " shook", " felt"])  # " sh" completed to " shook"
        self.assertNotIn("<|eot_id|>", words)
        # " Turned" is the same word: its probability is added to " turned"
        self.assertEqual(sum(1 for w in words if w.strip().lower() == "turned"), 1)
        probs = {a.word: a.probability for a in alts}
        p = np.exp(np.array([3.0, 2.5, 2.0, 1.0, 0.5, 4.0]) - 4.0)
        p /= p.sum() + 58 * np.exp(-54.0)
        self.assertAlmostEqual(probs[" turned"], p[0] + p[3], places=4)
        self.assertTrue(all(isinstance(a, WordAlternative) for a in alts))
        # greedy, a few tokens, from the prompt plus the alternative's first token
        self.assertTrue(all(t == 0.0 and n == 6 for _end, n, t in engine._llm.completions))

    def test_it_needs_a_model(self):
        with self.assertRaises(ModelNotLoadedError):
            LocalStoryEngine().word_alternatives(_chapter_project(), 0, "text ")


class ServerTests(unittest.TestCase):
    def test_logprob_shapes(self):
        openai = {"choices": [{"logprobs": {"top_logprobs": [{" a": -0.1, " b": -2.0}]}}]}
        self.assertAlmostEqual(dict(_top_logprobs(openai))[" a"], np.exp(-0.1))
        chat_style = {"choices": [{"logprobs": {"content": [{"top_logprobs": [{"token": " c", "logprob": -0.5}]}]}}]}
        self.assertEqual(_top_logprobs(chat_style)[0][0], " c")
        llama_server = {"completion_probabilities": [{"probs": [{"tok_str": " d", "prob": 0.4}]}]}
        self.assertEqual(_top_logprobs(llama_server), [(" d", 0.4)])
        self.assertEqual(_top_logprobs({}), [])

    def test_top_tokens_asks_the_server_for_logprobs(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "m"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append(payload)
                body = json.dumps({"choices": [{"text": " a", "logprobs": {
                    "top_logprobs": [{" a": -0.2, " b": -1.5, " c": -3.0}]}}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            llm = ServerLlama(f"http://127.0.0.1:{server.server_port}", model="m", n_ctx=4096)
            pairs = llm.top_tokens("prompt", 2)
        finally:
            server.shutdown()
        self.assertEqual([t for t, _p in pairs], [" a", " b"])
        posted = [p for p in seen if p.get("max_tokens") == 1][-1]
        self.assertEqual((posted["logprobs"], posted["temperature"]), (2, 0.0))


try:
    from tests.test_gui_p2 import GUI_AVAILABLE, _Base
except Exception:  # noqa: BLE001
    GUI_AVAILABLE, _Base = False, unittest.TestCase


@unittest.skipUnless(GUI_AVAILABLE, "no display / customtkinter")
class EditorMenuTests(_Base):
    def test_choose_an_alternative_or_continue_from_it(self):
        self.engine.word_alternatives = lambda project, index, before: (
            self.engine.__dict__.setdefault("asked", before),
            [WordAlternative(" shook", 0.4, " sh"), WordAlternative(" turned", 0.3, " turned")])[1]
        panel = self._chapter("She knelt beside him and touched his face.")
        with mock.patch("tkinter.Menu.tk_popup"):
            panel.show_word_alternatives("1.25", "1.32", at=(0, 0))
            self.app.update()
        self.assertEqual(self.engine.asked, "She knelt beside him and ")
        menu = panel.alternatives_menu
        self.assertEqual(menu.entrycget(0, "label"), "shook   (40 %)")
        self.assertEqual(menu.type(menu.index("end")), "cascade")
        menu.invoke(0)
        self.assertEqual(panel.content_box.get("1.0", "end-1c"), "She knelt beside him and shook his face.")
        self.assertEqual(panel.chapter.content, "She knelt beside him and shook his face.")
        self.assertEqual(panel.chapter.history_entries()[-1]["source"], "alternativa")
        # the text changed meanwhile: nothing happens
        self.assertIsNone(panel.replace_word("1.25", "1.32", "touched", " turned"))
        # continue: replaces, then continues from just after the new word
        with mock.patch.object(panel, "_on_continue") as cont:
            panel.continue_with_word("1.25", "1.30", "shook", " turned")
        cont.assert_called_once_with(from_cursor=True)
        self.assertEqual(panel.content_box.get("1.0", "insert"), "She knelt beside him and turned")


if __name__ == "__main__":
    unittest.main()
