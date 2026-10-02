import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import repetition


class TestWordFrequencies(unittest.TestCase):
    def test_counts_ignore_stopwords_and_short_words(self):
        text = "The castle was old. The castle was cold and the castle was silent."
        freqs = repetition.word_frequencies(text)
        # "castle" repeats 3 times and should be counted; "the"/"was"/"and" are stopwords
        self.assertEqual(freqs["castle"], 3)
        self.assertNotIn("the", freqs)
        self.assertNotIn("was", freqs)

    def test_overused_words_flags_high_frequency(self):
        text = "shadow " * 20 + "quiet forest path near the old shadow house"
        flagged = repetition.overused_words(text, per_1000_threshold=1.0)
        flagged_words = [w for w, _ in flagged]
        self.assertIn("shadow", flagged_words)

    def test_overused_words_empty_for_varied_text(self):
        text = "A quiet forest stood beside a river under pale morning light."
        flagged = repetition.overused_words(text)
        self.assertEqual(flagged, [])


class TestReduceRepetitionDegradesGracefully(unittest.TestCase):
    def test_no_flagged_words_returns_original(self):
        text = "A quiet forest stood beside a river under pale morning light."
        self.assertEqual(repetition.reduce_repetition(text), text)

    def test_without_nltk_data_does_not_crash_or_corrupt_text(self):
        # Fuerza el camino "sin datos de NLTK disponibles" para simular un
        # entorno sin internet y sin el corpus descargado: no debe fallar,
        # y como no hay sinonimos disponibles, el texto debe quedar intacto.
        original_ready = repetition._NLTK_READY
        original_cache = repetition._STOPWORDS_CACHE
        try:
            repetition._NLTK_READY = False
            repetition._STOPWORDS_CACHE = None
            text = "shadow " * 20 + "in the deep shadow forest"
            result = repetition.reduce_repetition(text)
            self.assertEqual(result.lower().split().count("shadow"), text.lower().split().count("shadow"))
        finally:
            repetition._NLTK_READY = original_ready
            repetition._STOPWORDS_CACHE = original_cache

    def test_zipped_wordnet_counts_as_available(self):
        # Regression: nltk.downloader leaves wordnet as corpora/wordnet.zip, and
        # find("corpora/wordnet") without ".zip" fails -- synonyms never ran.
        try:
            import nltk
        except ImportError:
            self.skipTest("nltk no esta instalado")
        from unittest import mock

        def fake_find(resource, *args, **kwargs):
            if resource in ("corpora/stopwords", "corpora/wordnet.zip"):
                return resource
            raise LookupError(resource)

        original_ready = repetition._NLTK_READY
        try:
            repetition._NLTK_READY = None
            with mock.patch.object(nltk.data, "find", side_effect=fake_find), \
                    mock.patch.object(nltk, "download", side_effect=AssertionError("must not download")):
                self.assertTrue(repetition._ensure_nltk_data())
        finally:
            repetition._NLTK_READY = original_ready

    def test_synonyms_are_found_with_the_bundled_data(self):
        local = repetition._local_nltk_data_dir()
        if not os.path.exists(os.path.join(local, "corpora", "wordnet.zip")):
            self.skipTest("nltk_data/ local no descargado (build.bat lo crea)")
        original_ready = repetition._NLTK_READY
        try:
            repetition._NLTK_READY = None
            self.assertTrue(repetition._ensure_nltk_data())
            self.assertIsNotNone(repetition._best_synonym("happy", {"happy"}))
        finally:
            repetition._NLTK_READY = original_ready

    def test_repetition_report_has_readable_output(self):
        text = "mountain " * 10 + "a calm village below"
        report = repetition.repetition_report(text)
        self.assertIn("mountain", report)


if __name__ == "__main__":
    unittest.main()
