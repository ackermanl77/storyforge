"""
Regression tests for the P1 generation-quality fixes from
improvement_reports/storyforge.md:

- B1: previous-chapters context keeps the NEWEST summaries (and the ending of
  chapter N-1) at every context-budget level.
- B2: summaries know when they are stale; long chapters are summarized in
  parts (map-reduce) instead of head/tail-trimmed.
- B3: prompts are rendered through the model's chat template (GGUF Jinja
  template, special-token detection, presets) with a raw fallback.
- B4: finish_reason is read; a section cut by max_tokens is joined without a
  paragraph break; a natural early end is honored or nudged.
- B5: continue/resume from existing text, with a dynamic tail that fills the
  free context.

No real model is loaded: ChatFakeLlama below is a llama_cpp.Llama stand-in
that honors stop/max_tokens/stream, reports finish_reason, and exposes
metadata/tokenize/detokenize so chat-template detection is exercised.
"""
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.engine as engine_module
from app.chat_format import (
    CHAT_FORMAT_CHATML,
    CHAT_FORMAT_RAW,
    ChatMLFormatter,
    JinjaTemplateFormatter,
    Llama3Formatter,
    MistralFormatter,
    RawFormatter,
    chat_format_from_label,
    detect_formatter,
)
from app.engine import CONTEXT_BUDGET_LEVELS, LocalStoryEngine
from app.project import Chapter, LoreEntry, Project, count_words
from app.prompts import (
    NOT_OVER_NUDGE,
    ChatPrompt,
    build_beat_progress_hint,
    build_chapter_system_prompt,
    build_previous_context,
    tail_preserving_format,
)

LLAMA3_SPECIALS = {"<|start_header_id|>": 1, "<|end_header_id|>": 2, "<|eot_id|>": 3, "<|begin_of_text|>": 4}
CHATML_SPECIALS = {"<|im_start|>": 1, "<|im_end|>": 2}


class ChatFakeLlama:
    """
    llama_cpp.Llama stand-in with the bits chat-template support relies on:
    `metadata` (optionally a tokenizer.chat_template), `tokenize(..., special=
    True)` that maps known special tokens to ONE token, token_bos/token_eos +
    detokenize. It honors `stop` and `max_tokens` (1 token == 1 word), reports
    finish_reason like llama.cpp, and streams when stream=True.
    `respond(prompt, call_index)` returns the model's "full" answer.
    """

    def __init__(self, respond, specials=None, chat_template=None, bos="<|begin_of_text|>", eos="<|eot_id|>"):
        self.respond = respond
        self.specials = dict(specials or {})
        self.metadata = {"tokenizer.chat_template": chat_template} if chat_template else {}
        self.bos, self.eos = bos, eos
        self.prompts, self.stops, self.max_tokens = [], [], []
        self.closed = False

    # --- vocab ---
    def tokenize(self, text, add_bos=True, special=False):
        s = text.decode("utf-8")
        if special and s in self.specials:
            return [self.specials[s]]
        if special:
            # Not in this fake vocab: "<|im_start|>" etc. become several tokens.
            return list(range(max(2, len(s.split()))))
        return list(range(len(s.split())))

    def token_bos(self):
        return 100

    def token_eos(self):
        return 101

    def detokenize(self, tokens, special=False):
        return {100: self.bos, 101: self.eos}.get(tokens[0], "").encode("utf-8")

    def close(self):
        self.closed = True

    # --- completion ---
    def __call__(self, prompt, max_tokens=0, stop=None, stream=False, **kwargs):
        self.prompts.append(prompt)
        self.stops.append(stop)
        self.max_tokens.append(max_tokens)
        text = self.respond(prompt, len(self.prompts) - 1)
        finish = "stop"
        cut = min((text.find(s) for s in (stop or []) if s in text), default=-1)
        if cut >= 0:
            text = text[:cut]
        words = text.split(" ")
        if len(words) > max_tokens:
            text = " ".join(words[:max_tokens])
            finish = "length"
        if not stream:
            return {"choices": [{"text": text, "finish_reason": finish}]}
        return self._stream(text, finish)

    @staticmethod
    def _stream(text, finish):
        parts = text.split(" ")
        for i, part in enumerate(parts):
            yield {"choices": [{"text": (" " if i else "") + part, "finish_reason": None}]}
        yield {"choices": [{"text": "", "finish_reason": finish}]}


