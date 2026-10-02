import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lecture.pdf import PdfError, prepare_pages
from server.lecture_testing import make_pdf


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "sources" / "자료구조"
        self.folder.mkdir(parents=True)
        self.pdf = self.folder / "교안.pdf"
        self.pages = self.folder / "pages"

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self):
        return prepare_pages(self.root, "자료구조")

    def test_missing_pdf(self):
        self.assertEqual(self.prepare().status, "missing")
        self.assertFalse(self.pages.exists())

    def test_renders_images_and_extracts_text(self):
        self.pdf.write_bytes(make_pdf(["Hello one", "Second page"]))
        result = self.prepare()
        self.assertEqual((result.status, result.pages), ("prepared", 2))
        self.assertTrue((self.pages / "p001.png").stat().st_size > 0)
        self.assertTrue((self.pages / "p002.png").is_file())
        self.assertEqual((self.pages / "p001.txt").read_text(encoding="utf-8").strip(), "Hello one")
        self.assertEqual((self.pages / "p002.txt").read_text(encoding="utf-8").strip(), "Second page")

    def test_unchanged_pdf_is_not_rendered_again(self):
        self.pdf.write_bytes(make_pdf(["Hello one"]))
        self.prepare()
        before = (self.pages / "p001.png").stat().st_mtime_ns
        result = self.prepare()
        self.assertEqual((result.status, result.pages), ("unchanged", 1))
        self.assertEqual((self.pages / "p001.png").stat().st_mtime_ns, before)

    def test_changed_pdf_replaces_all_pages(self):
        self.pdf.write_bytes(make_pdf(["a", "b", "c"]))
        self.prepare()
        self.pdf.write_bytes(make_pdf(["a", "b"]))
        result = self.prepare()
        self.assertEqual((result.status, result.pages), ("prepared", 2))
        self.assertFalse((self.pages / "p003.png").exists())

    def test_corrupt_pdf_raises_and_leaves_nothing_behind(self):
        for content in (b"not a pdf", b""):
            self.pdf.write_bytes(content)
            with self.assertRaises(PdfError):
                self.prepare()
        self.assertFalse(self.pages.exists())
        self.assertEqual([p.name for p in self.folder.iterdir()], ["교안.pdf"])

    def test_damaged_page_tree_raises_pdf_error_and_leaves_nothing_behind(self):
        # Opens fine but the second page cannot be loaded (a realistic truncated-file pattern).
        self.pdf.write_bytes(make_pdf(["one"]).replace(b"/Count 1", b"/Count 2"))
        with self.assertRaises(PdfError):
            self.prepare()
        self.assertEqual([p.name for p in self.folder.iterdir()], ["교안.pdf"])

    def test_too_many_pages_is_refused_and_cleaned_up(self):
        self.pdf.write_bytes(make_pdf(["a", "b"]))
        with patch("server.lecture.pdf.MAX_PAGES", 1), self.assertRaises(PdfError):
            self.prepare()
        self.assertEqual([p.name for p in self.folder.iterdir()], ["교안.pdf"])

    def test_oversized_file_is_refused(self):
        self.pdf.write_bytes(make_pdf(["a"]))
        with patch("server.lecture.pdf.MAX_BYTES", 10), self.assertRaises(PdfError):
            self.prepare()
