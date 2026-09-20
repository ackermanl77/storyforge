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
from app.prompts import (
    _trim_words_tail,
    build_chapter_purpose_instruction,
    build_chapter_system_prompt,
    build_outline_prompt,
    build_writing_style_instruction,
)


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


class TestChapterOutlineBudget(unittest.TestCase):
    """
    chapter.outline has no size limit enforced at the field level (unlike
    plot/characters/setting) other than Project.validate_inputs()'s check, so
    it must be trimmed the same way as everything else in the chapter prompt
    or an unusually long outline could make the smallest context budget
    level still not fit.
    """

    def test_long_outline_is_trimmed_to_the_given_budget(self):
        project = make_project()
        project.chapters[0].outline = "beat " * 1000
        prompt = build_chapter_system_prompt(project, 0, max_outline_words=50)
        # _trim_words appends " [...]" once the text is cut, which only
        # happens when the outline actually exceeded the budget.
        self.assertIn("[...]", prompt)

    def test_short_outline_is_not_marked_as_trimmed(self):
        project = make_project()
        project.chapters[0].outline = "Hero meets mentor. Hero refuses the call."
        prompt = build_chapter_system_prompt(project, 0, max_outline_words=400)
        self.assertIn("Hero refuses the call.", prompt)
        self.assertNotIn("[...]", prompt)


class TestWritingStyleEmphasis(unittest.TestCase):
    def test_no_style_selected_adds_no_emphasis(self):
        project = make_project()
        project.writing_style = ""
        self.assertEqual(build_writing_style_instruction(project), "")
        self.assertNotIn("WRITING STYLE EMPHASIS", build_chapter_system_prompt(project, 0))

    def test_unknown_style_value_is_ignored_not_an_error(self):
        # p.ej. un proyecto viejo con un valor que ya no existe en
        # project.WRITING_STYLES -- no debe romper la generacion.
        project = make_project()
        project.writing_style = "un valor que ya no existe"
        self.assertEqual(build_writing_style_instruction(project), "")

    def test_known_style_adds_its_emphasis_to_the_chapter_prompt(self):
        project = make_project()
        project.writing_style = "Dialogo"
        prompt = build_chapter_system_prompt(project, 0)
        self.assertIn("WRITING STYLE EMPHASIS", prompt)
        self.assertIn("dialogue-driven", prompt)

    def test_known_style_adds_its_emphasis_to_the_outline_prompt(self):
        project = make_project()
        project.writing_style = "Accion rapida"
        prompt = build_outline_prompt(project, num_chapters=3)
        self.assertIn("WRITING STYLE EMPHASIS", prompt)
        self.assertIn("fast pacing", prompt)


class TestChapterPurposeInstruction(unittest.TestCase):
    def test_no_purpose_selected_adds_no_instruction(self):
        project = make_project()
        project.chapters[0].purpose = ""
        self.assertEqual(build_chapter_purpose_instruction(project.chapters[0]), "")
        self.assertNotIn("CHAPTER PURPOSE", build_chapter_system_prompt(project, 0))

    def test_unknown_purpose_value_is_ignored_not_an_error(self):
        project = make_project()
        project.chapters[0].purpose = "algo que ya no existe"
        self.assertEqual(build_chapter_purpose_instruction(project.chapters[0]), "")

    def test_known_purpose_adds_its_instruction_to_the_chapter_prompt(self):
        project = make_project()
        project.chapters[0].purpose = "Epilogo"
        prompt = build_chapter_system_prompt(project, 0)
        self.assertIn("CHAPTER PURPOSE", prompt)
        self.assertIn("EPILOGUE", prompt)

    def test_opening_purpose_instruction(self):
        project = make_project()
        project.chapters[0].purpose = "Apertura"
        prompt = build_chapter_system_prompt(project, 0)
        self.assertIn("OPENING chapter", prompt)

    def test_climax_purpose_instruction(self):
        project = make_project()
        project.chapters[0].purpose = "Escena climatica"
        prompt = build_chapter_system_prompt(project, 0)
        self.assertIn("CLIMAX", prompt)

    def test_final_purpose_instruction(self):
        project = make_project()
        project.chapters[0].purpose = "Final"
        prompt = build_chapter_system_prompt(project, 0)
        self.assertIn("FINAL chapter", prompt)