def _project_with_chapters(n, summary_words=150, content=""):
    p = Project(plot="A long saga.", characters="Hero", setting="A kingdom")
    for i in range(n):
        ch = p.add_chapter(f"Title{i + 1}", target_words=400)
        ch.summary = " ".join([f"SUM{i + 1}"] + ["filler"] * (summary_words - 1))
        ch.content = content
    return p


# ---------------------------------------------------------------- B1
class TestPreviousContextKeepsNewest(unittest.TestCase):
    def test_previous_chapter_present_at_every_budget_level(self):
        # Before: chapters were joined oldest-first and trimmed keeping the
        # START, so chapter 5 was missing at all three levels.
        project = _project_with_chapters(6)
        for budget in CONTEXT_BUDGET_LEVELS:
            context = build_previous_context(project, 5, budget["max_previous_words"])
            self.assertIn("SUM5", context, f"chapter 5 missing at {budget['max_previous_words']} words")
            prompt = build_chapter_system_prompt(project, 5, max_previous_words=budget["max_previous_words"])
            self.assertIn("SUM5", prompt)

    def test_newest_summaries_win_and_older_ones_are_listed_by_title(self):
        project = _project_with_chapters(6)
        context = build_previous_context(project, 5, 300)
        self.assertIn("SUM4", context)
        self.assertNotIn("SUM1 ", context)
        self.assertIn("Earlier chapters", context)
        self.assertIn("Chapter 1 (Title1)", context)
        self.assertLess(context.index("Chapter 1 (Title1)"), context.index("SUM5"))  # chronological

    def test_includes_the_literal_ending_of_the_previous_chapter(self):
        project = _project_with_chapters(3, summary_words=20)
        project.chapters[1].content = " ".join(f"w{i}" for i in range(1000)) + " FINAL_WORDS."
        context = build_previous_context(project, 2, 500)
        self.assertIn("FINAL_WORDS.", context)
        self.assertIn("w999", context)
        self.assertNotIn("w0 ", context)

    def test_missing_summary_uses_the_end_of_the_chapter_not_the_start(self):
        project = _project_with_chapters(3, summary_words=20)
        project.chapters[0].summary = ""
        project.chapters[0].content = "START_MARKER " + "word " * 500 + "END_MARKER"
        context = build_previous_context(project, 2, 500)
        self.assertIn("END_MARKER", context)
        self.assertNotIn("START_MARKER", context)

    def test_first_chapter_message_unchanged(self):
        self.assertEqual(build_previous_context(_project_with_chapters(2), 0), "This is the first chapter of the story.")

    def test_lore_keyed_to_a_recent_chapter_now_triggers(self):
        project = _project_with_chapters(6)
        project.chapters[4].summary = "The dragon burned the mill. " + "filler " * 140
        project.lore_entries.append(LoreEntry(name="Dragon", keywords="dragon", text="LORE_MARKER"))
        prompt = build_chapter_system_prompt(project, 5, max_previous_words=150)
        self.assertIn("LORE_MARKER", prompt)


