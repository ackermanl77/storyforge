"""Pasajes anteriores relevantes (B16): passages, BM25 / embeddings ranking and the prompt block."""

import unittest
from unittest import mock

from app import retrieval
from app.engine import CONTEXT_BUDGET_LEVELS
from app.project import Project
from app.prompts import build_chapter_continuation_chat, build_chapter_start_chat


def _novel():
    project = Project(plot="A keeper and a stranger.", characters="Mara; Tobias.", setting="Gull Point.")
    filler = " ".join(f"The sea rolled grey and the wind kept on{i}." for i in range(8))
    one = project.add_chapter("Arrival", target_words=1000)
    one.content = (f"{filler}\n\nTobias gave Mara a brass compass engraved with the name Halloran and made her promise "
                   f"to return it to his sister in Wexmouth if he died.\n\n{filler}")
    two = project.add_chapter("The Tunnels", target_words=1000)
    two.content = f"{filler}\n\nThey found fresh boot prints in the eastern tunnel, leading toward the chapel.\n\n{filler}"
    three = project.add_chapter("Wexmouth", target_words=1000, outline="Mara reaches Wexmouth to find Tobias's sister.")
    three.content = "Mara stepped off the ferry with the compass in her pocket."
    return project


class PassageTests(unittest.TestCase):
    def test_paragraphs_are_merged_and_split_and_only_earlier_chapters_count(self):
        project = _novel()
        passages = retrieval.split_passages(project, 2)
        self.assertEqual({p.chapter_index for p in passages}, {0, 1})
        self.assertTrue(all(retrieval.MIN_PASSAGE_WORDS <= len(p.text.split()) <= retrieval.MAX_PASSAGE_WORDS
                            for p in passages[:-1]))
        long = Project()
        long.add_chapter("A").content = " ".join(f"w{i}" for i in range(400))
        long.add_chapter("B")
        self.assertEqual([len(p.text.split()) for p in retrieval.split_passages(long, 1)], [160, 160, 80])

    def test_bm25_finds_the_passage_with_the_rare_names(self):
        project = _novel()
        chosen = retrieval.recall_passages(project, 2, project.chapters[2].content, max_words=110)
        self.assertEqual(len(chosen), 1)
        self.assertIn("Halloran", chosen[0].text)
        self.assertEqual(chosen[0].chapter_index, 0)
        self.assertEqual(retrieval.recall_passages(project, 0, "", 400), [])  # nothing earlier
        self.assertEqual(retrieval.recall_passages(project, 2, "", 0), [])  # no budget

    def test_embeddings_rank_when_a_model_is_set_and_bm25_is_the_fallback(self):
        project = _novel()

        def embed(texts):  # "meaning": does the text talk about tunnels or boots?
            return [[1.0 if ("tunnel" in t.lower() or "underground" in t.lower()) else 0.0, 0.1] for t in texts]

        project.chapters[2].outline = "Something moves underground."
        retrieval.set_embedder(embed)
        try:
            self.assertTrue(retrieval.embedder_active())
            chosen = retrieval.recall_passages(project, 2, "", max_words=100)
            self.assertIn("boot prints", chosen[0].text)  # found by meaning, not by shared words
        finally:
            retrieval.set_embedder(None)
        broken = mock.Mock(side_effect=RuntimeError("model gone"))
        retrieval.set_embedder(broken)
        try:
            project.chapters[2].outline = "Halloran compass"
            self.assertIn("Halloran", retrieval.recall_passages(project, 2, "", max_words=110)[0].text)
        finally:
            retrieval.set_embedder(None)


class PromptTests(unittest.TestCase):
    def test_the_block_is_added_only_when_enabled_and_shrinks_with_the_budget(self):
        project = _novel()
        budget = CONTEXT_BUDGET_LEVELS[0]
        off = build_chapter_continuation_chat(project, 2, budget, project.chapters[2].content, 500, 100)
        self.assertNotIn("RELEVANT EARLIER PASSAGES", off.user + off.system)
        project.recall_passages = True
        on = build_chapter_continuation_chat(project, 2, budget, project.chapters[2].content, 500, 100)
        self.assertIn("RELEVANT EARLIER PASSAGES", on.user)
        self.assertIn("[Chapter 1] Tobias gave Mara a brass compass", on.user)
        start = build_chapter_start_chat(project, 2, dict(budget, max_recall_words=0))
        self.assertNotIn("RELEVANT EARLIER PASSAGES", start.user)
        self.assertTrue(all("max_recall_words" in level for level in CONTEXT_BUDGET_LEVELS))

    def test_the_flag_is_saved_and_old_projects_load_without_it(self):
        project = _novel()
        project.recall_passages = True
        self.assertTrue(Project.from_dict(project.to_dict()).recall_passages)
        data = project.to_dict()
        del data["recall_passages"]
        self.assertFalse(Project.from_dict(data).recall_passages)


try:
    from tests.test_gui_p2 import GUI_AVAILABLE, _Base
except Exception:  # noqa: BLE001
    GUI_AVAILABLE, _Base = False, unittest.TestCase


@unittest.skipUnless(GUI_AVAILABLE, "no display / customtkinter")
class PlotTabTests(_Base):
    def test_the_checkbox_follows_the_project(self):
        self.assertFalse(self.app.recall_passages_var.get())
        self.app.recall_passages_check.select()
        self.app._on_recall_passages_changed()
        self.assertTrue(self.app.project.recall_passages)
        self.app.project.recall_passages = False
        self.app._load_story_settings_into_ui()
        self.assertFalse(self.app.recall_passages_var.get())


if __name__ == "__main__":
    unittest.main()
