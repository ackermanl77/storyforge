"""Lluvia de ideas y entrevistas (F14): the prompt, the engine turn and the window.

With daredevil-8b on the GPU (2026-10-18): "Give me five ideas for what Mara does next." gave five
story-specific numbered ideas (confront Tobias about the map, search her father's records, lock him
in...) in 3.5 s; as Mara, "¿qué le pasó a tu hermano?" was answered in Spanish, in the first person,
with the bible's facts (drowned when she was nineteen, she blames herself), and a follow-up used the
earlier answer."""

import unittest
from unittest import mock

from app.engine import LocalStoryEngine
from app.project import Project
from app.prompts import SIDE_CHAT_BRAINSTORM, SIDE_CHAT_CHARACTER, build_side_chat, looks_spanish
from tests.test_generation_quality import LLAMA3_SPECIALS, ChatFakeLlama


def _project():
    project = Project(plot="A keeper rescues a stranger.", characters="Mara: the keeper; her brother drowned.",
                      setting="Gull Point, a rocky island.")
    chapter = project.add_chapter("The Storm", target_words=1000)
    chapter.content = " ".join(f"w{i}" for i in range(900)) + " She found the map."
    return project


class PromptTests(unittest.TestCase):
    def test_the_bible_the_chapter_tail_and_the_history_are_in_the_prompt(self):
        history = [("user", "Who is Tobias?"), ("assistant", "A liar from the mainland.")]
        prompt = build_side_chat(_project(), 0, history, "Ten ideas for the next scene", SIDE_CHAT_BRAINSTORM)
        for part in ("A keeper rescues a stranger.", "Mara: the keeper", "Gull Point", "She found the map.",
                     "Writer: Who is Tobias?", "You: A liar from the mainland.", "Ten ideas for the next scene"):
            self.assertIn(part, prompt.user)
        self.assertIn("creative writing partner", prompt.system)
        self.assertNotIn("w100 ", prompt.user)  # only the chapter's last 600 words
        self.assertNotIn("Answer in Spanish", prompt.user)

    def test_a_character_answers_in_character_and_in_spanish_when_asked_in_spanish(self):
        prompt = build_side_chat(_project(), None, [("assistant", "Fue mi culpa.")], "¿Qué le pasó a tu hermano?",
                                 SIDE_CHAT_CHARACTER, "Mara")
        self.assertIn("You are Mara", prompt.system)
        self.assertIn("Mara: Fue mi culpa.", prompt.user)
        self.assertTrue(prompt.user.endswith("(Answer in Spanish.)"))
        self.assertNotIn("CURRENT CHAPTER", prompt.user)  # no chapter selected

    def test_spanish_detection(self):
        self.assertTrue(looks_spanish("¿Por qué?"))
        self.assertTrue(looks_spanish("dime que hay en el mapa de la isla"))
        self.assertFalse(looks_spanish("Give me ten ideas for the next scene"))
        self.assertFalse(looks_spanish("Mara"))


class EngineTests(unittest.TestCase):
    def test_a_turn_streams_and_old_turns_are_dropped_when_the_prompt_is_too_long(self):
        llm = ChatFakeLlama(lambda p, i: "Ask her about the lantern. [END] ignored", specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        engine._n_ctx = 1200
        history = []
        for i in range(30):
            history += [("user", f"question {i} " + "pad " * 30), ("assistant", f"answer {i} " + "pad " * 30)]
        pieces = []
        reply = engine.side_chat(_project(), 0, history, "And now?", on_token=pieces.append)
        self.assertEqual(reply, "Ask her about the lantern.")
        sent = llm.prompts[-1]
        self.assertIn("question 29", sent)
        self.assertNotIn("question 0 ", sent)  # the oldest exchanges were dropped to fit
        self.assertIn("Keep to the story's established facts", sent)

    def test_it_needs_a_model(self):
        from app.engine import ModelNotLoadedError

        with self.assertRaises(ModelNotLoadedError):
            LocalStoryEngine().side_chat(_project(), 0, [], "hi")


try:
    from tests.test_gui_p2 import GUI_AVAILABLE, _Base
except Exception:  # noqa: BLE001
    GUI_AVAILABLE, _Base = False, unittest.TestCase


@unittest.skipUnless(GUI_AVAILABLE, "no display / customtkinter")
class WindowTests(_Base):
    def test_ask_insert_and_start_over(self):
        calls = []

        def side_chat(project, chapter_index, history, message, mode, character, cancel_check=None, on_token=None):
            calls.append((chapter_index, list(history), message, mode, character))
            if on_token:
                on_token("She hides ")
            return " She hides the map in the lamp room. "

        self.engine.side_chat = side_chat
        panel = self._chapter("Mara waited.")
        window = self.app.open_side_chat()
        self.assertIs(self.app.open_side_chat(), window)  # one window, brought to the front
        with mock.patch("app.ui_side_chat.messagebox.showinfo") as info:
            self.assertFalse(window.send(""))
            info.assert_called_once()
            window.set_mode(SIDE_CHAT_CHARACTER)
            self.assertFalse(window.send("Hello?"))  # no character name yet
        window.set_mode(SIDE_CHAT_CHARACTER, "Mara")
        self.assertTrue(window.send("Where is the map?"))
        self.app.update()
        self.assertEqual(calls[-1], (0, [], "Where is the map?", SIDE_CHAT_CHARACTER, "Mara"))
        self.assertIn("Mara: She hides the map in the lamp room.", window.transcript_text())
        self.assertEqual(window.last_reply(), "She hides the map in the lamp room.")
        window.send("Why there?")
        self.app.update()
        self.assertEqual(calls[-1][1], [("user", "Where is the map?"), ("assistant", "She hides the map in the lamp room.")])
        panel.content_box.mark_set("insert", "end-1c")
        self.assertTrue(window.insert_last_reply())
        self.assertEqual(panel.chapter.content, "Mara waited. She hides the map in the lamp room.")
        self.assertEqual(panel.chapter.history_entries()[-1]["source"], "conversación")
        window.new_conversation()
        self.assertEqual((window.history, window.transcript_text()), ([], ""))
        window.destroy()


if __name__ == "__main__":
    unittest.main()
