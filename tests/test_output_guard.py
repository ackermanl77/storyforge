"""Cleaning what the model returns (app/output_guard.py), on the patterns seen in a real
project generated with NemoReRemix-12B in the wrong chat format (2026-10-14)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.output_guard import clean_section  # noqa: E402

PREVIOUS = ("Aemon rode beside his brother through the Northern camp. Aegon sat straight in his saddle, "
            "but Aemon could see the tension in his shoulders. They reached Sansa's tent and dismounted.")


class CleanSectionTests(unittest.TestCase):
    def test_clean_prose_is_returned_untouched(self):
        piece = ' "Your Highness," she said as they approached. Aegon bowed his head.'
        self.assertEqual(clean_section(piece, PREVIOUS), (piece, []))

    def test_code_fences_are_removed_and_the_story_kept(self):
        text, removed = clean_section("```python\nAegon walked through the gates of Storm's End.\n```", "")
        self.assertEqual(text, "Aegon walked through the gates of Storm's End.")
        self.assertEqual(removed, ["code fences"])

    def test_echoed_instructions_and_everything_after_them_are_cut(self):
        piece = ("He turned and walked back to Ghost, mounting the direwolf.\n\n"
                 "The chapter is already in progress. The chapter written so far ends like this:\n\n"
                 + PREVIOUS)
        text, removed = clean_section(piece, PREVIOUS)
        self.assertEqual(text, "He turned and walked back to Ghost, mounting the direwolf.")
        self.assertIn("echoed instructions", removed)
        step = ("the point of no return.*\n\n[CHAPTER CONTINUED IN NEXT PART]\n\n"
                "*Continue seamlessly from the exact point where it stops.*\n\nSTEP-SPECIFIC CONTEXT ...")
        self.assertEqual(clean_section(step, "")[0], "the point of no return.*")

    def test_a_restart_that_repeats_the_written_ending_is_dropped(self):
        piece = (" Aegon sat straight in his saddle, but Aemon could see the tension in his shoulders. "
                 "They reached Sansa's tent and dismounted. The door to the tent opened and she emerged.")
        text, removed = clean_section(piece, PREVIOUS)
        self.assertEqual(text, " The door to the tent opened and she emerged.")  # leading space kept for gluing
        self.assertEqual(removed, ["2 repeated sentence(s)"])

    def test_short_repeated_lines_and_repeats_later_in_the_section_stay(self):
        previous = "No. She shook her head and walked away from the burning village."
        piece = ' "No." He watched her go. She shook her head and walked away from the burning village.'
        self.assertEqual(clean_section(piece, previous)[0], piece)  # only a leading echo is cut

    def test_an_answer_made_only_of_echo_comes_back_empty(self):
        text, removed = clean_section("```\nSTEP-SPECIFIC CONTEXT (closest to the passage)\n```", "")
        self.assertEqual(text, "")
        self.assertTrue(removed)


class EngineUsesTheGuardTests(unittest.TestCase):
    def test_a_section_with_an_echo_is_cleaned_before_it_joins_the_chapter(self):
        from tests.test_engine import FakeLlama, make_project
        from app.engine import LocalStoryEngine

        class EchoLlama(FakeLlama):
            def __call__(self, prompt, max_tokens=0, **kwargs):
                self.calls += 1
                text = ("```python\nThe rain fell on the harbour all night long and nobody slept.\n```\n\n"
                        "The chapter is already in progress. The chapter written so far ends like this:")
                return {"choices": [{"text": text, "finish_reason": "stop"}]}

        engine = LocalStoryEngine()
        engine._llm = EchoLlama()
        result = engine.generate_chapter(make_project(target_words=10), 0)
        self.assertEqual(result, "The rain fell on the harbour all night long and nobody slept.")
        self.assertEqual(engine.cleaned_sections, 1)


if __name__ == "__main__":
    unittest.main()
