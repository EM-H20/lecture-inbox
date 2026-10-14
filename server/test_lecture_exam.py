import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lecture.exam import (exam_problems, exam_prompt, list_exams, note_concepts, parse_response,
                                 read_exam, recent_exams)
from server.lecture.layout import LayoutError
from server.lecture.study import ACTIVE, StudyRunner
from server.lecture_testing import wait_for
from server.test_lecture_web import WebTestCase, H

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


class ExamRunnerTests(ExamRoot):
    def setUp(self):
        super().setUp()
        self.runner = StudyRunner(self.root)
        self.binary = self.root / 'agent'
        self.fake()
        self.which = patch('server.lecture.study.shutil.which', return_value=str(self.binary))
        self.which.start()

    def tearDown(self):
        self.runner.close()
        self.which.stop()
        super().tearDown()

    def fake(self, before='', response=None, after=''):
        response = json.dumps({'questions': questions()}, ensure_ascii=False) if response is None else response
        self.binary.write_text(f'''#!{sys.executable}
import json, sys, time
from pathlib import Path
args = sys.argv[1:]
prompt = args[args.index('--print') + 1] if '--mode' in args else sys.stdin.read()
Path('invocation.json').write_text(json.dumps(dict(args=args, prompt=prompt)))
{before}
response = {response!r}
{after}
if '-o' in args:
    Path(args[args.index('-o') + 1]).write_text(response)
elif '--mode' in args:
    print(json.dumps(dict(status='SUCCESS', response=response)))
else:
    print(json.dumps(dict(result=response, is_error=False)))
''')
        self.binary.chmod(0o700)

    def submit(self, agent='claude', **changes):
        args = dict(stems=['week_01_01'], counts=dict(SETTINGS['counts']), emphasis=True, memo='')
        args.update(changes)
        return self.runner.submit_exam('강의', agent, **args)

    def finish(self):
        self.assertTrue(wait_for(lambda: self.runner.status()['job']['status'] not in ACTIVE))
        return self.runner.status()['job']

    def saved(self):
        return sorted(self.exams.glob('*.json')) if self.exams.is_dir() else []

    def test_each_agent_generates_and_publishes_an_exam(self):
        for agent in ('claude', 'agy', 'codex'):
            with self.subTest(agent=agent):
                job = self.submit(agent)
                self.assertEqual((job['kind'], job['total']), ('exam', 1))
                job = self.finish()
                self.assertEqual((job['status'], job['completed'], job['error']), ('done', 1, ''))
                path = self.exams / f"{job['examId']}.json"
                exam = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual((exam['version'], exam['course'], exam['agent']), (1, '강의', agent))
                self.assertEqual(exam['settings'], SETTINGS)
                self.assertEqual(exam['questions'], questions())
                prompt = json.loads((self.root / 'invocation.json').read_text())['prompt']
                self.assertIn('output/강의/notes/week_01_01.md', prompt)
                self.assertIn('출제-지침.md', prompt)
                path.unlink()

    def test_bad_response_is_retried_with_reasons_then_rejected(self):
        short = json.dumps({'questions': questions()[:-1]}, ensure_ascii=False)
        self.fake(after=f"response = response if '거부' in prompt else {short!r}")
        self.submit()
        self.assertEqual(self.finish()['status'], 'done')
        self.assertEqual(len(self.saved()), 1)
        self.fake(response=short)
        self.submit()
        job = self.finish()
        self.assertEqual(job['status'], 'failed')
        self.assertIn('서술형 문제 수', job['error'])
        self.assertEqual(len(self.saved()), 1)
        self.assertEqual(list(self.exams.glob('.exam-*')), [])

    def test_exam_and_note_jobs_never_run_together_and_cancel_cleans_up(self):
        (self.root / 'sources' / '강의' / '전사').mkdir(parents=True)
        (self.root / 'sources' / '강의' / '전사' / 'week_01_01.md').write_text('[00:00:00] 내용')
        self.fake('time.sleep(30)')
        job = self.submit()
        self.assertTrue(wait_for(lambda: (self.root / 'invocation.json').exists()))
        with self.assertRaises(LayoutError):
            self.runner.submit('강의', 'claude', ['week_01_01'], replace=True)
        with self.assertRaises(LayoutError):
            self.submit()
        self.runner.cancel(job['id'])
        job = self.finish()
        self.assertEqual((job['status'], job['error']), ('cancelled', '시험지 생성을 취소했습니다.'))
        self.assertEqual(self.saved(), [])
        self.assertEqual(list(self.exams.glob('.exam-*')), [])

    def test_note_jobs_report_kind_note(self):
        (self.root / 'sources' / '강의' / '전사').mkdir(parents=True)
        (self.root / 'sources' / '강의' / '전사' / 'week_01_02.md').write_text('[00:00:00] 내용')
        self.fake('sys.exit(1)')
        self.assertEqual(self.runner.submit('강의', 'codex', ['week_01_02'])['kind'], 'note')
        self.finish()

    def test_invalid_settings_are_rejected_before_any_job(self):
        counts = SETTINGS['counts']
        cases = {
            'no stems': dict(stems=[]),
            'stem without note': dict(stems=['week_01_02']),
            'traversal stem': dict(stems=['../notes/week_01_01']),
            'over per-type limit': dict(counts=dict(counts, mcq=51)),
            'negative': dict(counts=dict(counts, ox=-1)),
            'zero total': dict(counts=dict(mcq=0, ox=0, short=0, essay=0)),
            'over total': dict(counts=dict(mcq=50, ox=11, short=0, essay=0)),
            'missing type': dict(counts=dict(mcq=1, ox=1, short=1)),
            'bool count': dict(counts=dict(counts, mcq=True)),
            'long memo': dict(memo='가' * 201),
        }
        for name, changes in cases.items():
            with self.subTest(name), self.assertRaises(LayoutError):
                self.submit(**changes)
        self.assertIsNone(self.runner.status()['job'])
        with self.assertRaises(LayoutError):
            self.runner.submit_exam('강의', 'unknown', ['week_01_01'], dict(counts))

    def test_previous_exams_are_offered_to_avoid_repeats(self):
        for day in range(1, 7):
            self.write_exam(f'2026100{day}-000000', saved_exam())
        self.submit()
        self.assertEqual(self.finish()['status'], 'done')
        prompt = json.loads((self.root / 'invocation.json').read_text())['prompt']
        self.assertIn('output/강의/exams/20261006-000000.json', prompt)
        self.assertIn('output/강의/exams/20261002-000000.json', prompt)
        self.assertNotIn('output/강의/exams/20261001-000000.json', prompt)

    def test_same_second_ids_never_overwrite(self):
        self.exams.mkdir(parents=True)
        existing = self.exams / '20261015-140300.json'
        existing.write_text('기존')
        final = self.root / 'final.json'
        final.write_text('새 시험지')
        ids = iter(['20261015-140300', '20261015-140301'])
        with patch('server.lecture.study.time.strftime', side_effect=lambda fmt: next(ids)), \
                patch('server.lecture.study.time.sleep'):
            self.assertEqual(StudyRunner._publish(final, self.exams), '20261015-140301')
        self.assertEqual(existing.read_text(), '기존')
        with patch('server.lecture.study.time.strftime', return_value='20261015-140300'), \
                patch('server.lecture.study.time.sleep'), self.assertRaises(RuntimeError):
            StudyRunner._publish(final, self.exams)
        self.assertEqual(existing.read_text(), '기존')


