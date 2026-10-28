"""The 2026-10-21 rows: editor feedback (F21), character detection (F22), scenes and
text never sent to the model (F23), lore aliases/relations/mentions (F24), Visualize
through PixelFlow (F25) and a series lorebook (F26)."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from app import visualize
from app.engine import LocalStoryEngine
from app.export import build_markdown
from app.lore_tools import (
    detect_new_names,
    locate_quote,
    mention_counts,
    parse_feedback,
    parse_relations,
)
from app.project import LoreEntry, Project
from app.prompts import build_feedback_chat, build_lorebook_block, build_previous_context
from app.retrieval import split_passages
from app.scenes import ai_text, export_text, has_hidden, scene_header, split_scenes
from tests.test_generation_quality import LLAMA3_SPECIALS, ChatFakeLlama

CHAPTER = (
    "### La huida [POV: Ana]\n"
    "Ana corrió hacia el puerto. Allí la esperaba Tobías Merino con el mapa.\n"
    "[[privado]]Nota: revisar la fecha del naufragio.[[/privado]]\n"
    "### El sótano [archivada]\n"
    "Una escena descartada con el Capitán Rojas.\n"
    "### El faro\n"
    "Tobías Merino encendió la lámpara. El Capitán Rojas no llegó nunca, y Tobías Merino esperó."
)


class SceneTests(unittest.TestCase):
    def test_scenes_are_parsed_with_their_pov_and_archive_flag(self):
        scenes = split_scenes(CHAPTER)
        self.assertEqual([(s.label, s.pov, s.archived) for s in scenes],
                         [("La huida", "Ana", False), ("El sótano", "", True), ("El faro", "", False)])
        self.assertEqual(scene_header("El faro", "Mara", archived=True), "### El faro [POV: Mara] [archivada]")

    def test_the_model_never_sees_private_text_or_archived_scenes(self):
        visible = ai_text(CHAPTER)
        self.assertNotIn("revisar la fecha", visible)
        self.assertNotIn("escena descartada", visible)
        self.assertIn("### El faro", visible)
        self.assertTrue(has_hidden(CHAPTER))
        self.assertEqual(ai_text("Plain text.\n\n### A scene\nMore."), "Plain text.\n\n### A scene\nMore.")

    def test_exports_drop_archived_scenes_and_markers_but_keep_private_text(self):
        exported = export_text(CHAPTER)
        self.assertIn("Nota: revisar la fecha", exported)
        self.assertNotIn("[[privado]]", exported)
        self.assertNotIn("escena descartada", exported)
        self.assertIn("* * *", exported)
        self.assertFalse(exported.startswith("* * *"))
        project = Project(name="X")
        project.add_chapter("Uno").content = CHAPTER
        self.assertNotIn("descartada", build_markdown(project))

    def test_every_model_context_is_filtered(self):
        project = Project(name="X")
        project.add_chapter("Uno").content = CHAPTER
        project.add_chapter("Dos")
        self.assertNotIn("revisar la fecha", build_previous_context(project, 1))
        self.assertTrue(all("descartada" not in p.text for p in split_passages(project, 1)))

    def test_refining_a_chapter_with_hidden_text_is_refused(self):
        project = Project(name="X")
        project.add_chapter("Uno").content = CHAPTER
        engine = LocalStoryEngine()
        engine._llm = ChatFakeLlama(lambda p, i: "x", specials=LLAMA3_SPECIALS)
        with self.assertRaises(ValueError):
            engine._refine_chapter(project, 0, "tighten", None, None, None)


class LoreToolTests(unittest.TestCase):
    def test_new_recurring_names_are_found_and_known_ones_skipped(self):
        names = detect_new_names(CHAPTER, [LoreEntry(name="Ana")])
        self.assertEqual([c.name for c in names], ["Tobías Merino"])  # Rojas: once (the other is archived)
        self.assertEqual(names[0].count, 2)  # the sentence-initial one is not counted
        self.assertEqual(detect_new_names(CHAPTER, [LoreEntry(name="Tobías", aliases="el viejo")]), [])

    def test_relations_and_aliases(self):
        self.assertEqual(parse_relations("familia: Ana\nfacción -> Los Lobos\nRojas"),
                         [{"type": "familia", "target": "Ana"}, {"type": "facción", "target": "Los Lobos"},
                          {"type": "relacionado con", "target": "Rojas"}])
        entry = LoreEntry(name="Isabel", keywords="Isabel", aliases="la Reina, Su Majestad",
                          relations=[{"type": "madre de", "target": "Ana"}], text="Reina de Gull Point.")
        self.assertEqual(entry.keyword_list(), ["Isabel", "la Reina", "Su Majestad"])
        block = build_lorebook_block([entry], "Entonces llegó la Reina.")
        self.assertIn("Isabel: Reina de Gull Point. (Relations: madre de: Ana)", block)
        round_trip = LoreEntry.from_dict(entry.to_dict())
        self.assertEqual((round_trip.aliases, round_trip.relations), (entry.aliases, entry.relations))

    def test_mentions_per_chapter(self):
        project = Project(name="X")
        project.add_chapter("Uno").content = "Llegó la Reina. Isabel sonrió."
        project.add_chapter("Dos").content = "Nadie."
        project.add_chapter("Tres").content = "Su Majestad habló."
        entry = LoreEntry(name="Isabel", aliases="la Reina, Su Majestad")
        self.assertEqual(mention_counts(project.chapters, entry), [(1, 2), (3, 1)])

    def test_feedback_notes_are_parsed_and_their_quotes_located(self):
        reply = ("- [ritmo] «Ana corrió hacia el puerto» — demasiado abrupto, prepara la huida.\n"
                 "- [continuidad] «encendió la lámpara» — en el capítulo 1 el faro no tenía lámpara.\n"
                 "  Revisa la biblia.\n"
                 "- [voz] sin cita — la narración cambia de tono.")
        notes = parse_feedback(reply)
        self.assertEqual([n.area for n in notes], ["ritmo", "continuidad", "voz"])
        self.assertTrue(notes[1].note.endswith("Revisa la biblia."))
        self.assertEqual(notes[2].quote, "")
        start, end = locate_quote(CHAPTER, "ANA  corrió hacia el puerto")
        self.assertEqual(CHAPTER[start:end], "Ana corrió hacia el puerto")
        self.assertIsNone(locate_quote(CHAPTER, "nunca escrito"))


class FeedbackEngineTests(unittest.TestCase):
    def test_the_prompt_quotes_the_bible_and_the_engine_returns_notes(self):
        project = Project(name="X", characters="Ana: la farera.", setting="Gull Point.")
        project.lore_entries.append(LoreEntry(name="Tobías Merino", keywords="Tobías", text="Un contrabandista."))
        project.add_chapter("Uno").content = CHAPTER
        prompt = build_feedback_chat(project, 0, {})
        for part in ("Ana: la farera.", "Gull Point.", "Un contrabandista.", "[area] «"):
            self.assertIn(part, prompt.user)
        self.assertNotIn("revisar la fecha", prompt.user)
        llm = ChatFakeLlama(lambda p, i: "- [ritmo] «Ana corrió» — más tensión.\n[END]", specials=LLAMA3_SPECIALS)
        engine = LocalStoryEngine()
        engine._llm = llm
        engine._n_ctx = 4096
        notes = engine.feedback(project, 0)
        self.assertEqual([(n.area, n.quote) for n in notes], [("ritmo", "Ana corrió")])


class SeriesTests(unittest.TestCase):
    def test_a_series_lorebook_is_shared_between_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            series = Path(folder) / "saga.sflore"
            first = Project(name="Libro 1")
            first.link_series(series)
            entry = first.add_lore_entry(name="Mara", keywords="Mara", text="La farera.")
            first.set_entry_shared(entry, True)
            self.assertTrue(entry.shared and entry in first.series_entries and entry not in first.lore_entries)
            first.save(Path(folder) / "libro1.json")
            second = Project(name="Libro 2")
            second.link_series(series)
            self.assertEqual([e.name for e in second.all_lore_entries()], ["Mara"])
            second.series_entries[0].text = "La farera, ya mayor."
            second.save(Path(folder) / "libro2.json")
            reopened = Project.load(Path(folder) / "libro1.json")
            self.assertEqual(reopened.series_entries[0].text, "La farera, ya mayor.")
            self.assertEqual(reopened.lore_entries, [])
            own = reopened.add_lore_entry(name="Mara", text="Otra Mara")
            self.assertEqual(reopened.all_lore_entries(), [own])  # the project's own entry wins
            self.assertNotIn("series_entries", json.loads(reopened.to_json()))

    def test_a_loaded_project_cannot_write_its_untrusted_series_path(self):
        with tempfile.TemporaryDirectory() as folder:
            series = Path(folder) / "shared.sflore"
            original = json.dumps({
                "format": "storyforge_series_lore",
                "format_version": 1,
                "entries": [{"name": "Mara", "keywords": "Mara", "text": "Original."}],
            })
            series.write_text(original, encoding="utf-8")
            project_path = Path(folder) / "untrusted.json"
            project_path.write_text(json.dumps({"name": "Imported", "series_path": str(series)}), encoding="utf-8")

            project = Project.load(project_path)
            self.assertEqual(project.series_path, str(series))
            self.assertFalse(project._series_write_authorized)
            project.series_entries[0].text = "Changed by project data."
            project.save(project_path)

            self.assertEqual(series.read_text(encoding="utf-8"), original)
            project.authorize_series_writes()
            project.save(project_path)
            self.assertEqual(
                json.loads(series.read_text(encoding="utf-8"))["entries"][0]["text"],
                "Changed by project data.",
            )

    def test_project_and_series_save_roll_back_together_on_second_write_failure(self):
        from unittest import mock
        from app import project as project_module

        with tempfile.TemporaryDirectory() as folder:
            series = Path(folder) / "shared.sflore"
            project_path = Path(folder) / "book.json"
            project = Project(name="Original")
            project.link_series(series)
            entry = project.add_lore_entry(name="Mara", text="Original.")
            project.set_entry_shared(entry, True)
            project.save(project_path)
            original_project = project_path.read_bytes()
            original_series = series.read_bytes()
            project.name = "Changed"
            project.series_entries[0].text = "Changed."
            save_series = project_module.save_series_lore

            def fail_after_write(path, entries):
                save_series(path, entries)
                raise OSError("injected second-write failure")

            with mock.patch.object(project_module, "save_series_lore", side_effect=fail_after_write):
                with self.assertRaisesRegex(OSError, "injected second-write failure"):
                    project.save(project_path)

            self.assertEqual(project_path.read_bytes(), original_project)
            self.assertEqual(series.read_bytes(), original_series)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class VisualizeTests(unittest.TestCase):
    def test_the_positive_prompt_is_replaced_and_the_image_returned(self):
        saved = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
                 "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
                 "3": {"class_type": "KSampler", "inputs": {"positive": ["1", 0], "negative": ["2", 0]}},
                 "4": {"class_type": "SaveImage", "inputs": {"image": ["3", 0]}}}
        calls = []

        def opener(req, timeout=0):
            path = req.full_url.split("8288", 1)[1]
            body = json.loads(req.data) if req.data else None
            calls.append((req.get_method(), path, body))
            if path.startswith("/api/workflows/"):
                return _Response(json.dumps({"extra": {"pixelflow_prompt": saved}}).encode())
            if path == "/api/queue":
                return _Response(b'{"prompt_id": "p1"}')
            if path.startswith("/api/history/"):
                status = "running" if sum(1 for c in calls if c[1].startswith("/api/history")) < 2 else "completed"
                return _Response(json.dumps({"status": status, "outputs": {"4": {"images": ["a.png"], "type": "output"}}}).encode())
            if path == "/outputs/a.png":
                return _Response(b"PNGDATA")
            raise AssertionError(path)

        image = visualize.generate_image("portrait of Mara", "Retrato", opener=opener, sleep=lambda s: None)
        self.assertEqual(image, b"PNGDATA")
        queued = next(body for method, path, body in calls if path == "/api/queue")
        self.assertEqual(queued["prompt"]["1"]["inputs"]["text"], "portrait of Mara")
        self.assertEqual(queued["prompt"]["2"]["inputs"]["text"], "blurry")  # the negative is left alone
        self.assertEqual(visualize.positive_text_nodes(saved), ["1"])


if __name__ == "__main__":
    unittest.main()


try:
    from tests.test_gui_p2 import GUI_AVAILABLE, _Base
except Exception:  # noqa: BLE001
    GUI_AVAILABLE, _Base = False, unittest.TestCase


@unittest.skipUnless(GUI_AVAILABLE, "no display / customtkinter")
class WindowTests(_Base):
    def test_feedback_scenes_and_private_text_in_the_chapter_editor(self):
        from unittest import mock

        from app import ui_story_tools
        from app.lore_tools import FeedbackNote

        panel = self._chapter("Ana corrió hacia el puerto. Llegó tarde.")
        self.engine.feedback = lambda project, index, cancel_check=None: [
            FeedbackNote("ritmo", "corrió hacia el puerto", "más tensión")]
        with mock.patch.object(ui_story_tools, "FeedbackDialog") as dialog:
            panel._on_feedback()
            self.app.update()
        notes = dialog.call_args[0][1]
        self.assertEqual(notes[0].area, "ritmo")
        self.assertTrue(panel.select_quote(notes[0].quote))
        self.assertEqual(panel.content_box.get("sel.first", "sel.last"), "corrió hacia el puerto")
        # Mark the selection private, then add a scene at the start.
        panel._on_mark_private()
        panel.sync_to_model()
        self.assertIn("[[privado]]corrió hacia el puerto[[/privado]]", panel.chapter.content)
        panel.content_box.mark_set("insert", "1.0")
        with mock.patch.object(ui_story_tools.simpledialog, "askstring", side_effect=["El puerto", "Ana"]):
            panel._on_new_scene()
        panel.sync_to_model()
        self.assertTrue(panel.chapter.content.startswith("### El puerto [POV: Ana]\n"))
        self.assertNotIn("corrió hacia el puerto", ai_text(panel.chapter.content))

    def test_lore_aliases_relations_mentions_detection_and_series(self):
        from unittest import mock

        from app import ui_lorebook_tab

        self._chapter("Llegó la Reina con Tobías Merino. Luego habló Tobías Merino.")
        self.app.add_lore_entry()
        panel = self.app.lore_panels[0]
        panel.name_entry.insert(0, "Isabel")
        panel.aliases_entry.insert(0, "la Reina")
        panel.relations_box.insert("1.0", "madre de: Ana")
        self.app.show_lore_mentions(panel)
        self.assertIn("cap. 1 (1)", panel.mentions_label.cget("text"))
        self.assertEqual(panel.entry.relations, [{"type": "madre de", "target": "Ana"}])
        # Character detection proposes Tobías Merino and creates its entry.
        with mock.patch.object(ui_lorebook_tab, "CharacterDetectionDialog") as dialog:
            self.app.detect_characters()
        candidates = dialog.call_args[0][2]
        self.assertEqual([c.name for c in candidates], ["Tobías Merino"])
        self.app.create_lore_entries(candidates, draft_with_model=False)
        self.assertEqual([e.name for e in self.app.project.lore_entries], ["Isabel", "Tobías Merino"])
        # A series lorebook, and an entry moved into it.
        with tempfile.TemporaryDirectory() as folder:
            series = str(Path(folder) / "saga.sflore")
            with mock.patch.object(ui_lorebook_tab.filedialog, "asksaveasfilename", return_value=series):
                self.app.link_series()
            self.assertIn("saga.sflore", self.app.series_label.cget("text"))
            first = self.app.lore_panels[0]
            self.app.set_lore_entry_shared(first, True)
            self.assertEqual([e.name for e in self.app.project.series_entries], ["Isabel"])
            self.assertEqual(len(self.app.lore_panels), 2)  # still listed, below the project's own
