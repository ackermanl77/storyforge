import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import (
    ContextOverflowError,
    LocalStoryEngine,
    MAX_SECTIONS_PER_CHAPTER,
    ModelNotLoadedError,
)
from app.project import Project
from app.prompts import _trim_words_tail


class FakeLlama:
    """Sustituto de llama_cpp.Llama: devuelve ~150 palabras por llamada,
    suficiente para probar el bucle de generacion por secciones sin un
    modelo real ni el paquete llama-cpp-python."""

    def __init__(self):
        self.calls = 0

    def __call__(self, prompt, max_tokens=0, **kwargs):
        self.calls += 1
        words = " ".join(f"word{self.calls}_{i}" for i in range(150))
        return {"choices": [{"text": words}]}


def make_project(target_words=400):
    p = Project(plot="A hero's journey.", characters="Hero", setting="A village")
    p.add_chapter("Chapter One", target_words=target_words)
    return p


class TestEngineNotLoaded(unittest.TestCase):
    def test_generate_without_model_raises(self):
        engine = LocalStoryEngine()
        project = make_project()
        with self.assertRaises(ModelNotLoadedError):
            engine.generate_chapter(project, 0)


class TestEngineGenerationLoop(unittest.TestCase):
    def test_stops_once_target_words_reached(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()  # inyectamos el modelo falso directamente
        project = make_project(target_words=400)

        progress_calls = []
        result = engine.generate_chapter(
            project, 0,
            progress_callback=lambda text, words, target: progress_calls.append(words),
        )

        self.assertGreaterEqual(len(result.split()), 400)
        self.assertTrue(progress_calls, "progress_callback deberia haberse llamado al menos una vez")
        # No deberia haber iterado de mas: con ~150 palabras por llamada,
        # 400 objetivo deberian tomar 3 llamadas o menos.
        self.assertLessEqual(engine._llm.calls, 4)

    def test_respects_max_sections_cap(self):
        engine = LocalStoryEngine()

        class NeverEnoughLlama(FakeLlama):
            def __call__(self, prompt, max_tokens=0, **kwargs):
                self.calls += 1
                return {"choices": [{"text": "x"}]}  # 1 palabra por llamada: nunca alcanza el target

        engine._llm = NeverEnoughLlama()
        project = make_project(target_words=100_000)  # inalcanzable a 1 palabra por llamada
        engine.generate_chapter(project, 0)
        self.assertLessEqual(engine._llm.calls, MAX_SECTIONS_PER_CHAPTER)

    def test_cancel_check_stops_generation_early(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        project = make_project(target_words=100_000)

        # cancela despues de la primera seccion
        state = {"n": 0}

        def cancel_check():
            state["n"] += 1
            return state["n"] > 1

        engine.generate_chapter(project, 0, cancel_check=cancel_check)
        self.assertLessEqual(engine._llm.calls, 2)


class TestTailTrim(unittest.TestCase):
    def test_keeps_the_end_not_the_start(self):
        text = " ".join(f"word{i}" for i in range(1, 101))  # word1 ... word100
        trimmed = _trim_words_tail(text, 10)
        self.assertNotIn("word1 ", trimmed)
        self.assertIn("word100", trimmed)
        self.assertIn("word91", trimmed)

    def test_short_text_untouched(self):
        text = "just a few words"
        self.assertEqual(_trim_words_tail(text, 50), text)


class TestContextOverflow(unittest.TestCase):
    def test_raises_when_nothing_fits_even_at_smallest_budget(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        # 1 token == 1 palabra, determinista para la prueba
        engine._count_tokens = lambda text: len(text.split())
        engine._n_ctx = 10  # ventana ridiculamente chica: nada cabe
        project = make_project(target_words=100)
        project.plot = "word " * 2000
        with self.assertRaises(ContextOverflowError):
            engine.generate_chapter(project, 0)

    def test_shrinks_context_budget_until_it_fits(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        engine._count_tokens = lambda text: len(text.split())
        # n_ctx elegido para que el presupuesto COMPLETO (nivel 0) no quepa,
        # pero un nivel mas chico (nivel 1 o 2) si.
        engine._n_ctx = 1800
        project = make_project(target_words=100)
        project.plot = "word " * 2000  # fuerza overflow con el presupuesto completo
        result = engine.generate_chapter(project, 0)
        self.assertTrue(result.strip())

    def test_summarize_trims_long_chapter_to_fit_context(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        engine._count_tokens = lambda text: len(text.split())
        engine._n_ctx = 500
        long_chapter = "word " * 5000
        summary = engine.summarize(long_chapter, max_words=50)
        self.assertTrue(summary.strip())

    def test_summarize_without_model_raises(self):
        engine = LocalStoryEngine()
        with self.assertRaises(ModelNotLoadedError):
            engine.summarize("some chapter text")


if __name__ == "__main__":
    unittest.main()
