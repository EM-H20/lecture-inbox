import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lecture.pdf import delete_document, list_documents, prepare_pages
from server.lecture_testing import make_pdf


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.course = self.root / "sources" / "자료구조"
        self.docs = self.course / "교안"
        self.docs.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, name, content):
        (self.docs / f"{name}.pdf").write_bytes(content)

    def pages(self, name):
        return self.course / "pages" / name

    def prepare(self):
        return prepare_pages(self.root, "자료구조")

    def outcome(self, results, name):
        return next(result for result in results if result.document == name)

    def test_no_documents(self):
        self.assertEqual(self.prepare(), [])
        self.assertEqual(list_documents(self.root, "자료구조"), [])

    def test_lists_only_pdf_files_sorted(self):
        self.add("2주차", make_pdf(["b"]))
        self.add("1주차", make_pdf(["a"]))
        (self.docs / "memo.txt").write_text("x", encoding="utf-8")
        (self.docs / "folder.pdf").mkdir()
        self.assertEqual(list_documents(self.root, "자료구조"), ["1주차", "2주차"])

    def test_renders_images_and_text_per_document(self):
        self.add("1주차", make_pdf(["Hello one", "Second page"]))
        self.add("2주차 실습", make_pdf(["Third"]))
        results = self.prepare()
        self.assertEqual([(r.document, r.status, r.pages) for r in results],
                         [("1주차", "prepared", 2), ("2주차 실습", "prepared", 1)])
        self.assertTrue((self.pages("1주차") / "p001.png").stat().st_size > 0)
        self.assertEqual((self.pages("1주차") / "p002.txt").read_text(encoding="utf-8").strip(), "Second page")
        self.assertEqual((self.pages("2주차 실습") / "p001.txt").read_text(encoding="utf-8").strip(), "Third")

    def test_unchanged_document_is_not_rendered_again(self):
        self.add("1주차", make_pdf(["Hello one"]))
        self.prepare()
        before = (self.pages("1주차") / "p001.png").stat().st_mtime_ns
        result = self.prepare()[0]
        self.assertEqual((result.status, result.pages), ("unchanged", 1))
        self.assertEqual((self.pages("1주차") / "p001.png").stat().st_mtime_ns, before)

    def test_changed_document_replaces_all_of_its_pages(self):
        self.add("1주차", make_pdf(["a", "b", "c"]))
        self.prepare()
        self.add("1주차", make_pdf(["a", "b"]))
        result = self.prepare()[0]
        self.assertEqual((result.status, result.pages), ("prepared", 2))
        self.assertFalse((self.pages("1주차") / "p003.png").exists())

    def test_one_broken_document_does_not_block_the_others(self):
        self.add("좋음", make_pdf(["Hello"]))
        self.add("깨짐", b"not a pdf")
        self.add("빈 파일", b"")
        results = self.prepare()
        self.assertEqual(self.outcome(results, "좋음").status, "prepared")
        for name in ("깨짐", "빈 파일"):
            broken = self.outcome(results, name)
            self.assertEqual((broken.status, broken.pages), ("failed", 0))
            self.assertIn("PDF", broken.error)
            self.assertFalse(self.pages(name).exists())
        self.assertEqual(sorted(p.name for p in (self.course / "pages").iterdir()), ["좋음"])  # no staging leftovers

    def test_a_damaged_page_tree_fails_only_that_document(self):
        self.add("망가짐", make_pdf(["one"]).replace(b"/Count 1", b"/Count 2"))
        result = self.prepare()[0]
        self.assertEqual(result.status, "failed")
        self.assertEqual([p.name for p in (self.course / "pages").iterdir()], [])

    def test_too_many_pages_and_oversized_files_fail_without_leftovers(self):
        self.add("길다", make_pdf(["a", "b"]))
        with patch("server.lecture.pdf.MAX_PAGES", 1):
            self.assertEqual(self.prepare()[0].status, "failed")
        with patch("server.lecture.pdf.MAX_BYTES", 10):
            self.assertEqual(self.prepare()[0].status, "failed")
        pages_root = self.course / "pages"
        self.assertEqual([p.name for p in pages_root.iterdir()] if pages_root.exists() else [], [])

    def test_a_broken_replacement_does_not_leave_stale_pages_behind(self):
        self.add("1주차", make_pdf(["good"]))
        self.prepare()
        self.add("1주차", b"not a pdf")
        self.assertEqual(self.prepare()[0].status, "failed")
        self.assertFalse(self.pages("1주차").exists())

    def test_pages_of_a_removed_document_are_cleaned_up(self):
        self.add("1주차", make_pdf(["a"]))
        self.add("2주차", make_pdf(["b"]))
        self.prepare()
        (self.docs / "2주차.pdf").unlink()
        self.prepare()
        self.assertTrue(self.pages("1주차").is_dir())
        self.assertFalse(self.pages("2주차").exists())

    def test_delete_document_removes_the_pdf_and_its_pages(self):
        self.add("1주차", make_pdf(["a"]))
        self.prepare()
        self.assertTrue(delete_document(self.root, "자료구조", "1주차"))
        self.assertFalse((self.docs / "1주차.pdf").exists())
        self.assertFalse(self.pages("1주차").exists())
        self.assertFalse(delete_document(self.root, "자료구조", "1주차"))