# ---------------------------------------------------------------- B2
class TestSummaryStaleness(unittest.TestCase):
    def test_changing_content_makes_the_summary_stale(self):
        ch = Chapter(content="Original text.")
        ch.set_summary("A summary.")
        self.assertFalse(ch.summary_is_stale())
        self.assertFalse(ch.needs_summary())
        ch.content = "Refined text."
        self.assertTrue(ch.summary_is_stale())
        self.assertTrue(ch.needs_summary())

    def test_whitespace_only_changes_do_not_count(self):
        ch = Chapter(content="Text.")
        ch.set_summary("S")
        ch.content = "Text.\n"
        self.assertFalse(ch.summary_is_stale())

    def test_missing_summary_needs_one_only_if_there_is_content(self):
        self.assertFalse(Chapter().needs_summary())
        self.assertTrue(Chapter(content="x").needs_summary())

    def test_hash_roundtrips_and_legacy_projects_are_assumed_fresh(self):
        ch = Chapter(content="Text.")
        ch.set_summary("S")
        again = Chapter.from_dict(ch.to_dict())
        self.assertEqual(again.summary_source_hash, ch.summary_source_hash)
        legacy = Chapter.from_dict({"content": "Old text.", "summary": "Old summary."})
        self.assertFalse(legacy.summary_is_stale())

    def test_project_save_load_keeps_staleness(self):
        p = Project()
        ch = p.add_chapter("A")
        ch.content = "v1"
        ch.set_summary("s1")
        ch.content = "v2"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.json")
            p.save(path)
            self.assertTrue(Project.load(path).chapters[0].summary_is_stale())


class TestSummarizeLongChapterInParts(unittest.TestCase):
    def test_middle_of_a_long_chapter_reaches_the_summary(self):
        # Before: head/tail trimming meant the middle events never reached
        # the summarizer at all.
        def respond(prompt, i):
            if "Combine them" in prompt:
                return "COMBINED"
            markers = [w for w in prompt.split() if w.startswith("EVENT")]
            return "part summary " + " ".join(markers)

        llm = ChatFakeLlama(respond)
        engine = LocalStoryEngine()
        engine._llm = llm
        engine._n_ctx = 1500
        paragraphs = [f"EVENT{i} " + "word " * 199 for i in range(20)]  # 4,000 words
        result = engine.summarize("\n\n".join(paragraphs), max_words=100)

        self.assertEqual(result, "COMBINED")
        seen = " ".join(llm.prompts[:-1])
        for i in range(20):
            self.assertIn(f"EVENT{i} ", seen)
        self.assertIn("EVENT10", llm.prompts[-1])  # the combine step sees the middle too
        self.assertGreater(len(llm.prompts), 2)

    def test_short_chapter_is_a_single_call(self):
        llm = ChatFakeLlama(lambda p, i: "short summary")
        engine = LocalStoryEngine()
        engine._llm = llm
        self.assertEqual(engine.summarize("A short chapter."), "short summary")
        self.assertEqual(len(llm.prompts), 1)


# ---------------------------------------------------------------- B3
LLAMA31_LIKE_TEMPLATE = (
    "{{ bos_token }}{% for m in messages %}<|start_header_id|>{{ m['role'] }}<|end_header_id|>\n\n"
    "{{ m['content'] }}<|eot_id|>{% endfor %}"
    "{% if add_generation_prompt %}<|start_header_id|>assistant<|end_header_id|>\n\n{% endif %}"
)
NO_SYSTEM_TEMPLATE = (
    "{% for m in messages %}{% if m['role'] == 'system' %}{{ raise_exception('no system role') }}{% endif %}"
    "<start_of_turn>{{ m['role'] }}\n{{ m['content'] }}<end_of_turn>\n{% endfor %}"
    "{% if add_generation_prompt %}<start_of_turn>model\n{% endif %}"
)


