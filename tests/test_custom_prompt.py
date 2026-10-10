"""Per-chapter custom prompt (Chapter.custom_prompt): placeholders, the prompt
sent for the first and the following sections, saving, limits, chat templates
without a system turn, and the engine actually sending it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chat_format import AlpacaFormatter, ChatMLFormatter, Llama3Formatter, MistralFormatter
from app.engine import LocalStoryEngine
from app.project import MAX_CUSTOM_PROMPT_WORDS, Project
from app.prompts import (
    CUSTOM_PROMPT_TEMPLATE,
    ChatPrompt,
    build_chapter_continuation_chat,
    build_chapter_start_chat,
    render_custom_prompt,
)

BUDGET = {"tail_words": 300, "max_previous_words": 200}


def make_project():
    project = Project(name="T", plot="A lighthouse keeper finds a bottle.", characters="Mara, the keeper.",
                      setting="A rocky island.")
    project.add_chapter(title="The Bottle", target_words=400, outline="Mara finds the bottle.")
    project.add_chapter(title="The Storm", target_words=400, outline="The storm arrives.")
    project.chapters[0].content = "Mara climbed the stairs. " * 10
    return project


class RecordingLlama:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt, max_tokens=0, **kwargs):
        self.prompts.append(prompt)
        words = " ".join(f"w{len(self.prompts)}_{i}" for i in range(150))
        return {"choices": [{"text": words, "finish_reason": "length"}]}


class TestRendering(unittest.TestCase):
    def test_placeholders_are_filled_and_unknown_braces_are_kept(self):
        project = make_project()
        project.chapters[1].custom_prompt = (
            "Ch {capítulo} / {capitulo}: {título} / {titulo}. {palabras} words. {plot} | {personajes} | "
            "{setting} | {esquema} | {nota_autor} | {unknown} | {anterior}"
        )
        project.chapters[1].author_note = "Keep it tense."
        text = render_custom_prompt(project, 1)
        self.assertTrue(text.startswith("Ch 2 / 2: The Storm / The Storm. 400 words. A lighthouse keeper"))
        for part in ("Mara, the keeper.", "A rocky island.", "The storm arrives.", "Keep it tense.", "{unknown}",
                     "Mara climbed the stairs."):
            self.assertIn(part, text)

    def test_the_template_uses_only_known_placeholders(self):
        project = make_project()
        project.chapters[1].custom_prompt = CUSTOM_PROMPT_TEMPLATE
        self.assertNotIn("{", render_custom_prompt(project, 1))


class TestPrompts(unittest.TestCase):
    def test_first_section_is_exactly_the_users_prompt_without_a_system_turn(self):
        project = make_project()
        project.chapters[1].custom_prompt = "Write a storm scene about {personajes}"
        prompt = build_chapter_start_chat(project, 1, BUDGET, hints=["an automatic hint"])
        self.assertEqual(prompt.system, "")
        self.assertEqual(prompt.user, "Write a storm scene about Mara, the keeper.")
        self.assertEqual(prompt.prefill, "")
        self.assertNotIn("an automatic hint", prompt.user)

    def test_later_sections_continue_from_the_text_already_written(self):
        project = make_project()
        project.chapters[1].custom_prompt = "Write a storm scene."
        written = " ".join(f"word{i}" for i in range(200))
        prompt = build_chapter_continuation_chat(project, 1, BUDGET, written, 300, 150, hints=["hint"])
        self.assertEqual(prompt.system, "")
        self.assertTrue(prompt.user.startswith("Write a storm scene."))
        self.assertTrue(written.endswith(prompt.prefill.strip()))
        self.assertIn("word100", prompt.user)  # earlier text, before the prefilled last lines
        self.assertNotIn("hint", prompt.user)
        self.assertTrue(prompt.raw.endswith("word199"))

    def test_an_empty_custom_prompt_keeps_the_automatic_prompt(self):
        project = make_project()
        project.chapters[1].custom_prompt = "   "
        prompt = build_chapter_start_chat(project, 1, BUDGET)
        self.assertTrue(prompt.system)
        self.assertIn("The storm arrives.", prompt.system + prompt.user)


class TestProject(unittest.TestCase):
    def test_saved_with_the_project_only_when_set(self):
        project = make_project()
        self.assertNotIn("custom_prompt", project.to_dict()["chapters"][0])
        project.chapters[1].custom_prompt = "My prompt {plot}"
        loaded = Project.from_dict(project.to_dict())
        self.assertEqual(loaded.chapters[1].custom_prompt, "My prompt {plot}")
        self.assertEqual(loaded.chapters[0].custom_prompt, "")

    def test_a_too_long_custom_prompt_is_a_validation_error(self):
        project = make_project()
        project.chapters[1].custom_prompt = "word " * (MAX_CUSTOM_PROMPT_WORDS + 1)
        self.assertTrue(any("prompt propio" in error for error in project.validate_inputs()))


class TestTemplatesWithoutSystem(unittest.TestCase):
    def test_no_system_turn_is_rendered_when_the_system_text_is_empty(self):
        prompt = ChatPrompt(system="", user="Hello", prefill="Once")
        self.assertNotIn("system", Llama3Formatter().render(prompt))
        self.assertNotIn("system", ChatMLFormatter().render(prompt))
        self.assertEqual(MistralFormatter().render(prompt), "[INST] Hello [/INST]Once")
        self.assertEqual(AlpacaFormatter().render(prompt), "### Instruction:\nHello\n\n### Response:\nOnce")
        with_system = ChatPrompt(system="Rules", user="Hello")
        self.assertIn("system", ChatMLFormatter().render(with_system))
        self.assertEqual(MistralFormatter().render(with_system), "[INST] Rules\n\nHello [/INST]")


class TestEngine(unittest.TestCase):
    def test_generate_chapter_sends_the_custom_prompt(self):
        project = make_project()
        project.chapters[1].custom_prompt = "CUSTOM-START {título}"
        engine = LocalStoryEngine()
        engine._llm = RecordingLlama()
        engine.set_chat_format("chatml")
        text = engine.generate_chapter(project, 1)
        self.assertGreaterEqual(len(engine._llm.prompts), 2)  # 400 words in ~150-word sections
        first = engine._llm.prompts[0]
        self.assertIn("CUSTOM-START The Storm", first)
        self.assertNotIn("<|im_start|>system", first)
        self.assertNotIn("A lighthouse keeper", first)  # no plot unless {plot} is used
        self.assertIn("CUSTOM-START The Storm", engine._llm.prompts[1])
        self.assertIn("w1_149", engine._llm.prompts[1])  # continues from the text already written
        self.assertIn("w1_0", text)


if __name__ == "__main__":
    unittest.main()