class TestExpandField(unittest.TestCase):
    def test_expand_field_without_model_raises(self):
        engine = LocalStoryEngine()
        with self.assertRaises(ModelNotLoadedError):
            engine.expand_field("plot", "a short idea", max_words=100)

    def test_expand_field_returns_model_output(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        result = engine.expand_field("plot", "a hero's journey", max_words=100)
        self.assertTrue(result.strip())

    def test_expand_field_trims_very_long_input_to_fit_context(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        engine._n_ctx = 500
        long_note = "idea " * 5000
        result = engine.expand_field("characters", long_note, max_words=50)
        self.assertTrue(result.strip())


class TestRefineChapter(unittest.TestCase):
    def test_refine_chapter_without_model_raises(self):
        engine = LocalStoryEngine()
        project = make_project()
        project.chapters[0].content = "Once upon a time."
        with self.assertRaises(ModelNotLoadedError):
            engine.refine_chapter(project, 0, "make it darker")

    def test_refine_chapter_returns_model_output(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        project = make_project()
        project.chapters[0].content = "Once upon a time, a hero set out."
        result = engine.refine_chapter(project, 0, "make it darker")
        self.assertTrue(result.strip())

    def test_refine_chapter_shrinks_budget_until_it_fits(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        engine._count_tokens = lambda text: len(text.split())
        engine._n_ctx = 6000
        project = make_project(target_words=100)
        # 2500 palabras: menos que max_content_words del nivel completo
        # (3000, asi que no se recorta ahi y el prompt no cabe), pero mas que
        # el del nivel intermedio (1800, donde si se recorta y termina
        # cabiendo).
        project.chapters[0].content = "word " * 2500
        result = engine.refine_chapter(project, 0, "shorten this")
        self.assertTrue(result.strip())

    def test_refine_chapter_does_not_leak_plot_characters_setting(self):
        # build_refine_chapter_prompt deliberadamente no incluye plot/
        # personajes/setting -- prioriza conservar el capitulo completo.
        from app.prompts import build_refine_chapter_prompt
        project = make_project()
        project.plot = "UNIQUE_PLOT_MARKER_TEXT"
        project.chapters[0].content = "Once upon a time."
        prompt = build_refine_chapter_prompt(project, 0, "make it darker")
        self.assertNotIn("UNIQUE_PLOT_MARKER_TEXT", prompt)


class TestModelReload(unittest.TestCase):
    """
    Loading a new model must not hold the previous one in memory while the
    new one is being constructed -- two multi-GB Llama instances resident at
    once can exhaust RAM/VRAM.
    """

    def test_load_unloads_the_previous_model_first(self):
        import sys
        import tempfile
        import types

        engine = LocalStoryEngine()
        engine._llm = FakeLlama()  # simulates an already-loaded model
        saw_previous_model_released = []

        def fake_llama_constructor(**kwargs):
            # By the time the "new" model is being constructed, the old one
            # must already have been released, not just about to be replaced.
            saw_previous_model_released.append(engine._llm is None)
            return FakeLlama()

        fake_module = types.ModuleType("llama_cpp")
        fake_module.Llama = fake_llama_constructor
        sys.modules["llama_cpp"] = fake_module
        try:
            with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as tmp:
                model_path = tmp.name
            try:
                engine.load(model_path)
            finally:
                os.remove(model_path)
        finally:
            del sys.modules["llama_cpp"]

        self.assertEqual(saw_previous_model_released, [True])
        self.assertIsNotNone(engine._llm)


if __name__ == "__main__":
    unittest.main()