class TestChatFormatDetection(unittest.TestCase):
    def test_gguf_template_is_used_and_bos_is_not_duplicated(self):
        fmt = detect_formatter({"tokenizer.chat_template": LLAMA31_LIKE_TEMPLATE}, lambda t: False,
                               bos_token="<|begin_of_text|>", eos_token="<|eot_id|>")
        self.assertIsInstance(fmt, JinjaTemplateFormatter)
        text = fmt.render(ChatPrompt(system="SYS", user="USR", prefill="Once upon"))
        self.assertFalse(text.startswith("<|begin_of_text|>"))  # llama.cpp adds BOS itself
        self.assertIn("<|start_header_id|>system<|end_header_id|>\n\nSYS<|eot_id|>", text)
        self.assertTrue(text.endswith("<|start_header_id|>assistant<|end_header_id|>\n\nOnce upon"))
        self.assertIn("<|eot_id|>", fmt.stop)

    def test_template_without_system_role_merges_it_into_the_user_turn(self):
        fmt = detect_formatter({"tokenizer.chat_template": NO_SYSTEM_TEMPLATE}, lambda t: False)
        text = fmt.render(ChatPrompt(system="SYS", user="USR"))
        self.assertIn("<start_of_turn>user\nSYS\n\nUSR<end_of_turn>", text)

    def test_llama3_detected_from_special_tokens_when_gguf_has_no_template(self):
        # daredevil-8b's GGUF has no tokenizer.chat_template, but a Llama 3 vocab.
        fmt = detect_formatter({}, lambda t: t in LLAMA3_SPECIALS)
        self.assertIsInstance(fmt, Llama3Formatter)

    def test_chatml_mistral_and_raw_fallbacks(self):
        self.assertIsInstance(detect_formatter({}, lambda t: t in CHATML_SPECIALS), ChatMLFormatter)
        self.assertIsInstance(detect_formatter({}, lambda t: t in ("[INST]", "[/INST]")), MistralFormatter)
        self.assertIsInstance(detect_formatter({}, lambda t: False), RawFormatter)

    def test_raw_formatter_returns_the_legacy_prompt(self):
        prompt = ChatPrompt(system="S", user="U", prefill="P", raw="LEGACY")
        self.assertEqual(RawFormatter().render(prompt), "LEGACY")

    def test_label_roundtrip(self):
        self.assertEqual(chat_format_from_label("ChatML (Qwen, etc.)"), CHAT_FORMAT_CHATML)
        self.assertEqual(chat_format_from_label("???"), "auto")


def _chapter_project(target=300, outline=""):
    p = Project(plot="A hero's journey.", characters="Hero", setting="A village")
    p.add_chapter("Chapter One", target_words=target, outline=outline)
    return p


