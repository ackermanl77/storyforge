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


QUOTE = __import__("re").compile(r'["“”]([^"“”]*)["“”]')
WORD = __import__("re").compile(r"[A-Za-z']+")


def _narration_share(text: str, pronouns: set) -> float:
    words = [w.lower() for w in WORD.findall(QUOTE.sub(" ", text))]
    persons = [w for w in words if w in {"i", "me", "my", "you", "your", "she", "her", "he", "him", "his"}]
    return sum(w in pronouns for w in persons) / max(1, len(persons))


def _dialogue_share(text: str) -> float:
    return sum(len(WORD.findall(q)) for q in QUOTE.findall(text)) / max(1, len(WORD.findall(text)))


@unittest.skipUnless(MODEL and os.path.isfile(MODEL), "set STORYFORGE_TEST_MODEL to a .gguf to run")
class TestRealModelStorySettings(unittest.TestCase):
    """The story settings move a real model's writing the way they say (measured with
    daredevil-8b-abliterated Q8 on 2026-10-13; a story model of ~8B or more is needed --
    a tiny smoke-test model won't follow them). Two seeds per setting, 400-word chapters."""

    @classmethod
    def setUpClass(cls):
        cls.engine = LocalStoryEngine()
        layers = int(os.environ.get("STORYFORGE_TEST_GPU_LAYERS", "0"))
        cls.engine.load(MODEL, n_ctx=8192, n_gpu_layers=layers)

    @classmethod
    def tearDownClass(cls):
        cls.engine.unload()

    def _write(self, seed: int, **settings) -> str:
        project = Project(
            plot="Elena returns to her coastal hometown to settle her late father's affairs and finds a locked room.",
            characters="Elena: a guarded translator. Tomas: her younger brother, who wants the room left closed.",
            setting="A fishing town in northern Spain, late autumn.",
        )
        project.add_chapter("The Locked Room", target_words=400).outline = (
            "Elena arrives; she and Tomas argue about selling the house; she finds the key to the locked room.")
        for key, value in settings.items():
            setattr(project, key, value)
        self.engine.sampling = SamplingConfig(seed=seed)
        return self.engine.generate_chapter(project, 0)

    def test_point_of_view_settings_change_the_narration(self):
        for pov, pronouns in (("Primera persona", {"i", "me", "my"}), ("Segunda persona", {"you", "your"})):
            shares = [_narration_share(self._write(seed, point_of_view=pov), pronouns) for seed in (1, 2)]
            self.assertGreater(min(shares), 0.5, (pov, shares))

    def test_dialogue_balance_moves_the_dialogue_share(self):
        most = sum(_dialogue_share(self._write(seed, dialogue_balance="mucho_dialogo")) for seed in (1, 2)) / 2
        least = sum(_dialogue_share(self._write(seed, dialogue_balance="mucha_narracion")) for seed in (1, 2)) / 2
        self.assertGreater(most, least + 0.1, (most, least))


if __name__ == "__main__":
    unittest.main()
