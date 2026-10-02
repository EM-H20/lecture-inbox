import tempfile
import unittest
from pathlib import Path

from server.lecture.work_order import write_work_order


class WorkOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / "output" / "자료구조"
        self.src = self.root / "sources" / "자료구조"

    def tearDown(self):
        self.temp.cleanup()

    def doc(self, name, *page_texts, prepared=True):
        (self.src / "교안").mkdir(parents=True, exist_ok=True)
        (self.src / "교안" / f"{name}.pdf").write_bytes(b"%PDF")
        if prepared:
            folder = self.src / "pages" / name
            folder.mkdir(parents=True)
            for i, text in enumerate(page_texts, 1):
                (folder / f"p{i:03d}.png").write_bytes(b"x")
                (folder / f"p{i:03d}.txt").write_text(text, encoding="utf-8")

    def lecture(self, stem, note=False):
        (self.src / "전사").mkdir(parents=True, exist_ok=True)
        (self.src / "전사" / f"{stem}.md").write_text("[00:00:01] x\n", encoding="utf-8")
        if note:
            (self.out / "notes").mkdir(parents=True, exist_ok=True)
            (self.out / "notes" / f"{stem}.md").write_text("n", encoding="utf-8")

    def text(self):
        return write_work_order(self.root, "자료구조").read_text(encoding="utf-8")

    def row(self, text, stem):
        return next(line for line in text.splitlines() if line.startswith(f"| {stem} "))

    def test_without_documents_or_lectures(self):
        text = self.text()
        self.assertIn("정리-지침.md", text)
        self.assertIn("교안 없음", text)
        self.assertIn("sources/자료구조/교안/", text)
        self.assertIn("아직 전사체가 없습니다", text)

    def test_a_document_without_pages_says_to_prepare(self):
        self.doc("1주차", prepared=False)
        text = self.text()
        self.assertIn("`1주차` — 페이지가 아직 준비되지 않았습니다", text)
        self.assertIn('npm run lecture -- prepare --course "자료구조"', text)

    def test_lists_every_document_and_the_lectures_in_order_with_status(self):
        self.doc("1주차", "슬라이드 하나", "슬라이드 둘")
        self.doc("2주차 실습", "셋")
        self.lecture("week_01_02")
        self.lecture("week_01_01", note=True)
        text = self.text()
        self.assertIn("교안 2개", text)
        self.assertIn("쪽 이미지를 직접 열어 확인", text)  # the images carry the content; the text is only a hint
        self.assertIn("텍스트는 찾기 위한 참고용", text)
        self.assertIn("`1주차` — 2쪽 · 이미지 `sources/자료구조/pages/1주차/pNNN.png`, 텍스트 `sources/자료구조/pages/1주차/pNNN.txt`", text)
        self.assertIn("`2주차 실습` — 1쪽", text)
        self.assertLess(text.index("| week_01_01 "), text.index("| week_01_02 "))
        self.assertEqual(self.row(text, "week_01_01"),
                         "| week_01_01 | `sources/자료구조/전사/week_01_01.md` | `output/자료구조/notes/week_01_01.md` | 정리 완료 |")
        self.assertTrue(self.row(text, "week_01_02").endswith("| 정리 대기 |"))
        self.assertIn("정리 대기: 1개", text)

    def test_blank_page_text_is_flagged_for_that_document(self):
        self.doc("스캔본", "", "  ")
        self.doc("정상", "내용")
        text = self.text()
        self.assertIn("`스캔본`의 모든 페이지 추출 텍스트가 비어 있습니다", text)
        self.assertNotIn("`정상`의 모든 페이지", text)

    def test_ignores_staging_and_misnamed_files(self):
        self.lecture("week_01_01")
        (self.src / "전사" / ".staging-x").mkdir()
        (self.src / "전사" / ".staging-x" / "week_09_09.md").write_text("x", encoding="utf-8")
        (self.src / "전사" / "week_1_1.md").write_text("x", encoding="utf-8")
        text = self.text()
        self.assertNotIn("week_09_09", text)
        self.assertNotIn("week_1_1", text)