class TestEngineUsesChatTemplate(unittest.TestCase):
    def test_chapter_prompts_use_llama3_turns_and_prefill_the_continuation(self):
        llm = ChatFakeLlama(lambda p, i: f"Section{i} " + "word " * 120 + "end.", specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        result = engine.generate_chapter(_chapter_project(target=250), 0)

        first, second = llm.prompts[0], llm.prompts[1]
        self.assertTrue(first.startswith("<|start_header_id|>system<|end_header_id|>"))
        self.assertIn("Begin the chapter now", first)
        self.assertTrue(first.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n"))
        # The continuation's assistant turn is pre-filled with the chapter's
        # own ending, so the model continues the prose instead of answering.
        self.assertTrue(second.rstrip().endswith("end."))
        self.assertIn("Section0", second.split("assistant<|end_header_id|>")[-1])
        self.assertIn("<|eot_id|>", llm.stops[0])
        self.assertIn("Section1", result)

    def test_raw_choice_keeps_the_legacy_completion_prompt(self):
        llm = ChatFakeLlama(lambda p, i: "word " * 300, specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        engine.set_chat_format(CHAT_FORMAT_RAW)
        engine.generate_chapter(_chapter_project(target=100), 0)
        self.assertNotIn("<|start_header_id|>", llm.prompts[0])
        self.assertTrue(llm.prompts[0].endswith("Begin the chapter now:\n"))

    def test_outline_summary_expand_and_refine_are_rendered_as_chat(self):
        def respond(prompt, i):
            return "Chapter 1: A\nEvents.\n\nChapter 2: B\nMore." if "outline" in prompt else "ok text."

        llm = ChatFakeLlama(respond, specials=CHATML_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        project = _chapter_project()
        project.chapters[0].content = "Some chapter text."
        engine.generate_outline(project, 2)
        engine.summarize("Some chapter text.")
        engine.expand_field("plot", "an idea")
        engine.refine_chapter(project, 0, "darker")
        for prompt in llm.prompts:
            self.assertTrue(prompt.startswith("<|im_start|>system\n"), prompt[:60])
            self.assertTrue(prompt.endswith("<|im_start|>assistant\n"))
        refine_prompt = llm.prompts[-1]
        user_turn = refine_prompt.split("<|im_start|>user\n")[1]
        self.assertIn("EDITING INSTRUCTION: darker", user_turn)
        self.assertIn("Some chapter text.", user_turn)
        self.assertNotIn("FORMATTING RULES", user_turn)  # style rules live in the system turn

    def test_load_applies_the_chosen_format_and_close_releases_the_old_model(self):
        created = []

        def fake_llama(**kwargs):
            llm = ChatFakeLlama(lambda p, i: "x", specials=LLAMA3_SPECIALS)
            created.append(llm)
            return llm

        fake_module = types.ModuleType("llama_cpp")
        fake_module.Llama = fake_llama
        engine = LocalStoryEngine()
        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as tmp:
            path = tmp.name
        sys.modules["llama_cpp"] = fake_module
        try:
            engine.load(path, chat_format=CHAT_FORMAT_CHATML)
            self.assertIsInstance(engine.formatter, ChatMLFormatter)  # explicit choice beats detection
            engine.load(path, chat_format="auto")
            self.assertIsInstance(engine.formatter, Llama3Formatter)
            self.assertTrue(created[0].closed, "previous model must be close()d, not just dropped")
        finally:
            del sys.modules["llama_cpp"]
            os.remove(path)


# ---------------------------------------------------------------- B4
class TestFinishReasonHandling(unittest.TestCase):
    def test_raw_mode_section_cut_mid_sentence_is_not_split_into_a_new_paragraph(self):
        # SECTION_TARGET_WORDS=160 -> max_tokens=224: the first answer is cut
        # three words into "And a dangling half ...".
        def respond(prompt, i):
            if i == 0:
                return "First sentence here. " + "word " * 215 + "Second sentence ends. And a dangling half " + "x " * 50
            return "continued text that finishes the scene. " + "more " * 100

        llm = ChatFakeLlama(respond)  # no special tokens -> raw completion
        engine = LocalStoryEngine()
        engine._llm = llm
        saved = engine_module.SECTION_TARGET_WORDS
        try:
            engine_module.SECTION_TARGET_WORDS = 160
            result = engine.generate_chapter(_chapter_project(target=300), 0)
        finally:
            engine_module.SECTION_TARGET_WORDS = saved
        self.assertEqual(len(llm.prompts), 2)
        self.assertNotIn("\n\n", result)
        self.assertNotIn("dangling", result)
        self.assertIn("Second sentence ends. continued text", result)

    def test_chat_mode_continuation_is_glued_directly(self):
        def respond(prompt, i):
            if i == 0:
                return "He opened the door and " + "word " * 300
            return " saw the sea. It was calm. " + "more " * 100

        llm = ChatFakeLlama(respond, specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        saved = engine_module.SECTION_TARGET_WORDS
        try:
            engine_module.SECTION_TARGET_WORDS = 160
            result = engine.generate_chapter(_chapter_project(target=250), 0)
        finally:
            engine_module.SECTION_TARGET_WORDS = saved
        self.assertIn("word saw the sea.", result)
        self.assertNotIn("\n\n", result)

    def test_natural_end_near_the_target_finishes_the_chapter(self):
        llm = ChatFakeLlama(lambda p, i: "word " * 90 + "The end.")
        engine = LocalStoryEngine()
        engine._llm = llm
        engine.generate_chapter(_chapter_project(target=100), 0)
        self.assertEqual(len(llm.prompts), 1)

    def test_early_natural_end_gets_a_keep_going_nudge(self):
        llm = ChatFakeLlama(lambda p, i: "word " * 40 + "The end.")
        engine = LocalStoryEngine()
        engine._llm = llm
        engine.generate_chapter(_chapter_project(target=300), 0)
        self.assertGreater(len(llm.prompts), 1)
        self.assertIn(NOT_OVER_NUDGE, llm.prompts[1])

    def test_streamed_finish_reason_is_read(self):
        llm = ChatFakeLlama(lambda p, i: "word " * 5000)
        engine = LocalStoryEngine()
        engine._llm = llm
        engine.generate_chapter(_chapter_project(target=100), 0, progress_callback=lambda *a: None)
        self.assertEqual(engine.last_finish_reason, "length")

    def test_truncated_outline_is_reported(self):
        outline = "\n\n".join(f"Chapter {i}: T{i}\n" + "beat " * 200 for i in range(1, 4))
        llm = ChatFakeLlama(lambda p, i: outline)
        engine = LocalStoryEngine()
        engine._llm = llm
        items = engine.generate_outline(Project(plot="p", characters="c", setting="s"), 3)
        self.assertEqual(engine.last_finish_reason, "length")
        self.assertLess(len(items[-1][1].split()), 200)


# ---------------------------------------------------------------- B5
class TestContinueAndDynamicTail(unittest.TestCase):
    def test_resume_continues_from_existing_text(self):
        llm = ChatFakeLlama(lambda p, i: " and then more happened. " + "word " * 100, specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        existing = "EXISTING_START " + "old " * 50 + "the knight drew his sword"
        result = engine.generate_chapter(_chapter_project(target=200), 0, resume_from=existing)
        self.assertTrue(result.startswith(existing))
        self.assertIn("drew his sword and then more happened.", result)
        self.assertNotIn("Begin the chapter now", llm.prompts[0])
        self.assertTrue(llm.prompts[0].endswith("the knight drew his sword"))

    def test_resume_on_a_finished_chapter_adds_one_more_section(self):
        llm = ChatFakeLlama(lambda p, i: " " + "more " * 2000)
        engine = LocalStoryEngine()
        engine._llm = llm
        existing = "done " * 300
        result = engine.generate_chapter(_chapter_project(target=200), 0, resume_from=existing)
        self.assertGreater(count_words(result), 300)
        self.assertEqual(len(llm.prompts), 1)

    def test_tail_fills_the_free_context_instead_of_a_fixed_400_words(self):
        llm = ChatFakeLlama(lambda p, i: " " + "more " * 50, specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        engine._n_ctx = 32768
        existing = "CHAPTER_OPENING " + "prose " * 3000 + "last line"
        engine.generate_chapter(_chapter_project(target=3100), 0, resume_from=existing)
        self.assertIn("CHAPTER_OPENING", llm.prompts[0])  # whole chapter so far fits

    def test_tail_shrinks_to_fit_a_small_context(self):
        llm = ChatFakeLlama(lambda p, i: " " + "more " * 50, specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        engine._n_ctx = 2500
        existing = "CHAPTER_OPENING " + "prose " * 3000 + "last line"
        engine.generate_chapter(_chapter_project(target=3100), 0, resume_from=existing)
        self.assertNotIn("CHAPTER_OPENING", llm.prompts[0])
        self.assertLessEqual(len(llm.prompts[0].split()) + llm.max_tokens[0], engine._n_ctx)

    def test_beat_hint_points_at_the_next_uncovered_beat(self):
        hint = build_beat_progress_hint("- Arrive\n- Fight\n- Escape\n- Rest", written_words=260, target_words=500)
        self.assertIn("beat 3 of 4", hint)
        self.assertIn("Escape", hint)
        self.assertEqual(build_beat_progress_hint("Just one beat.", 10, 100), "")

    def test_tail_preserving_format_keeps_paragraph_breaks(self):
        text = "Para one sentence.\n\nPara two first. Para two second.\n\nPara three."
        tail = tail_preserving_format(text, 7)
        self.assertIn("\n\n", tail)
        self.assertTrue(tail.endswith("Para three."))
        self.assertNotIn("[...]", tail)


if __name__ == "__main__":
    unittest.main()
