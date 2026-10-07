import os
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.project import (
    MAX_CHAPTER_HISTORY,
    MAX_CHAPTERS,
    MAX_LORE_ENTRIES,
    MAX_LORE_ENTRY_WORDS,
    MAX_OUTLINE_WORDS_PER_CHAPTER,
    MAX_WORDS_PER_CHAPTER,
    Chapter,
    LoreEntry,
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

    def test_chapter_content_over_limit_is_a_warning_not_an_error(self):
        # Antes era un error de validate_inputs(), que bloqueaba generar
        # CUALQUIER capitulo (o el esquema) mientras un capitulo tuviera
        # apenas mas de 10,000 palabras.
        p = Project()
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.content = "word " * (MAX_WORDS_PER_CHAPTER + 1)
        self.assertEqual(p.validate_inputs(), [])
        warnings = p.validate_warnings()
        self.assertTrue(any("Capítulo 1" in w and "10,000" in w for w in warnings))

    def test_chapter_content_within_limit_has_no_warning(self):
        p = Project()
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.content = "word " * MAX_WORDS_PER_CHAPTER
        self.assertEqual(p.validate_warnings(), [])

    def test_chapter_outline_over_limit_flagged(self):
        p = Project()
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.outline = "word " * (MAX_OUTLINE_WORDS_PER_CHAPTER + 1)
        errors = p.validate_inputs()
        self.assertTrue(any("Capítulo 1" in e and "esquema" in e for e in errors))

    def test_chapter_outline_within_limit_not_flagged(self):
        p = Project(plot="a story " * 10, characters="a hero", setting="a castle")
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.outline = "word " * MAX_OUTLINE_WORDS_PER_CHAPTER
        self.assertEqual(p.validate_inputs(), [])


class TestChapterHistory(unittest.TestCase):
    def test_push_history_does_nothing_for_empty_content(self):
        ch = Chapter()
        ch.push_history()
        self.assertEqual(ch.history, [])

    def test_push_history_records_current_content(self):
        ch = Chapter(content="first draft")
        ch.push_history()
        self.assertEqual(ch.history, ["first draft"])
        # push_history no vacia el content actual, solo lo copia a history --
        # quien llama es responsable de sobrescribir content por separado.
        self.assertEqual(ch.content, "first draft")

    def test_push_history_caps_at_max_chapter_history(self):
        ch = Chapter()
        for i in range(MAX_CHAPTER_HISTORY + 3):
            ch.content = f"draft {i}"
            ch.push_history()
        self.assertEqual(len(ch.history), MAX_CHAPTER_HISTORY)
        # se conservan las mas recientes, se descartan las mas viejas
        self.assertEqual(ch.history[-1], f"draft {MAX_CHAPTER_HISTORY + 2}")
        self.assertEqual(ch.history[0], f"draft {3}")


class TestLoreEntry(unittest.TestCase):
    def test_keyword_list_splits_and_strips_commas(self):
        entry = LoreEntry(keywords=" Elena ,  the queen ,, Her Majesty")
        self.assertEqual(entry.keyword_list(), ["Elena", "the queen", "Her Majesty"])

    def test_keyword_list_empty_for_blank_keywords(self):
        entry = LoreEntry(keywords="   ")
        self.assertEqual(entry.keyword_list(), [])

    def test_word_count_counts_the_body_text(self):
        entry = LoreEntry(text="a short body of text")
        self.assertEqual(entry.word_count(), 5)


class TestProjectLorebook(unittest.TestCase):
    def test_new_project_has_no_lore_entries(self):
        p = Project()
        self.assertEqual(p.lore_entries, [])

    def test_add_lore_entry_appends_and_returns_it(self):
        p = Project()
        entry = p.add_lore_entry(name="Elena", keywords="Elena, the queen", text="Ruler of the realm.")
        self.assertEqual(len(p.lore_entries), 1)
        self.assertIs(p.lore_entries[0], entry)
        self.assertEqual(entry.name, "Elena")

    def test_cannot_add_more_than_max_lore_entries(self):
        p = Project()
        for _ in range(MAX_LORE_ENTRIES):
            p.add_lore_entry()
        self.assertFalse(p.can_add_lore_entry())
        with self.assertRaises(ValueError):
            p.add_lore_entry()

    def test_validate_inputs_flags_too_many_lore_entries(self):
        p = Project()
        p.lore_entries = [LoreEntry() for _ in range(MAX_LORE_ENTRIES + 1)]
        errors = p.validate_inputs()
        self.assertTrue(any("lorebook" in e.lower() for e in errors))

    def test_validate_inputs_flags_lore_entry_over_word_limit(self):
        p = Project()
        p.add_lore_entry(name="Elena", text="word " * (MAX_LORE_ENTRY_WORDS + 1))
        errors = p.validate_inputs()
        self.assertTrue(any("Elena" in e for e in errors))

    def test_validate_inputs_passes_for_lore_entry_within_limit(self):
        p = Project(plot="a story " * 10, characters="a hero", setting="a castle")
        p.add_lore_entry(name="Elena", text="word " * MAX_LORE_ENTRY_WORDS)
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

    def test_save_keeps_previous_version_as_bak(self):
        p = Project(plot="first version")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            p.save(path)
            p.plot = "second version"
            p.save(path)
            self.assertEqual(Project.load(path).plot, "second version")
            self.assertEqual(Project.load(path + ".bak").plot, "first version")
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_failed_save_leaves_existing_file_intact(self):
        p = Project(plot="good version")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            p.save(path)
            p.plot = "never written"
            with unittest.mock.patch("app.fileutil.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    p.save(path)
            self.assertEqual(Project.load(path).plot, "good version")
            self.assertFalse(os.path.exists(path + ".tmp"))

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

    def test_chapter_purpose_and_history_round_trip(self):
        p = Project()
        chapter = p.add_chapter("Cap", target_words=100)
        chapter.content = "final version"
        chapter.purpose = "Escena climatica"
        chapter.push_history()  # guarda "final version" antes de este cambio de ejemplo
        chapter.content = "final version"

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            p.save(path)
            loaded = Project.load(path)

        self.assertEqual(loaded.chapters[0].purpose, "Escena climatica")
        self.assertEqual(loaded.chapters[0].history, ["final version"])

    def test_loading_a_project_saved_without_purpose_or_history_defaults_to_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old_project.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    '{"name": "Vieja", "plot": "", "characters": "", "setting": "", '
                    '"chapters": [{"title": "Cap 1", "target_words": 100, "content": "x"}]}'
                )
            loaded = Project.load(path)
        self.assertEqual(loaded.chapters[0].purpose, "")
        self.assertEqual(loaded.chapters[0].history, [])

    def test_lore_entries_round_trip(self):
        p = Project()
        p.add_lore_entry(name="Elena", keywords="Elena, the queen", text="Ruler of the realm.")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            p.save(path)
            loaded = Project.load(path)

        self.assertEqual(len(loaded.lore_entries), 1)
        self.assertEqual(loaded.lore_entries[0].name, "Elena")
        self.assertEqual(loaded.lore_entries[0].keywords, "Elena, the queen")
        self.assertEqual(loaded.lore_entries[0].text, "Ruler of the realm.")

    def test_loading_a_project_saved_without_lore_entries_defaults_to_empty(self):
        # Proyectos guardados antes de que existiera el lorebook no tienen la
        # clave "lore_entries" en su JSON -- debe cargar como [] en vez de fallar.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old_project.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"name": "Vieja", "plot": "x", "characters": "", "setting": "", "chapters": []}')
            loaded = Project.load(path)
        self.assertEqual(loaded.lore_entries, [])


if __name__ == "__main__":
    unittest.main()
