import unittest
import unicodedata

from server.lecture.citation_hints import transcript_quote_hints


TRANSCRIPT = """[00:07:31] 이탈리아의 밀라노 루이기 베째라.
[00:07:39] 루이지, 루이기.
[00:07:50] 그래서 배제라.
[00:09:12] 특허를 출원한 건 베체라.
[00:30:04] 데미타세
[00:30:04] 반이라는 뜻이에요
"""
TABLE = """| 본문 표기 | 전사 표현 | 근거 |
|---|---|---|
| 루이기 베제라 | 루이기 베째라, 루이지, 베체라, 배제라 | 전사 {citations} |
"""


class CitationHintTests(unittest.TestCase):
    def test_real_missing_variant_citation_is_found_without_gold_labels(self):
        note = TABLE.format(citations='[00:07:31], [00:07:39], [00:09:12]')
        hints = transcript_quote_hints(note, TRANSCRIPT)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]['transcript_expression'], '배제라')
        self.assertEqual(hints[0]['matching_timestamps'], ['00:07:50'])
        self.assertEqual(hints[0]['note_line'], 3)
        self.assertEqual(transcript_quote_hints(note.replace('[00:09:12]', '[00:09:12], [00:07:50]'), TRANSCRIPT), [])

    def test_ranges_normalization_and_duplicate_source_timestamps(self):
        note = TABLE.format(citations='약 [00:07:31]–[00:09:12]')
        self.assertEqual(transcript_quote_hints(unicodedata.normalize('NFD', note), TRANSCRIPT), [])
        note += '| 데미타세 | “데미타세”·반이라는 뜻 | 전사 [00:30:04] |\n'
        self.assertEqual(transcript_quote_hints(note, TRANSCRIPT), [])

    def test_only_correction_tables_and_literal_hints_not_semantic_grades(self):
        note = '```markdown\n' + TABLE.format(citations='[00:07:31]') + '```\n'
        note += '| 다른 표 | 전사 표현 | 근거 |\n| 표기 | 없는 말 | [00:07:31] |\n'
        self.assertEqual(transcript_quote_hints(note, TRANSCRIPT), [])
        note += TABLE.format(citations='[00:09:12]~[00:07:31]')
        hints = transcript_quote_hints(note, TRANSCRIPT)
        self.assertEqual(len(hints), 4)
        self.assertTrue(all(not hint['cited_timestamps'] for hint in hints))
        note = TABLE.format(citations='[00:07:31]–[00:09:12]').replace('배제라', '이름의 바꿔쓰기')
        self.assertEqual(transcript_quote_hints(note, TRANSCRIPT)[0]['matching_timestamps'], [])


if __name__ == '__main__':
    unittest.main()
