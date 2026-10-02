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

    def pages(self, *texts):
        folder = self.src / "pages"
        folder.mkdir(parents=True)
        for i, text in enumerate(texts, 1):
            (folder / f"p{i:03d}.png").write_bytes(b"x")
            (folder / f"p{i:03d}.txt").write_text(text, encoding="utf-8")

    def lecture(self, stem, note=False):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f"{stem}.md").write_text("[00:00:01] x\n", encoding="utf-8")
        if note:
            (self.out / "notes").mkdir(exist_ok=True)
            (self.out / "notes" / f"{stem}.md").write_text("n", encoding="utf-8")

    def text(self):
        return write_work_order(self.root, "자료구조").read_text(encoding="utf-8")

    def row(self, text, stem):
        return next(line for line in text.splitlines() if line.startswith(f"| {stem} "))

    def test_without_pdf_or_lectures(self):
        text = self.text()
        self.assertIn("정리-지침.md", text)
        self.assertIn("교안 없음", text)
        self.assertIn("아직 전사체가 없습니다", text)

    def test_pdf_without_pages_says_to_prepare(self):
        self.src.mkdir(parents=True)
        (self.src / "교안.pdf").write_bytes(b"%PDF")
        text = self.text()
        self.assertIn("페이지가 아직 준비되지 않았습니다", text)
        self.assertIn('npm run lecture -- prepare --course "자료구조"', text)

    def test_lists_lectures_in_order_with_status(self):
        self.pages("슬라이드 하나", "슬라이드 둘")
        self.lecture("week_01_02")
        self.lecture("week_01_01", note=True)
        text = self.text()
        self.assertIn("페이지 2장", text)
        self.assertIn("sources/자료구조/pages/pNNN.png", text)
        self.assertLess(text.index("| week_01_01 "), text.index("| week_01_02 "))
        self.assertEqual(self.row(text, "week_01_01"),
                         "| week_01_01 | `output/자료구조/week_01_01.md` | `output/자료구조/notes/week_01_01.md` | 정리 완료 |")
        self.assertTrue(self.row(text, "week_01_02").endswith("| 정리 대기 |"))
        self.assertIn("정리 대기: 1개", text)

    def test_blank_page_text_is_flagged(self):
        self.pages("", "  ")
        self.assertIn("추출 텍스트가 비어 있습니다", self.text())

    def test_ignores_staging_and_misnamed_files(self):
        self.lecture("week_01_01")
        (self.out / ".staging-x").mkdir()
        (self.out / ".staging-x" / "week_09_09.md").write_text("x", encoding="utf-8")
        (self.out / "week_1_1.md").write_text("x", encoding="utf-8")
        text = self.text()
        self.assertNotIn("week_09_09", text)
        self.assertNotIn("week_1_1", text)
