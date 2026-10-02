import unittest

from server.lecture.repetition import find_repetition_span
from server.lecture.transcript import Segment, Transcript, format_hms, to_markdown

LOOP = "같은 문장을 계속 반복합니다"


def segs(*texts):
    return [Segment(float(i), float(i + 1), text) for i, text in enumerate(texts)]


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.transcript = Transcript("ggml-small", "ko", "a.mp4", 4000.0, [
            Segment(0.0, 2.4, "안녕하세요"), Segment(3725.9, 3730.0, "두 번째")])

    def test_hms(self):
        self.assertEqual(format_hms(0), "00:00:00")
        self.assertEqual(format_hms(3725.9), "01:02:05")

    def test_markdown_has_one_timestamp_per_segment(self):
        self.assertEqual(to_markdown(self.transcript), "[00:00:00] 안녕하세요\n[01:02:05] 두 번째\n")

    def test_empty_transcript_is_empty_text(self):
        self.assertEqual(to_markdown(Transcript("m", "ko", "a.mp4", 1.0, [])), "")


class RepetitionTests(unittest.TestCase):
    def test_three_identical_long_segments_are_a_loop(self):
        self.assertEqual(find_repetition_span(segs(LOOP, LOOP, LOOP)), (0, 2))

    def test_loop_in_the_middle(self):
        texts = ["첫번째 이야기입니다", "전혀 다른 내용이에요", LOOP, LOOP, LOOP, LOOP, "마무리 하겠습니다"]
        self.assertEqual(find_repetition_span(segs(*texts)), (2, 5))

    def test_loop_at_the_end(self):
        self.assertEqual(find_repetition_span(segs("첫번째 이야기입니다", LOOP, LOOP, LOOP)), (1, 3))

    def test_two_repeats_are_not_a_loop(self):
        self.assertIsNone(find_repetition_span(segs(LOOP, LOOP)))

    def test_short_acknowledgements_are_not_a_loop(self):
        self.assertIsNone(find_repetition_span(segs("네", "네", "네", "네", "네")))

    def test_empty_list(self):
        self.assertIsNone(find_repetition_span([]))
