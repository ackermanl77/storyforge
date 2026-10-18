"""Frases a evitar (B15, app/phrase_guard.py): matching, and the engine's rewind-and-resample.

The real 3,000-word run with daredevil-8b wrote "her heart skipped a beat" three times and kept
closing sections on "...would change her life forever"."""

import unittest

import numpy as np

from app.engine import LocalStoryEngine
from app.phrase_guard import DEFAULT_BANNED_PHRASES, MAX_REWINDS, MAX_REWINDS_AT_ONE_POINT, PhraseGuard, clean_phrases
from app.project import Project
from app.sampling import TASK_OUTLINE, TASK_PROSE
from tests.test_generation_quality import LLAMA3_SPECIALS, ChatFakeLlama, _chapter_project


class Recording(ChatFakeLlama):
    """Also keeps every call's logits_processor."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.processors = []

    def __call__(self, prompt, max_tokens=0, stop=None, stream=False, **kwargs):
        self.processors.append(kwargs.get("logits_processor"))
        return super().__call__(prompt, max_tokens, stop, stream, **kwargs)


def _engine(respond):
    engine = LocalStoryEngine()
    engine._llm = Recording(respond, specials=LLAMA3_SPECIALS)
    return engine


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.guard = PhraseGuard(list(DEFAULT_BANNED_PHRASES))

    def _hit(self, text):
        m = self.guard.search(text)
        return m and text[m.start:m.end]

    def test_clichés_are_found_case_insensitively_with_wildcards_and_both_apostrophes(self):
        self.assertEqual(self._hit("Then her HEART skipped a beat."), "HEART skipped a beat")
        self.assertEqual(self._hit("It would change her whole life forever."), "change her whole life forever")
        self.assertEqual(self._hit("a breath she didn’t know she was holding"), "breath she didn’t know she was holding")
        self.assertEqual(self._hit("Supo que eso cambiaría su vida para siempre."), "cambiaría su vida para siempre")

    def test_ordinary_sentences_are_left_alone(self):
        for text in ("a change of plans forever after", "his heartbeat skipped", "the old testament",
                     "She wanted to change the world."):
            self.assertIsNone(self.guard.search(text), text)

    def test_the_list_is_cleaned(self):
        self.assertEqual(clean_phrases(["  heart  skipped ", "Heart skipped", "*", "* lead", "", "ok *"]),
                         ["heart skipped", "lead", "ok"])

    def test_a_project_gets_the_defaults_plus_its_own_or_only_its_own(self):
        project = Project(banned_phrases=["the void stared back"])
        self.assertIn("the void stared back", PhraseGuard.for_project(project).phrases)
        self.assertIn("heart skipped a beat", PhraseGuard.for_project(project).phrases)
        project.avoid_cliches = False
        self.assertEqual(PhraseGuard.for_project(project).phrases, ["the void stared back"])
        project.banned_phrases = []
        self.assertIsNone(PhraseGuard.for_project(project))

    def test_the_settings_are_saved_with_the_project(self):
        project = Project(avoid_cliches=False, banned_phrases=["the void stared back", " "])
        loaded = Project.from_dict(project.to_dict())
        self.assertFalse(loaded.avoid_cliches)
        self.assertEqual(loaded.banned_phrases, ["the void stared back"])
        self.assertTrue(Project.from_dict({"name": "old"}).avoid_cliches)  # older files: on


class TestRewind(unittest.TestCase):
    CLICHE = " She waited by the door. Her heart skipped a beat when it opened. "
    FIXED = " pulse jumped when it opened. "

    def test_a_streamed_cliché_is_rewritten_and_never_shown(self):
        def respond(prompt, i):
            if prompt.endswith("Her"):
                return self.FIXED + "word " * 400
            return self.CLICHE + "word " * 400

        engine = _engine(respond)
        shown = []
        text = engine.generate_chapter(_chapter_project(target=150), 0,
                                       progress_callback=lambda t, w, total: shown.append(t))
        self.assertIn("Her pulse jumped when it opened.", text)
        self.assertNotIn("heart skipped a beat", text)
        self.assertFalse(any("heart skipped" in s for s in shown))  # held back, then cut
        self.assertGreaterEqual(engine.stats.phrase_rewinds, 1)
        # The resumed call continues the same prompt from just before the phrase...
        first, second = engine._llm.prompts[0], engine._llm.prompts[1]
        self.assertTrue(second.startswith(first) and second.endswith("Her"))
        # ...with the phrase's first word banned as its first token only.
        processor = engine._llm.processors[1]
        ids = engine._first_token_ids("heart")
        self.assertTrue(ids)
        prompt_len = engine._count_tokens(second)
        scores = np.zeros(32, dtype=np.float32)
        processor[0](np.arange(prompt_len), scores)
        self.assertTrue(np.isneginf(scores[ids]).all())
        scores = np.zeros(32, dtype=np.float32)
        processor[0](np.arange(prompt_len + 1), scores)
        self.assertFalse(np.isneginf(scores[ids]).any())

    def test_a_non_streamed_completion_is_rewritten_too(self):
        engine = _engine(lambda p, i: (self.FIXED if p.endswith("Her") else self.CLICHE) + "end.")
        engine.phrase_guard = PhraseGuard(list(DEFAULT_BANNED_PHRASES))
        result = engine._complete_ex("Write.", 200, task=TASK_PROSE)
        self.assertIn("Her pulse jumped", result.text)
        self.assertNotIn("heart skipped", result.text)
        self.assertEqual(result.finish_reason, "stop")

    def test_a_model_that_insists_at_one_point_is_accepted_after_a_few_tries(self):
        def respond(prompt, i):
            if prompt.endswith("Her"):
                return " heart skipped a beat. end."  # insists, every time
            if prompt.endswith("beat."):  # the fake streams "beat." as one piece
                return " The end."  # once accepted, it just goes on
            return self.CLICHE + "end."

        engine = _engine(respond)
        engine.phrase_guard = PhraseGuard(list(DEFAULT_BANNED_PHRASES))
        result = engine._complete_ex("Write.", 200, task=TASK_PROSE)
        self.assertIn("Her heart skipped a beat. The end.", result.text)  # accepted rather than looping
        # the first call, MAX_REWINDS_AT_ONE_POINT retries, the accepting one, and the rest of the text
        self.assertEqual(len(engine._llm.prompts), 2 + MAX_REWINDS_AT_ONE_POINT)

    def test_the_rewinds_per_call_are_capped(self):
        # Every resumed call repeats the whole cliché sentence, so it lands somewhere new each time.
        engine = _engine(lambda p, i: self.CLICHE + "end.")
        engine.phrase_guard = PhraseGuard(list(DEFAULT_BANNED_PHRASES))
        engine._complete_ex("Write.", 400, task=TASK_PROSE)
        self.assertEqual(len(engine._llm.prompts), 1 + MAX_REWINDS)

    def test_outlines_and_turned_off_projects_are_not_touched(self):
        engine = _engine(lambda p, i: self.CLICHE + "end.")
        engine.phrase_guard = PhraseGuard(list(DEFAULT_BANNED_PHRASES))
        self.assertIn("heart skipped", engine._complete_ex("Outline.", 200, task=TASK_OUTLINE).text)
        self.assertEqual(len(engine._llm.prompts), 1)
        project = _chapter_project(target=60)
        project.avoid_cliches = False
        engine = _engine(lambda p, i: self.CLICHE + "word " * 100)
        self.assertIn("heart skipped a beat", engine.generate_chapter(project, 0))


if __name__ == "__main__":
    unittest.main()
