import tempfile
import unittest
from pathlib import Path

from server.lecture.catalog import list_courses


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_sources_folder_is_an_empty_list(self):
        self.assertEqual(list_courses(self.root), [])

    def test_lists_documents_pages_lectures_and_notes(self):
        course = self.root / "sources" / "자료구조"
        (course / "pages" / "1주차").mkdir(parents=True)
        (course / "전사").mkdir()
        (course / "교안").mkdir()
        (course / "교안" / "1주차.pdf").write_bytes(b"%PDF")
        (course / "교안" / "2주차.pdf").write_bytes(b"%PDF")  # not prepared yet: 0 pages
        for name in ("p001.png", "p002.png"):
            (course / "pages" / "1주차" / name).write_bytes(b"x")
        (course / "전사" / "week_01_02.md").write_text("x", encoding="utf-8")
        (course / "전사" / "week_01_01.md").write_text("x", encoding="utf-8")
        (course / "전사" / "week_1_1.md").write_text("x", encoding="utf-8")  # misnamed: ignored
        notes = self.root / "output" / "자료구조" / "notes"
        notes.mkdir(parents=True)
        (notes / "week_01_01.md").write_text("n", encoding="utf-8")
        (self.root / "sources" / "빈 강의").mkdir()
        self.assertEqual(list_courses(self.root), [
            {"name": "빈 강의", "documents": [], "lectures": []},
            {"name": "자료구조", "documents": [{"name": "1주차", "pages": 2}, {"name": "2주차", "pages": 0}], "lectures": [
                {"stem": "week_01_01", "week": 1, "session": 1, "hasNote": True},
                {"stem": "week_01_02", "week": 1, "session": 2, "hasNote": False}]},
        ])

    def test_hidden_folders_files_and_unsafe_names_are_skipped(self):
        sources = self.root / "sources"
        (sources / ".hidden").mkdir(parents=True)
        (sources / "note.txt").write_text("x", encoding="utf-8")
        (sources / "a:b").mkdir()  # ':' would be rewritten by safe_name, so the API could never address it
        self.assertEqual(list_courses(self.root), [])
