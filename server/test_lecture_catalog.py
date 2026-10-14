import tempfile
import unittest
from pathlib import Path

from server.lecture.catalog import list_courses, note_handouts


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
                {"stem": "week_01_01", "week": 1, "session": 1, "hasNote": True, "handouts": []},
                {"stem": "week_01_02", "week": 1, "session": 2, "hasNote": False, "handouts": []}]},
        ])

    def test_hidden_folders_files_and_unsafe_names_are_skipped(self):
        sources = self.root / "sources"
        (sources / ".hidden").mkdir(parents=True)
        (sources / "note.txt").write_text("x", encoding="utf-8")
        (sources / "a:b").mkdir()  # ':' would be rewritten by safe_name, so the API could never address it
        self.assertEqual(list_courses(self.root), [])

    def test_handouts_come_from_the_note_metadata_line(self):
        def note(meta):
            return f"# 강의 — 주제\n\n{meta}\n\n## 핵심 암기사항\n"
        cases = {
            "01주차 01번째 강의 · 교안 01_에스프레소 및 관리 p.3–10 · 전사 약 00:02:36–00:30:17": ["01_에스프레소 및 관리"],
            "03주차 01번째 강의 · 교안 A p.3–8, p.10 · 교안 B 2장 p.2 · 전사 약 00:01:00–00:02:00": ["A", "B 2장"],
            "03주차 01번째 강의 · 교안 A p.3 · 교안 A p.9 · 전사 약 00:01:00–00:02:00": ["A"],
            "01주차 01번째 강의 · 교안 연결 확인 필요 · 전사 약 00:00:00–00:00:01": [],
            "메타데이터가 아닌 문단": [],
        }
        for meta, expected in cases.items():
            with self.subTest(meta=meta):
                self.assertEqual(note_handouts(note(meta)), expected)

    def test_lecture_lists_handouts_of_its_note(self):
        course = self.root / "sources" / "바리스타"
        (course / "전사").mkdir(parents=True)
        (course / "전사" / "week_02_01.md").write_text("x", encoding="utf-8")
        notes = self.root / "output" / "바리스타" / "notes"
        notes.mkdir(parents=True)
        (notes / "week_02_01.md").write_text(
            "# 바리스타 — 추출\n\n02주차 01번째 강의 · 교안 2교시(26년) p.2–6 · 전사 약 00:00:01–00:10:00\n", encoding="utf-8")
        lecture = list_courses(self.root)[0]["lectures"][0]
        self.assertEqual(lecture["handouts"], ["2교시(26년)"])
