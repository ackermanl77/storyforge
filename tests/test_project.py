import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.project import (
    MAX_CHAPTERS,
    MAX_OUTLINE_WORDS_PER_CHAPTER,
    MAX_WORDS_PER_CHAPTER,
    Chapter,
    Project,
    count_words,
)


class TestCountWords(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(count_words("hello world"), 2)

    def test_empty(self):
        self.assertEqual(count_words(""), 0)
        self.assertEqual(count_words(None), 0)

    def test_punctuation_and_contractions(self):
        self.assertEqual(count_words("Don't stop, it's fine."), 4)

    def test_newlines(self):
        self.assertEqual(count_words("one\ntwo\n\nthree"), 3)


class TestProjectValidation(unittest.TestCase):
    def test_valid_project_has_no_errors(self):
        p = Project(plot="a story " * 10, characters="a hero", setting="a castle")
        p.add_chapter("Intro", 500)
        self.assertEqual(p.validate_inputs(), [])

    def test_plot_over_limit(self):
        p = Project(plot="word " * 50_001)
        errors = p.validate_inputs()
        self.assertTrue(any("plot" in e.lower() for e in errors))

    def test_characters_over_limit(self):
        p = Project(characters="word " * 10_001)
        errors = p.validate_inputs()
        self.assertTrue(any("personajes" in e.lower() for e in errors))

    def test_setting_over_limit(self):
        p = Project(setting="word " * 10_001)
        errors = p.validate_inputs()
        self.assertTrue(any("setting" in e.lower() for e in errors))

    def test_cannot_add_more_than_max_chapters(self):
        p = Project()
        for _ in range(MAX_CHAPTERS):
            p.add_chapter()
        self.assertFalse(p.can_add_chapter())
        with self.assertRaises(ValueError):
            p.add_chapter()

    def test_chapter_target_words_clamped_to_max(self):
        p = Project()
        chapter = p.add_chapter("Cap", target_words=999_999)
        self.assertEqual(chapter.target_words, MAX_WORDS_PER_CHAPTER)

    def test_chapter_content_over_limit_flagged(self):
        p = Project()
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.content = "word " * (MAX_WORDS_PER_CHAPTER + 1)
        errors = p.validate_inputs()
        self.assertTrue(any("Capitulo 1" in e and "excede" in e for e in errors))

    def test_chapter_outline_over_limit_flagged(self):
        p = Project()
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.outline = "word " * (MAX_OUTLINE_WORDS_PER_CHAPTER + 1)
        errors = p.validate_inputs()
        self.assertTrue(any("Capitulo 1" in e and "esquema" in e for e in errors))

    def test_chapter_outline_within_limit_not_flagged(self):
        p = Project(plot="a story " * 10, characters="a hero", setting="a castle")
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.outline = "word " * MAX_OUTLINE_WORDS_PER_CHAPTER
        self.assertEqual(p.validate_inputs(), [])


class TestPersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        p = Project(name="Mi historia", plot="Once upon a time", characters="Ana", setting="A forest")
        p.add_chapter("Chapter One", 1500)
        p.chapters[0].content = "It was a dark night."

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            p.save(path)
            loaded = Project.load(path)

        self.assertEqual(loaded.name, "Mi historia")
        self.assertEqual(loaded.plot, "Once upon a time")
        self.assertEqual(len(loaded.chapters), 1)
        self.assertEqual(loaded.chapters[0].title, "Chapter One")
        self.assertEqual(loaded.chapters[0].content, "It was a dark night.")
        self.assertEqual(loaded.chapters[0].word_count(), 5)

    def test_writing_style_round_trips(self):
        p = Project(writing_style="Descriptiva")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            p.save(path)
            loaded = Project.load(path)
        self.assertEqual(loaded.writing_style, "Descriptiva")

    def test_loading_a_project_saved_without_writing_style_defaults_to_empty(self):
        # Proyectos guardados antes de que existiera este campo no tienen la
        # clave "writing_style" en su JSON -- debe cargar como "" (sin
        # enfasis de estilo) en vez de fallar.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old_project.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"name": "Vieja", "plot": "x", "characters": "", "setting": "", "chapters": []}')
            loaded = Project.load(path)
        self.assertEqual(loaded.writing_style, "")


if __name__ == "__main__":
    unittest.main()
