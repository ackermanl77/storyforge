"""
T4: opt-in smoke test against a REAL GGUF (skipped by default).

    set STORYFORGE_TEST_MODEL=C:\\path\\to\\tiny-model.gguf
    set STORYFORGE_TEST_GPU_LAYERS=-1        (optional, default 0)
    python -m pytest -q tests/test_real_model.py

Use a small model (~100-500 MB): it loads the model, streams ~40 tokens with
the chat template, checks cancellation mid-stream, sampling/seed plumbing and
that unload() releases the model. CI never runs it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import LocalStoryEngine, OperationCancelled  # noqa: E402
from app.project import Project  # noqa: E402
from app.sampling import SamplingConfig  # noqa: E402

MODEL = os.environ.get("STORYFORGE_TEST_MODEL", "")


@unittest.skipUnless(MODEL and os.path.isfile(MODEL), "set STORYFORGE_TEST_MODEL to a small .gguf to run")
class TestRealModelSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LocalStoryEngine()
        layers = int(os.environ.get("STORYFORGE_TEST_GPU_LAYERS", "0"))
        cls.engine.load(MODEL, n_ctx=2048, n_gpu_layers=layers)

    @classmethod
    def tearDownClass(cls):
        cls.engine.unload()
        assert not cls.engine.is_loaded

    def test_streams_with_the_chat_template_and_a_fixed_seed(self):
        project = Project(plot="A lighthouse keeper finds a message in a bottle.", characters="Mara.", setting="Coast.")
        project.add_chapter("The Bottle", target_words=40)
        self.engine.sampling = SamplingConfig(seed=42)
        tokens = []
        text = self.engine.generate_chapter(project, 0, progress_callback=lambda t, w, _: tokens.append(w))
        self.assertTrue(text.strip())
        self.assertTrue(tokens)
        self.assertEqual(self.engine.last_seed, 42)
        self.assertGreater(self.engine.stats.generated_tokens, 0)
        self.assertIsNotNone(self.engine.stats.tokens_per_second)

    def test_stop_cancels_mid_stream(self):
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] > 5

        with self.assertRaises(OperationCancelled):
            self.engine.expand_field("plot", "A short idea about a storm.", max_words=300, cancel_check=cancel)


if __name__ == "__main__":
    unittest.main()
