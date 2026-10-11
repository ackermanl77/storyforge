import os
import sys
import tempfile
import types
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.engine as engine_module
from app.engine import (
    ContextOverflowError,
    LocalStoryEngine,
    MAX_SECTIONS_PER_CHAPTER,
    ModelNotLoadedError,
    supports_gpu_offload,
)
from app.project import LoreEntry, Project
from app.prompts import (
    _trim_words_tail,
    build_chapter_purpose_instruction,
    build_chapter_system_prompt,
    build_lorebook_block,
    build_outline_prompt,
    build_writing_style_instruction,
    find_relevant_lore_entries,
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


class StreamingFakeLlama:
    """
    A llama_cpp.Llama stand-in that actually honors stream=True, unlike
    FakeLlama above (which always returns a complete dict, the same way a
    handful of existing tests' engine._llm doubles do -- LocalStoryEngine.
    _complete() is deliberately written to accept either shape, see
    app/engine.py). When stream=True is passed, this returns a generator of
    incremental text deltas (NOT cumulative), matching llama_cpp's own
    streaming format. `stream_requests` records whether stream=True was
    passed on each call, so tests can confirm generate_chapter() only asks
    for streaming when it actually has a progress_callback to feed.
    """

    def __init__(self, words_per_call: int = 150, chunk_size: int = 10):
        self.calls = 0
        self.words_per_call = words_per_call
        self.chunk_size = chunk_size
        self.stream_requests = []

    def __call__(self, prompt, max_tokens=0, stream=False, **kwargs):
        self.calls += 1
        self.stream_requests.append(stream)
        words = [f"word{self.calls}_{i}" for i in range(self.words_per_call)]
        if not stream:
            return {"choices": [{"text": " ".join(words)}]}
        return self._stream(words)

    def _stream(self, words):
        for i in range(0, len(words), self.chunk_size):
            chunk = words[i:i + self.chunk_size]
            delta = (" " if i > 0 else "") + " ".join(chunk)
            yield {"choices": [{"text": delta}]}


class StopHonoringFakeLlama:
    """
    A llama_cpp.Llama stand-in that, unlike FakeLlama/StreamingFakeLlama
    above, honors `stop` and `max_tokens` the way llama.cpp does: the
    response is cut right before the earliest stop sequence, and to at most
    int(max_tokens / TOKENS_PER_WORD_ESTIMATE) words. `respond(prompt)`
    produces the model's "full" answer; `stops`/`max_tokens` record what each
    call asked for.
    """

    def __init__(self, respond):
        self.respond = respond
        self.calls = 0
        self.stops = []
        self.max_tokens = []
        self.prompts = []

    def __call__(self, prompt, max_tokens=0, stop=None, **kwargs):
        self.calls += 1
        self.stops.append(stop)
        self.max_tokens.append(max_tokens)
        self.prompts.append(prompt)
        text = self.respond(prompt)
        finish_reason = "stop"
        cut = min((text.find(s) for s in (stop or []) if s in text), default=-1)
        if cut >= 0:
            text = text[:cut]
        max_words = int(max_tokens / engine_module.TOKENS_PER_WORD_ESTIMATE)
        words = text.split(" ")
        if len(words) > max_words:
            text = " ".join(words[:max_words])
            finish_reason = "length"
        # Igual que llama.cpp: "length" si se agoto max_tokens, "stop" si el
        # modelo termino solo o toco una secuencia de corte.
        return {"choices": [{"text": text, "finish_reason": finish_reason}]}


def _echo_refine_chunk(prompt):
    """Answers a refine prompt with exactly the text it was asked to revise."""
    start = prompt.index("CURRENT CHAPTER TEXT:\n") + len("CURRENT CHAPTER TEXT:\n")
    end = prompt.rindex("\n\nRevised chapter:")
    return prompt[start:end]


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

    def test_records_where_the_last_section_starts(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        project = make_project(target_words=400)
        result = engine.generate_chapter(project, 0)
        start = engine.last_section_start
        self.assertIsNotNone(start)
        self.assertTrue(0 < start < len(result))
        # Continuing from that prefix regenerates only the last section: the prefix stays as it was.
        prefix = result[:start]
        again = engine.generate_chapter(project, 0, resume_from=prefix)
        self.assertTrue(again.startswith(prefix.rstrip()))
        self.assertEqual(engine.last_section_start, len(prefix.rstrip()))

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

    def test_refine_long_chapter_in_parts_keeps_the_whole_chapter(self):
        # Antes: el capitulo se recortaba para caber (conservando el inicio)
        # y la version "revisada" de ese recorte reemplazaba el capitulo
        # completo -- el final se perdia en silencio.
        engine = LocalStoryEngine()
        engine._llm = StopHonoringFakeLlama(_echo_refine_chunk)
        engine._count_tokens = lambda text: len(text.split())
        engine._n_ctx = 3000
        project = make_project(target_words=100)
        paragraphs = [f"PARA{i} " + " ".join(["word"] * 99) for i in range(40)]  # 4,000 palabras
        project.chapters[0].content = "\n\n".join(paragraphs)

        result = engine.refine_chapter(project, 0, "shorten this")

        self.assertGreater(engine._llm.calls, 1, "should have been refined in several parts")
        for i in range(40):
            self.assertIn(f"PARA{i} ", result)
        self.assertEqual(result, project.chapters[0].content)
        self.assertIn("part 1 of", engine._llm.prompts[0])

    def test_refine_single_huge_paragraph_is_split_without_losing_words(self):
        engine = LocalStoryEngine()
        engine._llm = StopHonoringFakeLlama(_echo_refine_chunk)
        engine._count_tokens = lambda text: len(text.split())
        engine._n_ctx = 3000
        project = make_project(target_words=100)
        project.chapters[0].content = " ".join(f"w{i}" for i in range(3000))  # sin parrafos ni puntuacion

        result = engine.refine_chapter(project, 0, "shorten this")

        self.assertEqual(result.split(), project.chapters[0].content.split())

    def test_refine_short_chapter_is_a_single_call(self):
        engine = LocalStoryEngine()
        engine._llm = StopHonoringFakeLlama(_echo_refine_chunk)
        project = make_project()
        project.chapters[0].content = "Once upon a time, a hero set out."
        engine.refine_chapter(project, 0, "make it darker")
        self.assertEqual(engine._llm.calls, 1)
        self.assertNotIn("part 1 of", engine._llm.prompts[0])

    def test_refine_does_not_stop_at_a_paragraph_starting_with_chapter(self):
        engine = LocalStoryEngine()
        engine._llm = StopHonoringFakeLlama(_echo_refine_chunk)
        project = make_project()
        project.chapters[0].content = "She closed the book.\n\nChapter by chapter, her life had changed."
        result = engine.refine_chapter(project, 0, "make it darker")
        self.assertIn("her life had changed", result)

    def test_refine_empty_part_raises_instead_of_dropping_text(self):
        engine = LocalStoryEngine()
        engine._llm = StopHonoringFakeLlama(lambda prompt: "" if "PARA20 " in prompt else _echo_refine_chunk(prompt))
        engine._count_tokens = lambda text: len(text.split())
        engine._n_ctx = 3000
        project = make_project(target_words=100)
        project.chapters[0].content = "\n\n".join(f"PARA{i} " + " ".join(["word"] * 99) for i in range(40))
        with self.assertRaises(RuntimeError):
            engine.refine_chapter(project, 0, "shorten this")

    def test_refine_raises_clear_error_when_not_even_a_small_part_fits(self):
        engine = LocalStoryEngine()
        engine._llm = FakeLlama()
        engine._count_tokens = lambda text: len(text.split())
        engine._n_ctx = 400
        project = make_project(target_words=100)
        project.chapters[0].content = "word " * 2000
        with self.assertRaises(ContextOverflowError):
            engine.refine_chapter(project, 0, "shorten this")

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


class TestFindRelevantLoreEntries(unittest.TestCase):
    def test_empty_scan_text_matches_nothing(self):
        entries = [LoreEntry(name="A", keywords="a", text="x")]
        self.assertEqual(find_relevant_lore_entries(entries, ""), [])

    def test_matches_case_insensitively(self):
        entries = [LoreEntry(name="Queen", keywords="queen", text="royal")]
        self.assertEqual(find_relevant_lore_entries(entries, "Then the QUEEN spoke."), entries)

    def test_matches_multi_word_keyword_phrase(self):
        entries = [LoreEntry(name="Queen", keywords="the queen", text="royal")]
        self.assertEqual(find_relevant_lore_entries(entries, "Then the queen spoke."), entries)

    def test_does_not_match_as_a_substring_of_another_word(self):
        entries = [LoreEntry(name="Ann", keywords="Ann", text="x")]
        self.assertEqual(find_relevant_lore_entries(entries, "The announcement echoed."), [])

    def test_entry_with_no_keywords_never_matches(self):
        entries = [LoreEntry(name="Empty", keywords="", text="x")]
        self.assertEqual(find_relevant_lore_entries(entries, "anything at all"), [])

    def test_preserves_entry_order(self):
        first = LoreEntry(name="First", keywords="alpha", text="1")
        second = LoreEntry(name="Second", keywords="beta", text="2")
        result = find_relevant_lore_entries([first, second], "alpha and beta both appear")
        self.assertEqual(result, [first, second])


class TestBuildLorebookBlock(unittest.TestCase):
    def test_empty_string_when_nothing_matches(self):
        entries = [LoreEntry(name="A", keywords="zzz", text="text")]
        self.assertEqual(build_lorebook_block(entries, "no match here"), "")

    def test_trims_matched_entry_text_to_budget(self):
        entries = [LoreEntry(name="A", keywords="alpha", text="word " * 500)]
        block = build_lorebook_block(entries, "alpha appears", max_entry_words=20)
        self.assertIn("[...]", block)

    def test_caps_number_of_matched_entries(self):
        entries = [LoreEntry(name=f"E{i}", keywords="alpha", text=f"body{i}") for i in range(20)]
        block = build_lorebook_block(entries, "alpha appears", max_entries=3)
        self.assertEqual(block.count("body"), 3)


class TestLorebookInChapterPrompt(unittest.TestCase):
    """
    Lorebook / World Info integration point: build_chapter_system_prompt()
    scans the current chapter's outline plus the previous chapters' summary
    text (the narratively "nearby" material for this generation) and only
    pulls in a lore entry's text when one of its keywords actually appears
    there -- unlike plot/characters/setting, which are always included in
    full.
    """

    def test_entry_not_included_when_no_keyword_matches(self):
        project = make_project()
        project.lore_entries.append(
            LoreEntry(name="Unrelated", keywords="Bob, Bobby", text="UNIQUE_LORE_MARKER")
        )
        project.chapters[0].outline = "Hero meets mentor in the forest."
        prompt = build_chapter_system_prompt(project, 0)
        self.assertNotIn("UNIQUE_LORE_MARKER", prompt)
        self.assertNotIn("RELEVANT WORLD INFO", prompt)

    def test_entry_included_when_outline_mentions_a_keyword(self):
        project = make_project()
        project.lore_entries.append(
            LoreEntry(name="The Mentor", keywords="mentor, old sage", text="UNIQUE_LORE_MARKER")
        )
        project.chapters[0].outline = "Hero meets the mentor in the forest."
        prompt = build_chapter_system_prompt(project, 0)
        self.assertIn("UNIQUE_LORE_MARKER", prompt)
        self.assertIn("RELEVANT WORLD INFO", prompt)

    def test_previous_chapter_summary_can_also_trigger_a_match(self):
        project = make_project()
        project.add_chapter("Chapter Two", target_words=200)
        project.chapters[0].summary = "The hero defeated the dragon."
        project.lore_entries.append(LoreEntry(name="Dragon", keywords="dragon", text="UNIQUE_LORE_MARKER"))
        prompt = build_chapter_system_prompt(project, 1)
        self.assertIn("UNIQUE_LORE_MARKER", prompt)

    def test_no_lore_entries_adds_no_block(self):
        project = make_project()
        prompt = build_chapter_system_prompt(project, 0)
        self.assertNotIn("RELEVANT WORLD INFO", prompt)


class TestStreamingGeneration(unittest.TestCase):
    """
    LocalStoryEngine.generate_chapter() streams each section token-by-token
    via llama_cpp.Llama.__call__(..., stream=True) when a progress_callback
    is supplied, instead of only reporting once the whole ~900-word section
    is done -- see app/engine.py::_complete().
    """

    def test_does_not_request_streaming_without_a_progress_callback(self):
        engine = LocalStoryEngine()
        llm = StreamingFakeLlama()
        engine._llm = llm
        project = make_project(target_words=100)
        engine.generate_chapter(project, 0)
        self.assertTrue(llm.stream_requests)
        self.assertFalse(any(llm.stream_requests))

    def test_requests_streaming_when_progress_callback_is_given(self):
        engine = LocalStoryEngine()
        llm = StreamingFakeLlama()
        engine._llm = llm
        project = make_project(target_words=100)
        engine.generate_chapter(project, 0, progress_callback=lambda *a: None)
        self.assertTrue(any(llm.stream_requests))

    def test_progress_callback_fires_many_times_within_a_single_section(self):
        engine = LocalStoryEngine()
        engine._llm = StreamingFakeLlama(words_per_call=150, chunk_size=10)
        project = make_project(target_words=100)
        updates = []
        engine.generate_chapter(
            project, 0, progress_callback=lambda text, words, target: updates.append(words)
        )
        # 150 words / 10-word chunks = 15 token-level updates for the first
        # section alone, plus the section-end update -- far more than the
        # old one-call-per-section behavior.
        self.assertGreater(len(updates), 5)
        # Word counts reported must never go backwards (cumulative text).
        self.assertEqual(updates, sorted(updates))

    def test_final_result_contains_all_streamed_text(self):
        engine = LocalStoryEngine()
        engine._llm = StreamingFakeLlama(words_per_call=150, chunk_size=10)
        project = make_project(target_words=100)
        result = engine.generate_chapter(project, 0, progress_callback=lambda *a: None)
        self.assertIn("word1_0", result)
        self.assertIn("word1_149", result)

    def test_cancel_check_can_stop_generation_mid_stream(self):
        engine = LocalStoryEngine()
        engine._llm = StreamingFakeLlama(words_per_call=150, chunk_size=10)
        project = make_project(target_words=100_000)  # unreachable within one section

        state = {"n": 0}

        def cancel_check():
            state["n"] += 1
            return state["n"] > 3  # cancel partway through the first section's stream

        result = engine.generate_chapter(
            project, 0, progress_callback=lambda *a: None, cancel_check=cancel_check
        )
        # Cancelling a few chunks into a 15-chunk section must leave
        # noticeably less than the section's full 150 words -- proof
        # cancellation took effect DURING the section, not only between
        # sections like before streaming existed.
        self.assertLess(len(result.split()), 150)


class TestCudaDllDiscovery(unittest.TestCase):
    """_ensure_cuda_dlls_discoverable() locates the standalone nvidia-cuda-runtime/
    nvidia-cublas pip packages' DLL folders and puts them on PATH so a CUDA-enabled
    llama-cpp-python wheel can actually load (see README's "Rendimiento / GPU").
    """

    def setUp(self):
        self._orig_prepared = engine_module._cuda_dlls_prepared
        engine_module._cuda_dlls_prepared = False
        self._orig_path = os.environ.get("PATH", "")

    def tearDown(self):
        engine_module._cuda_dlls_prepared = self._orig_prepared
        os.environ["PATH"] = self._orig_path

    def _make_fake_nvidia_dll_dir(self, tmp):
        site_packages = os.path.join(tmp, "site-packages")
        dll_dir = os.path.join(site_packages, "nvidia", "cu13", "bin", "x86_64")
        os.makedirs(dll_dir)
        open(os.path.join(dll_dir, "cublas64_13.dll"), "wb").close()
        return site_packages, dll_dir

    def test_finds_and_adds_nvidia_dll_directory_to_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_packages, dll_dir = self._make_fake_nvidia_dll_dir(tmp)
            with unittest.mock.patch.object(sys, "path", sys.path + [site_packages]):
                engine_module._ensure_cuda_dlls_discoverable()
            self.assertIn(dll_dir, os.environ["PATH"])

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_packages, _dll_dir = self._make_fake_nvidia_dll_dir(tmp)
            with unittest.mock.patch.object(sys, "path", sys.path + [site_packages]):
                engine_module._ensure_cuda_dlls_discoverable()
                path_after_first = os.environ["PATH"]
                engine_module._ensure_cuda_dlls_discoverable()
                self.assertEqual(path_after_first, os.environ["PATH"])

    def test_finds_cuda12_layout_with_dlls_directly_in_bin(self):
        # nvidia-cublas-cu12 & co. put the DLLs in nvidia/<pkg>/bin/*.dll,
        # one level shallower than cu13's nvidia/cu13/bin/x86_64/.
        with tempfile.TemporaryDirectory() as tmp:
            site_packages = os.path.join(tmp, "site-packages")
            cublas_bin = os.path.join(site_packages, "nvidia", "cublas", "bin")
            runtime_bin = os.path.join(site_packages, "nvidia", "cuda_runtime", "bin")
            for d, dll in ((cublas_bin, "cublas64_12.dll"), (runtime_bin, "cudart64_12.dll")):
                os.makedirs(d)
                open(os.path.join(d, dll), "wb").close()
            self.assertEqual(
                sorted(engine_module.find_nvidia_dll_dirs(site_packages)), sorted([cublas_bin, runtime_bin])
            )
            with unittest.mock.patch.object(sys, "path", sys.path + [site_packages]), \
                    unittest.mock.patch.object(engine_module.sys, "platform", "win32"), \
                    unittest.mock.patch.object(engine_module.os, "add_dll_directory", create=True):
                engine_module._ensure_cuda_dlls_discoverable()
            self.assertIn(cublas_bin, os.environ["PATH"])
            self.assertIn(runtime_bin, os.environ["PATH"])

    def test_bin_dir_without_dlls_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_packages = os.path.join(tmp, "site-packages")
            os.makedirs(os.path.join(site_packages, "nvidia", "cublas", "bin"))
            self.assertEqual(engine_module.find_nvidia_dll_dirs(site_packages), [])

    def test_no_op_when_no_nvidia_packages_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_packages = os.path.join(tmp, "site-packages")
            os.makedirs(site_packages)
            with unittest.mock.patch.object(sys, "path", [site_packages]):
                engine_module._ensure_cuda_dlls_discoverable()  # must not raise
            self.assertEqual(os.environ.get("PATH", ""), self._orig_path)


class TestSupportsGpuOffload(unittest.TestCase):
    def test_returns_false_when_llama_cpp_not_installed(self):
        with unittest.mock.patch.dict(sys.modules, {"llama_cpp": None, "llama_cpp.llama_cpp": None}):
            self.assertFalse(supports_gpu_offload())

    def test_reflects_the_real_llama_cpp_offload_capability_flag(self):
        fake_lib = types.ModuleType("llama_cpp.llama_cpp")
        fake_lib.llama_supports_gpu_offload = lambda: True
        fake_pkg = types.ModuleType("llama_cpp")
        fake_pkg.llama_cpp = fake_lib
        with unittest.mock.patch.dict(sys.modules, {"llama_cpp": fake_pkg, "llama_cpp.llama_cpp": fake_lib}):
            self.assertTrue(supports_gpu_offload())

        fake_lib.llama_supports_gpu_offload = lambda: False
        with unittest.mock.patch.dict(sys.modules, {"llama_cpp": fake_pkg, "llama_cpp.llama_cpp": fake_lib}):
            self.assertFalse(supports_gpu_offload())

    def test_returns_false_when_llama_cpp_fails_to_load_its_dlls(self):
        # A CUDA-built llama_cpp whose CUDA runtime DLLs can't be resolved raises RuntimeError
        # ("Failed to load shared library ...") from the import itself, not ImportError -- this
        # runs while the GUI builds its Model tab, so it must degrade to "no GPU", not crash.
        class _DllLoadFailure(types.ModuleType):
            def __getattr__(self, name):
                raise RuntimeError("Failed to load shared library 'llama.dll'")

        with unittest.mock.patch.dict(sys.modules, {"llama_cpp": _DllLoadFailure("llama_cpp")}):
            sys.modules.pop("llama_cpp.llama_cpp", None)
            self.assertFalse(supports_gpu_offload())

    def test_returns_false_instead_of_raising_if_the_capability_check_itself_errors(self):
        fake_lib = types.ModuleType("llama_cpp.llama_cpp")

        def _boom():
            raise OSError("no CUDA-capable device")

        fake_lib.llama_supports_gpu_offload = _boom
        fake_pkg = types.ModuleType("llama_cpp")
        fake_pkg.llama_cpp = fake_lib
        with unittest.mock.patch.dict(sys.modules, {"llama_cpp": fake_pkg, "llama_cpp.llama_cpp": fake_lib}):
            self.assertFalse(supports_gpu_offload())


class TestLoadDllFailure(unittest.TestCase):
    def test_native_library_load_failure_becomes_a_readable_error(self):
        class _DllLoadFailure(types.ModuleType):
            def __getattr__(self, name):
                raise RuntimeError("Failed to load shared library 'llama.dll'")

        engine = LocalStoryEngine()
        with unittest.mock.patch.dict(sys.modules, {"llama_cpp": _DllLoadFailure("llama_cpp")}), \
                unittest.mock.patch.object(engine_module, "_ensure_cuda_dlls_discoverable"):
            with self.assertRaises(RuntimeError) as ctx:
                engine.load("whatever.gguf")
        self.assertIn("no se pudo cargar su librería nativa", str(ctx.exception))
        self.assertIn("Failed to load shared library", str(ctx.exception))


class TestFitTextToTokenBudget(unittest.TestCase):
    def test_shrinks_until_it_fits_when_tokenizer_exceeds_the_estimate(self):
        # 3 tokens por palabra (la estimacion es 1.4): antes el bucle solo
        # movia palabras de la cabeza a la cola sin achicar el total, y
        # devolvia un texto que seguia sin caber.
        engine = LocalStoryEngine()
        engine._count_tokens = lambda text: len(text.split()) * 3
        text = " ".join(f"w{i}" for i in range(5000))
        trimmed = engine._fit_text_to_token_budget(text, 600)
        self.assertLessEqual(engine._count_tokens(trimmed), 600)
        self.assertIn("w0", trimmed)
        self.assertIn("w4999", trimmed)

    def test_text_that_fits_is_untouched(self):
        engine = LocalStoryEngine()
        self.assertEqual(engine._fit_text_to_token_budget("a few words", 100), "a few words")


class TestStopSequences(unittest.TestCase):
    def test_expand_field_does_not_stop_at_chapter_headings(self):
        engine = LocalStoryEngine()
        engine._llm = StopHonoringFakeLlama(lambda p: "Chapter 1: intro.\n\nChapter 2: the twist.")
        result = engine.expand_field("plot", "a twist story", max_words=100)
        self.assertIn("the twist", result)
        self.assertNotIn("\n\nChapter", engine._llm.stops[0])

    def test_chapter_prose_still_uses_the_default_chapter_stop(self):
        engine = LocalStoryEngine()
        engine._llm = StopHonoringFakeLlama(lambda p: "word " * 150)
        engine.generate_chapter(make_project(target_words=100), 0)
        self.assertIn("\n\nChapter", engine._llm.stops[0])


class TestChapterLengthCap(unittest.TestCase):
    def test_last_section_does_not_push_a_max_length_chapter_over_the_limit(self):
        from app.project import MAX_WORDS_PER_CHAPTER, count_words
        engine = LocalStoryEngine()
        # Responde siempre todo lo que max_tokens permite.
        engine._llm = StopHonoringFakeLlama(lambda p: " ".join(["word"] * 5000))
        project = make_project(target_words=MAX_WORDS_PER_CHAPTER)
        result = engine.generate_chapter(project, 0)
        self.assertLessEqual(count_words(result), MAX_WORDS_PER_CHAPTER)
        self.assertGreater(count_words(result), MAX_WORDS_PER_CHAPTER - 200)


if __name__ == "__main__":
    unittest.main()
