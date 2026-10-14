import json
import tempfile
import unittest
from pathlib import Path

from server.lecture.exam import (exam_problems, exam_prompt, list_exams, note_concepts, parse_response,
                                 read_exam, recent_exams)

NOTE = ('# 강의 — 주제\n\n01주차 01번째 강의 · 교안 A p.1 · 전사 약 00:00:00–00:00:01\n\n'
        '## 핵심 암기사항\n\n요약\n\n## 1. 첫 개념\n\n설명\n\n## 2. 둘째 개념\n\n설명\n\n'
        '## 예상문제와 해설\n\n### 1. 질문\n\n**정답:** 답\n\n## 불확실한 내용\n\n없음\n')
# Counts differ from the UI defaults (25/15/0/0) so a test cannot pass by falling back to them.
SETTINGS = {"stems": ["week_01_01"], "counts": {"mcq": 2, "ox": 1, "short": 1, "essay": 1},
            "emphasis": True, "memo": ""}


def questions():
    source = {"stem": "week_01_01", "concept": 2}
    return [
        {"type": "mcq", "question": "Q1", "choices": ["가", "나", "다", "라"], "answer": 3, "explanation": "E1", "source": source},
        {"type": "mcq", "question": "Q2", "choices": ["a", "b", "c", "d"], "answer": 0, "explanation": "E2",
         "source": {"stem": "week_01_01", "concept": 1}},
        {"type": "ox", "question": "Q3", "answer": False, "explanation": "E3", "source": source},
        {"type": "short", "question": "Q4", "answer": "크레마", "explanation": "E4", "source": source},
        {"type": "essay", "question": "Q5", "answer": "모범답안", "keyPoints": ["포인트"], "explanation": "E5", "source": source},
    ]


def changed(index, **fields):
    """questions() with one question's fields replaced; a value of None deletes the field."""
    items = questions()
    for key, value in fields.items():
        if value is None:
            items[index].pop(key, None)
        else:
            items[index][key] = value
    return {"questions": items}


def saved_exam(items=None, **extra):
    return {"version": 1, "course": "강의", "createdAt": "2026-10-15T14:03:00", "agent": "claude",
            "settings": SETTINGS, "questions": questions() if items is None else items, **extra}


class ExamRoot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.notes = self.root / 'output' / '강의' / 'notes'
        self.notes.mkdir(parents=True)
        (self.notes / 'week_01_01.md').write_text(NOTE, encoding='utf-8')
        self.exams = self.root / 'output' / '강의' / 'exams'

    def tearDown(self):
        self.temp.cleanup()

    def write_exam(self, exam_id, content):
        self.exams.mkdir(parents=True, exist_ok=True)
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        (self.exams / f'{exam_id}.json').write_text(text, encoding='utf-8')


