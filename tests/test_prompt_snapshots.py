"""
T3: golden-file snapshots of the prompts built from a fixed sample project,
in raw form and rendered through the Llama 3 / ChatML templates. A prompt
change makes these fail with a readable diff; if the change is intended,
regenerate with:

    set STORYFORGE_UPDATE_SNAPSHOTS=1 && python -m pytest -q tests/test_prompt_snapshots.py
"""
import difflib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chat_format import ChatMLFormatter, Llama3Formatter  # noqa: E402
from app.project import LoreEntry, Project  # noqa: E402
from app.prompts import (  # noqa: E402
    build_chapter_continuation_chat,
    build_chapter_start_chat,
    build_expand_field_chat,
    build_outline_chat,
    build_refine_chapter_chat,
    build_rewrite_span_chat,
    build_summary_chat,
)

SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
UPDATE = os.environ.get("STORYFORGE_UPDATE_SNAPSHOTS") == "1"
BUDGET = dict(max_plot_words=1200, max_characters_words=600, max_setting_words=600,
              max_previous_words=500, max_outline_words=400, tail_words=400, max_lore_words=200)


def _project():
    p = Project(name="Snapshot", plot="A cartographer maps a city that rearranges itself every night.",
                characters="Ines, a stubborn cartographer. Tomas, her rival.", setting="Velmora, a port city.",
                writing_style="Descriptiva", author_note="Keep the tone wry.")
    one = p.add_chapter("The Moving Street", 1200, outline="- Ines notices a street moved.\n- She meets Tomas.")
    one.content = "Ines unrolled the map. The street was gone.\n\nShe swore quietly."
    one.set_summary("Ines finds that a street has moved and meets her rival Tomas.")
    two = p.add_chapter("Night Survey", 1500, outline="Ines and Tomas survey the city at night.")
    two.purpose = "Escena climatica"
    two.author_note = "Tomas hides a lantern."
    p.lore_entries.append(LoreEntry(name="Velmora Bell", keywords="bell, Tomas", text="A bell that rings at each shift."))
    return p


def _prompts():
    p = _project()
    return {
        "outline": build_outline_chat(p, 3, max_plot_words=1200, max_characters_words=600, max_setting_words=600),
        "chapter_start": build_chapter_start_chat(p, 1, BUDGET),
        "chapter_continue": build_chapter_continuation_chat(p, 1, BUDGET, "The bell rang twice. Tomas", 900, 400,
                                                            hints=["PROGRESS: example hint."]),
        "summary": build_summary_chat(p.chapters[0].content, 150),
        "expand": build_expand_field_chat("plot", p.plot, 400),
        "refine": build_refine_chapter_chat(p, 0, "make it darker"),
        "rewrite_span": build_rewrite_span_chat(p, 0, "Ines unrolled the map.", "The street was gone.",
                                                "She swore quietly.", "describe"),
    }


class TestPromptSnapshots(unittest.TestCase):
    def _check(self, name, text):
        path = os.path.join(SNAP_DIR, f"{name}.txt")
        if UPDATE or not os.path.isfile(path):
            os.makedirs(SNAP_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            if not UPDATE:
                self.fail(f"snapshot {name} did not exist; it was created -- review and rerun")
            return
        with open(path, encoding="utf-8") as f:
            expected = f.read()
        if expected != text:
            diff = "".join(difflib.unified_diff(expected.splitlines(True), text.splitlines(True),
                                                f"{name} (snapshot)", f"{name} (now)"))
            self.fail(f"prompt changed:\n{diff}")

    def test_snapshots(self):
        renderers = {"raw": lambda c: c.raw, "llama3": Llama3Formatter().render, "chatml": ChatMLFormatter().render}
        for name, chat in _prompts().items():
            for fmt, render in renderers.items():
                with self.subTest(prompt=name, format=fmt):
                    self._check(f"{name}.{fmt}", render(chat))


if __name__ == "__main__":
    unittest.main()
