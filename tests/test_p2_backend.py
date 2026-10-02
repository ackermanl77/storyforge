"""
Regresiones de la ronda P2 del informe de mejoras (motor, proyecto, GGUF,
preferencias): B6 muestreo/semilla, B8 lorebook, B9 detener, B10 modelos,
B11 formato de proyecto, B13 conteo incremental, F2 estadisticas, F7 nota
del autor / reescribir seleccion, B4 completar esquema, P1/P2 opciones de
carga y VRAM, R4 reintentos de os.replace.
"""
import json
import os
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import gguf
from app.engine import LocalStoryEngine, OperationCancelled
from app.fileutil import replace_with_retry
from app.project import (
    FORMAT_VERSION,
    LoreEntry,
    Project,
    count_words,
    portable_model_path,
    resolve_model_path,
)
from app.prompts import (
    build_chapter_continuation_chat,
    build_chapter_start_chat,
    match_lore_entries,
)
from app.sampling import (
    PRESET_CUSTOM,
    PRESET_PRECISE,
    PROSE_PRESETS,
    TASK_DEFAULTS,
    TASK_SUMMARY,
    SamplingConfig,
    SamplingSettings,
    parse_seed,
)

BUDGET = dict(max_plot_words=1200, max_characters_words=600, max_setting_words=600,
              max_previous_words=500, max_outline_words=400, tail_words=400, max_lore_words=200)


class RecordingLlama:
    """Doble de llama_cpp.Llama: registra los kwargs de cada llamada y, con
    stream=True, devuelve un fragmento por "token" (palabra)."""

    def __init__(self, text="alpha beta gamma delta epsilon.", finish="stop", on_chunk=None):
        self.text = text
        self.finish = finish
        self.calls = []
        self.on_chunk = on_chunk

    def __call__(self, prompt, **kwargs):
        self.calls.append(dict(kwargs, prompt=prompt))
        if not kwargs.get("stream"):
            return {"choices": [{"text": self.text, "finish_reason": self.finish}]}
        return self._stream()

    def _stream(self):
        words = self.text.split(" ")
        for i, word in enumerate(words):
            if self.on_chunk:
                self.on_chunk(i)
            last = i == len(words) - 1
            yield {"choices": [{"text": (" " if i else "") + word, "finish_reason": self.finish if last else None}]}


def _project(target=100):
    p = Project(plot="A hero's journey.", characters="Ana, a knight.", setting="A castle.")
    p.add_chapter("Start", target)
    return p