class ExamApiTests(WebTestCase):
    BODY = {'agent': 'claude', 'stems': ['week_01_01'], 'counts': {'mcq': 2, 'ox': 1, 'short': 1, 'essay': 1},
            'emphasis': False, 'memo': '메모'}

    def test_create_validates_and_delegates(self):
        self.make_course()
        path = '/api/local/courses/강의/exams'
        self.assertEqual(self.client.post(path, json=self.BODY).status_code, 403)
        for name, change in {
            'unknown agent': {'agent': 'sh'},
            'no stems': {'stems': []},
            'bad stem': {'stems': ['../x']},
            'over per-type': {'counts': {'mcq': 51, 'ox': 0, 'short': 0, 'essay': 0}},
            'missing type': {'counts': {'mcq': 1, 'ox': 0, 'short': 0}},
            'long memo': {'memo': '가' * 201},
        }.items():
            with self.subTest(name):
                self.assertEqual(self.client.post(path, headers=H, json={**self.BODY, **change}).status_code, 422)
        runner = self.client.app.state.study
        with patch.object(runner, 'submit_exam', return_value={'status': 'waiting', 'kind': 'exam'}) as submit:
            self.assertEqual(self.client.post(path, headers=H, json=self.BODY).status_code, 202)
            submit.assert_called_once_with('강의', 'claude', ['week_01_01'],
                                           {'mcq': 2, 'ox': 1, 'short': 1, 'essay': 1}, False, '메모')
        with patch.object(runner, 'submit_exam', side_effect=LayoutError('이미 진행 중')):
            response = self.client.post(path, headers=H, json=self.BODY)
            self.assertEqual((response.status_code, response.json()['detail']), (409, '이미 진행 중'))
        self.assertEqual(self.client.post('/api/local/courses/없는 강의/exams', headers=H, json=self.BODY).status_code, 404)

    def test_list_and_read_exams(self):
        self.make_course()
        exams = self.root / 'output' / '강의' / 'exams'
        exams.mkdir(parents=True)
        (exams / '20261015-140300.json').write_text(json.dumps(saved_exam(), ensure_ascii=False), encoding='utf-8')
        (exams / '20261016-090000.json').write_text('{broken', encoding='utf-8')
        listed = self.client.get('/api/local/courses/강의/exams').json()['exams']
        self.assertEqual([item['id'] for item in listed], ['20261016-090000', '20261015-140300'])
        self.assertIn('error', listed[0])
        exam = self.client.get('/api/local/courses/강의/exams/20261015-140300')
        self.assertEqual((exam.status_code, exam.json()['id'], exam.json()['questions']), (200, '20261015-140300', questions()))
        self.assertEqual(self.client.get('/api/local/courses/강의/exams/20261016-090000').status_code, 422)
        self.assertEqual(self.client.get('/api/local/courses/강의/exams/20991231-000000').status_code, 404)
        self.assertEqual(self.client.get('/api/local/courses/강의/exams/not-an-id').status_code, 422)
        self.assertEqual(self.client.get('/api/local/courses/강의/exams', headers={'Host': 'evil.test'}).status_code, 403)
        self.assertEqual(self.client.get('/api/local/courses/없는 강의/exams').status_code, 404)


if __name__ == '__main__':
    unittest.main()