class ExamShapeTests(ExamRoot):
    def problems(self, data, settings=SETTINGS):
        return exam_problems(data, settings, self.root, '강의')

    def test_note_concepts_reads_numbered_headings_outside_code(self):
        text = NOTE.replace('설명\n\n## 2.', '```md\n## 9. 가짜\n```\n\n## 2.', 1)
        self.assertEqual(note_concepts(text), {1, 2})

    def test_parse_response_tolerates_fences_and_prose(self):
        body = json.dumps({"questions": questions()}, ensure_ascii=False)
        for text in (body, f'```json\n{body}\n```', f'다음은 시험지입니다.\n```json\n{body}\n```\n확인해 주세요.',
                     f'시험지입니다: {body} 끝.'):
            with self.subTest(text=text[:20]):
                data, problems = parse_response(text)
                self.assertEqual((problems, data['questions'][0]['question']), ([], 'Q1'))
        for text in ('', '작업을 완료했습니다.', '{"questions": [', '```json\n{oops}\n```'):
            with self.subTest(text=text):
                data, problems = parse_response(text)
                self.assertIsNone(data)
                self.assertTrue(problems)

    def test_valid_exam_passes(self):
        self.assertEqual(self.problems({"questions": questions()}), [])

    def test_shape_errors_are_reported(self):
        cases = {
            'not an object': [questions()],
            'no questions key': {"items": questions()},
            'unknown type': changed(0, type='multiple'),
            'empty question': changed(0, question='  '),
            'missing explanation': changed(3, explanation=None),
            'three choices': changed(0, choices=['가', '나', '다']),
            'duplicate choices': changed(0, choices=['가', '가 ', '다', '라']),
            'blank choice': changed(0, choices=['가', '', '다', '라']),
            'answer out of range': changed(0, answer=4),
            'answer is a bool': changed(1, answer=True),
            'answer as text': changed(0, answer='3'),
            'ox answer as text': changed(2, answer='X'),
            'blank short answer': changed(3, answer=' '),
            'essay without key points': changed(4, keyPoints=[]),
            'essay key points missing': changed(4, keyPoints=None),
            'source missing': changed(3, source=None),
            'concept as text': changed(3, source={"stem": "week_01_01", "concept": "2"}),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertNotEqual(self.problems(data), [])

    def test_counts_must_match_settings_exactly(self):
        data = {"questions": questions()[:-1]}
        problems = self.problems(data)
        self.assertTrue(any('서술형' in item and '1개' in item and '0개' in item for item in problems), problems)
        extra = {"questions": questions() + [questions()[2]]}
        self.assertTrue(any('OX' in item for item in self.problems(extra)))

    def test_source_must_point_to_a_selected_note_concept(self):
        (self.notes / 'week_01_02.md').write_text(NOTE, encoding='utf-8')
        cases = {
            'concept not in note': {"stem": "week_01_01", "concept": 3},
            'note outside the range': {"stem": "week_01_02", "concept": 1},
            'traversal stem': {"stem": "../week_01_01", "concept": 1},
        }
        for name, source in cases.items():
            with self.subTest(name):
                self.assertNotEqual(self.problems(changed(0, source=source)), [])
        missing = dict(SETTINGS, stems=['week_01_01', 'week_09_09'])
        self.assertNotEqual(self.problems(changed(0, source={"stem": "week_09_09", "concept": 1}), missing), [])


class ExamStoreTests(ExamRoot):
    def test_list_and_read_exams(self):
        self.write_exam('20261015-140300', saved_exam())
        self.write_exam('20261016-090000', saved_exam())
        self.write_exam('20261014-000000', '{broken')
        self.write_exam('20261013-000000', saved_exam(version=2))
        self.write_exam('20261012-000000', saved_exam(items=[{"type": "mcq", "question": "Q"}]))
        self.write_exam('not-an-id', saved_exam())
        items = list_exams(self.root, '강의')
        self.assertEqual([item['id'] for item in items],
                         ['20261016-090000', '20261015-140300', '20261014-000000', '20261013-000000', '20261012-000000'])
        self.assertEqual(items[0]['settings'], SETTINGS)
        self.assertNotIn('questions', items[0])
        self.assertTrue(all('error' in item for item in items[2:]))
        self.assertEqual(read_exam(self.root, '강의', '20261015-140300')['questions'], questions())
        with self.assertRaises(FileNotFoundError):
            read_exam(self.root, '강의', '20991231-000000')
        for broken in ('20261014-000000', '20261013-000000', '20261012-000000'):
            with self.subTest(broken), self.assertRaises(ValueError):
                read_exam(self.root, '강의', broken)
        self.assertEqual(list_exams(self.root, '없는 강의'), [])

    def test_recent_exams_are_the_latest_five(self):
        for day in range(1, 8):
            self.write_exam(f'2026100{day}-000000', saved_exam())
        self.assertEqual(recent_exams(self.root, '강의'),
                         [f'output/강의/exams/2026100{day}-000000.json' for day in (7, 6, 5, 4, 3)])

    def test_prompt_carries_paths_settings_and_quoted_memo(self):
        settings = dict(SETTINGS, stems=['week_01_01', 'week_02_01'], memo='수치 위주로 "꼭"', emphasis=False)
        prompt = exam_prompt('강의', settings, ['output/강의/exams/20261015-140300.json'])
        for expected in ('출제-지침.md', 'output/강의/notes/week_01_01.md', 'output/강의/notes/week_02_01.md',
                         'output/강의/exams/20261015-140300.json', '객관식 2', 'OX 1', '단답식 1', '서술형 1',
                         '교수님 강조 우선: 꺼짐', '"수치 위주로 \\"꼭\\""'):
            self.assertIn(expected, prompt)
        self.assertNotIn('셸 명령이 차단', prompt)
        self.assertIn('셸 명령이 차단', exam_prompt('강의', settings, agent='agy'))
        retry = exam_prompt('강의', settings, problems=['1번 문제 오류'])
        self.assertIn('거부', retry)
        self.assertIn('- 1번 문제 오류', retry)


if __name__ == '__main__':
    unittest.main()