class TestSampling(unittest.TestCase):
    def test_each_task_uses_its_own_sampler(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama()
        engine.summarize("Some chapter text to summarize.")
        call = engine._llm.calls[-1]
        self.assertEqual(call["temperature"], TASK_DEFAULTS[TASK_SUMMARY].temperature)
        self.assertIn("min_p", call)
        engine.generate_chapter(_project(target=5), 0)
        prose = engine._llm.calls[-1]
        self.assertEqual(prose["temperature"], PROSE_PRESETS["Equilibrado"].temperature)
        self.assertEqual(prose["repeat_penalty"], PROSE_PRESETS["Equilibrado"].repeat_penalty)

    def test_presets_and_custom(self):
        cfg = SamplingConfig(preset=PRESET_PRECISE)
        self.assertEqual(cfg.prose(), PROSE_PRESETS[PRESET_PRECISE])
        cfg = SamplingConfig(preset=PRESET_CUSTOM, custom_prose=SamplingSettings(temperature=1.3))
        self.assertEqual(cfg.prose().temperature, 1.3)

    def test_fixed_seed_is_passed_and_random_seed_is_recorded(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama()
        engine.sampling = SamplingConfig(seed=1234)
        engine.expand_field("plot", "an idea")
        self.assertEqual(engine._llm.calls[-1]["seed"], 1234)
        self.assertEqual(engine.last_seed, 1234)
        engine.sampling = SamplingConfig(seed=None)
        engine.expand_field("plot", "an idea")
        used = engine._llm.calls[-1]["seed"]
        self.assertIsInstance(used, int)
        self.assertEqual(engine.last_seed, used)
        self.assertEqual(engine.stats.seed, used)

    def test_from_dict_clamps_and_ignores_garbage(self):
        s = SamplingSettings.from_dict({"temperature": 9, "top_k": "x", "min_p": -1, "bogus": 1})
        self.assertEqual(s.temperature, 2.0)
        self.assertEqual(s.min_p, 0.0)
        self.assertEqual(s.top_k, SamplingSettings().top_k)
        self.assertIsNone(parse_seed(""))
        self.assertIsNone(parse_seed("abc"))
        self.assertEqual(parse_seed(" 42 "), 42)
        cfg = SamplingConfig.from_dict({"preset": "nope", "seed": "7"})
        self.assertEqual((cfg.preset, cfg.seed), ("Equilibrado", 7))


class TestStopAndStats(unittest.TestCase):
    def test_global_stop_cancels_a_summary_mid_stream(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama(text=" ".join(["w"] * 50),
                                     on_chunk=lambda i: engine.request_stop() if i == 3 else None)
        with self.assertRaises(OperationCancelled):
            engine.summarize("text", cancel_check=lambda: False)

    def test_stop_before_the_call_never_calls_the_model(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama()
        engine.request_stop()
        with self.assertRaises(OperationCancelled):
            engine.refine_chapter(_project(), 0, "darker", cancel_check=lambda: False)
        self.assertEqual(engine._llm.calls, [])
        engine.clear_stop()
        self.assertFalse(engine.stop_requested)

    def test_outline_and_expand_accept_cancel_check(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama()
        with self.assertRaises(OperationCancelled):
            engine.generate_outline(_project(), 3, cancel_check=lambda: True)
        with self.assertRaises(OperationCancelled):
            engine.expand_field("plot", "x", cancel_check=lambda: True)

    def test_refine_reports_part_progress(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama()
        parts = []
        engine.refine_chapter(_project(), 0, "darker", progress_callback=lambda i, n: parts.append((i, n)))
        self.assertEqual(parts, [(1, 1)])

    def test_stats_record_prompt_tokens_speed_and_context(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama(text=" ".join(f"w{i}" for i in range(30)))
        engine._n_ctx = 4096
        engine.generate_chapter(_project(target=20), 0, progress_callback=lambda *a: None)
        stats = engine.stats
        self.assertTrue(stats.finished)
        self.assertGreater(stats.prompt_tokens, 0)
        self.assertEqual(stats.generated_tokens, 30)
        self.assertEqual(stats.budget_level, 1)
        self.assertIn("Start", stats.prompt_text)
        self.assertGreater(stats.context_fraction, 0)
        self.assertEqual(stats.operation, "Capítulo 1")
        self.assertEqual(stats.target_words, 20)


class TestIncrementalWordCount(unittest.TestCase):
    """B13: el conteo durante el streaming es incremental y coincide con el exacto."""

    def test_counts_match_with_words_split_across_chunks(self):
        class SplitLlama(RecordingLlama):
            def _stream(self):
                for chunk in ["Hel", "lo wor", "ld, it", "'s fi", "ne. ", "Done", "."]:
                    yield {"choices": [{"text": chunk, "finish_reason": None}]}
                yield {"choices": [{"text": "", "finish_reason": "stop"}]}

        engine = LocalStoryEngine()
        engine._llm = SplitLlama()
        seen = []
        engine.generate_chapter(_project(target=6), 0, progress_callback=lambda t, w, _: seen.append((t, w)))
        for text, words in seen:
            self.assertEqual(words, count_words(text), text)

    def test_resume_counts_include_existing_text(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama(text="one two three.")
        seen = []
        engine.generate_chapter(_project(target=200), 0, resume_from="Already four words here.",
                                progress_callback=lambda t, w, _: seen.append((t, w)))
        self.assertTrue(all(w == count_words(t) for t, w in seen))


class TestLorebookB8(unittest.TestCase):
    def test_disabled_constant_priority_and_recursion(self):
        sword = LoreEntry(name="Dawnblade", keywords="Dawnblade", text="A holy sword.")
        ana = LoreEntry(name="Ana", keywords="Ana", text="A knight who carries Dawnblade.", priority=1)
        rules = LoreEntry(name="Rules", keywords="", text="Magic costs blood.", constant=True)
        off = LoreEntry(name="Off", keywords="castle", text="x", enabled=False)
        low = LoreEntry(name="Castle", keywords="castle", text="Old castle.", priority=-1)
        matches = match_lore_entries([sword, ana, rules, off, low], "Ana walks to the castle.")
        names = [m.entry.name for m in matches]
        self.assertEqual(names[0], "Rules")  # siempre incluida primero
        self.assertNotIn("Off", names)
        self.assertLess(names.index("Ana"), names.index("Castle"))  # prioridad
        self.assertIn("Dawnblade", names)  # recursiva, via la entrada de Ana
        dawn = next(m for m in matches if m.entry.name == "Dawnblade")
        self.assertEqual(dawn.via, "Ana")
        self.assertIn("Ana", dawn.reason_es())

    def test_recency_breaks_priority_ties(self):
        a = LoreEntry(name="A", keywords="alpha")
        b = LoreEntry(name="B", keywords="beta")
        names = [m.entry.name for m in match_lore_entries([a, b], "alpha ... later beta")]
        self.assertEqual(names, ["B", "A"])

    def test_continuation_prompt_scans_the_chapter_so_far(self):
        p = _project()
        p.lore_entries.append(LoreEntry(name="Dragon", keywords="dragon", text="LORE_MARKER"))
        start = build_chapter_start_chat(p, 0, BUDGET)
        self.assertNotIn("LORE_MARKER", start.system)
        cont = build_chapter_continuation_chat(p, 0, BUDGET, "Then a dragon landed.", 100, 400)
        self.assertIn("LORE_MARKER", cont.system)


class TestAuthorNoteF7(unittest.TestCase):
    def test_note_goes_at_the_end_of_the_user_turn(self):
        p = _project()
        p.author_note = "Keep it tense."
        p.chapters[0].author_note = "Ana is wounded."
        start = build_chapter_start_chat(p, 0, BUDGET)
        self.assertTrue(start.user.rstrip().endswith("Keep it tense. Ana is wounded."))
        self.assertIn("AUTHOR'S NOTE", start.raw)
        cont = build_chapter_continuation_chat(p, 0, BUDGET, "Some text.", 100, 400)
        self.assertTrue(cont.user.rstrip().endswith("Ana is wounded."))
        self.assertNotIn("AUTHOR'S NOTE", cont.system)

    def test_no_note_leaves_raw_prompt_unchanged(self):
        raw = build_chapter_start_chat(_project(), 0, BUDGET).raw
        self.assertTrue(raw.endswith("words. \n\nBegin the chapter now:\n"))

    def test_rewrite_span_sends_selection_and_context(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama(text="NEW PASSAGE")
        out = engine.rewrite_span(_project(), 0, "Before text.", "The old passage.", "After text.", mode="shorten")
        self.assertEqual(out, "NEW PASSAGE")
        prompt = engine._llm.calls[-1]["prompt"]
        for piece in ("Before text.", "The old passage.", "After text.", "Condense"):
            self.assertIn(piece, prompt)


class TestCompleteOutlineB4(unittest.TestCase):
    def test_returns_only_the_missing_chapters(self):
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama(
            text="Chapter 1: Start\nRepeated.\n\nChapter 3: Middle\nThings happen.\n\nChapter 4: End\nIt ends."
        )
        existing = [("Start", "Begin."), ("Second", "More.")]
        items = engine.complete_outline(_project(), 4, existing)
        self.assertEqual([t for t, _ in items], ["Middle", "End"])
        prompt = engine._llm.calls[-1]["prompt"]
        self.assertIn("Chapter 2: Second", prompt)
        self.assertIn("from Chapter 3 to Chapter 4", prompt)
        self.assertEqual(engine.complete_outline(_project(), 2, existing), [])


def _write_gguf(path, metadata):
    """GGUF v3 minimo: cabecera + pares clave/valor (strings, uint32, arreglos)."""
    def s(text):
        b = text.encode("utf-8")
        return struct.pack("<Q", len(b)) + b

    body = b""
    for key, value in metadata.items():
        body += s(key)
        if isinstance(value, str):
            body += struct.pack("<I", 8) + s(value)
        elif isinstance(value, list):
            body += struct.pack("<I", 9) + struct.pack("<I", 8) + struct.pack("<Q", len(value))
            body += b"".join(s(v) for v in value)
        else:
            body += struct.pack("<I", 4) + struct.pack("<I", value)
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, len(metadata)) + body)


class TestGgufB10(unittest.TestCase):
    def test_header_reader_and_model_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.gguf")
            _write_gguf(path, {
                "general.architecture": "llama", "general.name": "Tiny",
                "llama.context_length": 8192, "llama.block_count": 32,
                "llama.attention.head_count": 32, "llama.attention.head_count_kv": 8,
                "llama.embedding_length": 4096, "general.file_type": 7,
                "tokenizer.ggml.tokens": [f"t{i}" for i in range(100)],
            })
            meta = gguf.read_gguf_metadata(path)
            self.assertEqual(meta["tokenizer.ggml.tokens"], {"array_length": 100})
            info = gguf.model_info(path)
        self.assertEqual((info.architecture, info.trained_context, info.n_layers), ("llama", 8192, 32))
        self.assertEqual((info.n_head_kv, info.head_dim, info.quantization), (8, 128, "Q8_0"))
        self.assertFalse(info.has_chat_template)
        self.assertIn("contexto entrenado 8,192", info.summary_es())

    def test_not_a_gguf(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
            f.write(b"nope")
        try:
            with self.assertRaises(gguf.GGUFError):
                gguf.read_gguf_metadata(f.name)
            self.assertTrue(gguf.model_info(f.name).error)
        finally:
            os.remove(f.name)

    def test_split_models_are_grouped_and_incomplete_sets_flagged(self):
        from app.engine import find_local_models
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("solo.gguf", "big-00001-of-00002.gguf", "big-00002-of-00002.gguf",
                         "orphan-00002-of-00002.gguf", "notes.txt"):
                open(os.path.join(tmp, name), "wb").close()
            entries = gguf.list_model_entries(tmp)
            labels = {os.path.basename(e.path): e for e in entries}
            self.assertEqual(set(labels), {"solo.gguf", "big-00001-of-00002.gguf", "orphan-00001-of-00002.gguf"})
            self.assertTrue(labels["big-00001-of-00002.gguf"].complete)
            self.assertIn("2 partes", labels["big-00001-of-00002.gguf"].label)
            self.assertEqual(labels["orphan-00001-of-00002.gguf"].missing_parts, [1])
            self.assertIn("incompleto", labels["orphan-00001-of-00002.gguf"].label)
            loadable = [os.path.basename(p) for p in find_local_models(tmp)]
            self.assertEqual(sorted(loadable), ["big-00001-of-00002.gguf", "solo.gguf"])

    def test_vram_estimate(self):
        info = gguf.ModelInfo(path="x", size_bytes=8 * 1024**3, n_layers=32, n_head_kv=8, head_dim=128)
        kv = gguf.estimate_kv_bytes(info, 8192, "f16")
        self.assertEqual(kv, 8192 * 32 * 8 * 128 * 2 * 2)  # 1 GiB
        self.assertLess(gguf.estimate_kv_bytes(info, 8192, "q8_0"), kv)
        fits = gguf.estimate_vram(info, 8192, "f16", free_vram_bytes=16 * 1024**3)
        self.assertEqual((fits.fits_fully, fits.suggested_gpu_layers), (True, -1))
        partial = gguf.estimate_vram(info, 8192, "f16", free_vram_bytes=5 * 1024**3)
        self.assertFalse(partial.fits_fully)
        self.assertTrue(0 < partial.suggested_gpu_layers < 32)
        self.assertIn("capas en GPU", partial.message)
        huge = gguf.estimate_vram(gguf.ModelInfo(path="x", size_bytes=50 * 1024**3, n_layers=80),
                                  8192, free_vram_bytes=1024**3, total_ram_bytes=16 * 1024**3)
        self.assertIn("ATENCION", huge.message)
        unknown = gguf.estimate_vram(info, 8192)
        self.assertIsNone(unknown.suggested_gpu_layers)

    def test_friendly_errors(self):
        self.assertIn("memoria", gguf.friendly_load_error(RuntimeError("CUDA error: out of memory")))
        self.assertIn("arquitectura", gguf.friendly_load_error(ValueError("unknown model architecture: 'x'")))
        self.assertIn("Detalle: Failed to load model from file",
                      gguf.friendly_load_error(ValueError("Failed to load model from file: m.gguf")))


class TestLoadOptionsP1(unittest.TestCase):
    def _load(self, **kwargs):
        engine = LocalStoryEngine()
        captured = {}

        class FakeLlama:
            def __init__(self, **kw):
                captured.update(kw)

            def n_ctx(self):
                return 4096

        fake_module = types.ModuleType("llama_cpp")
        fake_module.Llama = FakeLlama
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"llama_cpp": fake_module}):
            path = os.path.join(tmp, "m.gguf")
            open(path, "wb").close()
            engine.load(path, **kwargs)
        return engine, captured

    def test_gpu_defaults_flash_attention_and_passes_kv_type(self):
        engine, kw = self._load(n_gpu_layers=-1, n_batch=1024, n_ubatch=512, kv_cache_type="q8_0")
        self.assertTrue(kw["flash_attn"])
        self.assertEqual((kw["type_k"], kw["type_v"]), (8, 8))
        self.assertEqual((kw["n_batch"], kw["n_ubatch"]), (1024, 512))
        self.assertEqual(engine.n_ctx, 4096)  # el real, no el pedido
        self.assertEqual(engine.load_options["kv_cache_type"], "q8_0")

    def test_cpu_load_passes_no_extra_options(self):
        _engine, kw = self._load(n_gpu_layers=0)
        for key in ("flash_attn", "type_k", "type_v", "n_batch"):
            self.assertNotIn(key, kw)

    def test_quantized_kv_requires_flash_attention(self):
        engine = LocalStoryEngine()
        with self.assertRaises(ValueError):
            engine.load("x.gguf", n_gpu_layers=0, kv_cache_type="q4_0", flash_attn=False)

    def test_missing_shard_is_refused_with_a_clear_message(self):
        engine = LocalStoryEngine()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big-00001-of-00002.gguf")
            open(path, "wb").close()
            fake_module = types.ModuleType("llama_cpp")
            fake_module.Llama = lambda **kw: self.fail("must not construct")
            with mock.patch.dict(sys.modules, {"llama_cpp": fake_module}):
                with self.assertRaises(RuntimeError) as ctx:
                    engine.load(path)
        self.assertIn("faltan las partes 2", str(ctx.exception))

    def test_construction_errors_are_translated(self):
        engine = LocalStoryEngine()

        def boom(**kw):
            raise ValueError("Failed to load model from file: m.gguf")

        fake_module = types.ModuleType("llama_cpp")
        fake_module.Llama = boom
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"llama_cpp": fake_module}):
            path = os.path.join(tmp, "m.gguf")
            open(path, "wb").close()
            with self.assertRaises(RuntimeError) as ctx:
                engine.load(path)
        self.assertIn("OneDrive", str(ctx.exception))


class TestProjectFormatB11(unittest.TestCase):
    def test_format_version_and_new_fields_round_trip(self):
        p = _project()
        p.author = "Ana"
        p.author_note = "Dark."
        p.sampling = SamplingConfig(preset=PRESET_PRECISE, seed=9)
        p.context_size = 16384
        p.lore_entries.append(LoreEntry(name="X", keywords="x", constant=True, priority=3, enabled=False))
        p.chapters[0].content = "v1"
        p.push_chapter_history(p.chapters[0], "refinar: darker")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            p.save(path)
            data = json.loads(open(path, encoding="utf-8").read())
            loaded = Project.load(path)
        self.assertEqual(data["format_version"], FORMAT_VERSION)
        self.assertEqual(data["chapters"][0]["history"][0]["source"], "refinar: darker")
        self.assertEqual((loaded.author, loaded.author_note, loaded.context_size), ("Ana", "Dark.", 16384))
        self.assertEqual((loaded.sampling.preset, loaded.sampling.seed), (PRESET_PRECISE, 9))
        e = loaded.lore_entries[0]
        self.assertEqual((e.constant, e.priority, e.enabled), (True, 3, False))
        self.assertEqual(loaded.chapters[0].history_entries()[0]["source"], "refinar: darker")

    def test_old_format_and_bad_types_load_with_defaults(self):
        data = {
            "name": None, "plot": 5, "characters": ["bad"], "chapters": [
                {"title": "A", "target_words": "lots", "history": ["old text", 3]}, "garbage",
            ],
            "lore_entries": None, "sampling": "x", "history_limit": 9999,
        }
        with self.assertLogs("app.project", level="WARNING"):
            p = Project.from_dict(data)
        self.assertEqual(p.plot, "5")
        self.assertEqual(p.characters, "")
        self.assertEqual(len(p.chapters), 1)
        self.assertEqual(p.chapters[0].target_words, 2000)
        self.assertEqual(p.chapters[0].history, ["old text"])
        self.assertEqual(p.lore_entries, [])
        self.assertEqual(p.history_limit, 100)
        with self.assertRaises(ValueError):
            Project.from_dict(["not", "a", "project"])

    def test_history_limit(self):
        p = _project()
        p.history_limit = 2
        ch = p.chapters[0]
        for i in range(4):
            ch.content = f"v{i}"
            p.push_chapter_history(ch, f"s{i}")
        self.assertEqual(ch.history, ["v2", "v3"])
        self.assertEqual([m["source"] for m in ch.history_meta], ["s2", "s3"])

    def test_model_path_is_stored_relative_to_models_dir(self):
        with tempfile.TemporaryDirectory() as models:
            inside = os.path.join(models, "sub", "m.gguf")
            self.assertEqual(portable_model_path(inside, models), "sub/m.gguf")
            self.assertEqual(os.path.normcase(resolve_model_path("sub/m.gguf", models)), os.path.normcase(inside))
        outside = os.path.abspath(os.path.join(os.sep, "elsewhere", "m.gguf"))
        self.assertEqual(portable_model_path(outside, models), outside)
        self.assertEqual(resolve_model_path(outside, models), outside)


class TestSettingsAndFiles(unittest.TestCase):
    def test_model_settings_round_trip(self):
        from app import settings
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"STORYFORGE_USER_DATA_DIR": tmp}):
            settings.set_model_settings("C:/m/Model.gguf", {"n_gpu_layers": 20, "kv_cache_type": "q8_0", "junk": 1})
            self.assertEqual(settings.get_model_settings("model.gguf"), {"n_gpu_layers": 20, "kv_cache_type": "q8_0"})
            self.assertEqual(settings.get_last_model(), "C:/m/Model.gguf")
            settings.set_ui_preferences({"appearance": "light", "ui_scale": "huge"})
            prefs = settings.get_ui_preferences()
            self.assertEqual(prefs["appearance"], "light")
            self.assertEqual(prefs["ui_scale"], 1.0)

    def test_replace_retries_on_permission_error(self):
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("locked by OneDrive")

        with mock.patch("app.fileutil.os.replace", side_effect=flaky):
            replace_with_retry("a", "b", sleep=lambda s: None)
        self.assertEqual(len(calls), 3)
        with mock.patch("app.fileutil.os.replace", side_effect=PermissionError("x")):
            with self.assertRaises(PermissionError):
                replace_with_retry("a", "b", retries=2, sleep=lambda s: None)


if __name__ == "__main__":
    unittest.main()
