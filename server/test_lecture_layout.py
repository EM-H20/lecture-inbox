import tempfile
import unittest
from pathlib import Path

from server.lecture.layout import (
    LayoutError, TranscriptExists, documents_dir, lecture_stem, pages_dir, publish_transcript, safe_document,
)
from server.lecture.transcript import Segment, Transcript


def transcript(text="안녕하세요"):
    return Transcript("ggml-small", "ko", "a.mp4", 60.0, [Segment(0.0, 2.0, text)])


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, course="자료구조", week=1, session=2, text="안녕하세요", **kwargs):
        return publish_transcript(self.root, course, week, session, transcript(text), **kwargs)

    def test_stem_is_zero_padded_and_range_checked(self):
        self.assertEqual(lecture_stem(1, 2), "week_01_02")
        self.assertEqual(lecture_stem(12, 3), "week_12_03")
        for week, session in ((0, 1), (1, 100), (1, 0)):
            with self.assertRaises(LayoutError):
                lecture_stem(week, session)

    def test_publish_writes_markdown_and_plain_text(self):
        md, txt = self.publish()
        self.assertEqual(md, self.root / "sources" / "자료구조" / "전사" / "week_01_02.md")
        self.assertEqual(md.read_text(encoding="utf-8"), "[00:00:00] 안녕하세요\n")
        self.assertEqual(txt.read_text(encoding="utf-8"), "안녕하세요\n")

    def test_course_name_cannot_escape_the_sources_folder(self):
        for name in ("../../evil", "/etc/passwd", "..", "a/../../b"):
            for path in self.publish(course=name):
                self.assertEqual(path.parent.parent.parent, self.root / "sources", name)

    def test_blank_course_name_is_rejected(self):
        for name in ("", "   "):
            with self.assertRaises(LayoutError):
                self.publish(course=name)

    def test_existing_transcript_is_refused_and_left_untouched(self):
        md, _ = self.publish(text="원래 내용")
        with self.assertRaises(TranscriptExists):
            self.publish(text="새 내용")
        self.assertEqual(md.read_text(encoding="utf-8"), "[00:00:00] 원래 내용\n")

    def test_overwrite_replaces_both_files(self):
        self.publish(text="원래 내용")
        md, txt = self.publish(text="새 내용", overwrite=True)
        self.assertEqual(md.read_text(encoding="utf-8"), "[00:00:00] 새 내용\n")
        self.assertEqual(txt.read_text(encoding="utf-8"), "새 내용\n")

    def test_no_staging_folder_is_left_behind(self):
        md, _ = self.publish()
        self.assertEqual(sorted(p.name for p in md.parent.iterdir()), ["week_01_02.md", "week_01_02.txt"])


class DocumentNameTests(unittest.TestCase):
    def test_keeps_the_name_and_drops_the_pdf_extension(self):
        self.assertEqual(safe_document("1주차.pdf"), "1주차")
        self.assertEqual(safe_document("2주차 실습.PDF"), "2주차 실습")
        self.assertEqual(safe_document("no extension"), "no extension")

    def test_cannot_escape_its_folder(self):
        for name in ("../../x.pdf", "/etc/passwd", "..", "a/b.pdf"):
            self.assertNotIn("/", safe_document(name), name)

    def test_blank_names_are_rejected(self):
        for name in ("", "   ", ".pdf", " .PDF "):
            with self.assertRaises(LayoutError):
                safe_document(name)

    def test_documents_and_their_pages_live_under_the_course(self):
        root = Path("/project")
        self.assertEqual(documents_dir(root, "자료구조"), root / "sources" / "자료구조" / "교안")
        self.assertEqual(pages_dir(root, "자료구조", "1주차"), root / "sources" / "자료구조" / "pages" / "1주차")
