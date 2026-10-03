import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lecture.layout import LayoutError
from server.lecture.study import ACTIVE, StudyRunner
from server.lecture_testing import wait_for
from server.test_lecture_web import WebTestCase, H

NOTE = '# 시험 대비\n## 핵심 암기사항\n근거\n## 예상문제와 해설\n연습문제\n## 불확실한 내용\n없음\n'


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runner = StudyRunner(self.root)
        self.source = self.root / 'sources' / '강의' / '전사'
        self.source.mkdir(parents=True)
        (self.source / 'week_01_01.md').write_text('[00:00:00] 내용', encoding='utf-8')
        self.notes = self.root / 'output' / '강의' / 'notes'
        self.binary = self.root / 'agent'
        self.fake()
        self.which = patch('server.lecture.study.shutil.which', return_value=str(self.binary))
        self.which.start()

    def tearDown(self):
        self.runner.close()
        self.which.stop()
        self.temp.cleanup()

    def fake(self, before='', note=NOTE):
        self.binary.write_text(f'''#!{sys.executable}
import json, sys, time, subprocess
from pathlib import Path
args = sys.argv[1:]
prompt = sys.stdin.read()
Path('invocation.json').write_text(json.dumps(dict(args=args, prompt=prompt)))
{before}
note = {note!r}
if '-o' in args:
    Path(args[args.index('-o') + 1]).write_text(note)
elif '--print' in args:
    print(json.dumps(dict(result=note, is_error=False)))
else:
    print(json.dumps(dict(response=note)))
''')
        self.binary.chmod(0o700)

    def finish(self):
        self.assertTrue(wait_for(lambda: self.runner.status()['job']['status'] not in ACTIVE))
        return self.runner.status()['job']

    def test_each_agent_output_and_command(self):
        for agent in ('claude', 'gemini', 'codex'):
            with self.subTest(agent=agent):
                self.runner.submit('강의', agent, ['week_01_01'])
                job = self.finish()
                self.assertEqual((job['status'], job['completed'], job['agent']), ('done', 1, agent))
                note = self.notes / 'week_01_01.md'
                self.assertEqual(note.read_text(), NOTE)
                invocation = json.loads((self.root / 'invocation.json').read_text())
                args = invocation['args']
                self.assertIn('sources/강의/전사/week_01_01.md', invocation['prompt'])
                self.assertNotIn('--dangerously-skip-permissions', args)
                if agent == 'claude':
                    self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
                elif agent == 'gemini':
                    self.assertEqual(args[args.index('--approval-mode') + 1], 'plan')
                else:
                    self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
                note.unlink()

    def test_duplicate_cancel_and_retry(self):
        self.fake("time.sleep(30)")
        job = self.runner.submit('강의', 'codex', ['week_01_01'])
        self.assertTrue(wait_for(lambda: (self.root / 'invocation.json').exists()))
        with self.assertRaises(LayoutError):
            self.runner.submit('강의', 'claude', ['week_01_01'])
        self.runner.cancel(job['id'])
        self.assertEqual(self.finish()['status'], 'cancelled')
        self.assertFalse((self.notes / 'week_01_01.md').exists())
        self.assertEqual(list(self.notes.glob('.study-*')), [])
        self.fake()
        self.runner.submit('강의', 'codex', ['week_01_01'])
        self.assertEqual(self.finish()['status'], 'done')

    def test_failed_or_incomplete_response_is_not_published(self):
        for before, note in [('sys.exit(1)', NOTE), ('', ''), ('', '작업을 완료했습니다.')]:
            self.fake(before, note)
            self.runner.submit('강의', 'gemini', ['week_01_01'])
            self.assertEqual(self.finish()['status'], 'failed')
            self.assertFalse((self.notes / 'week_01_01.md').exists())

    def test_existing_and_concurrently_created_notes_are_preserved(self):
        self.notes.mkdir(parents=True)
        note = self.notes / 'week_01_01.md'
        note.write_text('기존 노트')
        with self.assertRaises(LayoutError):
            self.runner.submit('강의', 'codex', ['week_01_01'])
        self.assertEqual(note.read_text(), '기존 노트')
        note.unlink()
        self.fake("Path('output/강의/notes/week_01_01.md').write_text('동시 작성')")
        self.runner.submit('강의', 'codex', ['week_01_01'])
        self.assertEqual(self.finish()['status'], 'failed')
        self.assertEqual(note.read_text(), '동시 작성')

    def test_close_kills_process_group_and_preserves_source(self):
        self.fake("child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\nPath('child.pid').write_text(str(child.pid))\ntime.sleep(30)")
        self.runner.submit('강의', 'claude', ['week_01_01'])
        self.assertTrue(wait_for(lambda: (self.root / 'child.pid').exists()))
        pid = int((self.root / 'child.pid').read_text())
        self.runner.close()
        self.assertEqual(self.finish()['status'], 'cancelled')
        def exited():
            try:
                os.kill(pid, 0)
                return False
            except ProcessLookupError:
                return True
        self.assertTrue(wait_for(exited))
        self.assertEqual((self.source / 'week_01_01.md').read_text(), '[00:00:00] 내용')

    def test_missing_agent_and_timeout(self):
        with patch('server.lecture.study.shutil.which', return_value=None):
            with self.assertRaises(LayoutError):
                self.runner.submit('강의', 'codex', ['week_01_01'])
            self.assertTrue(all(not a['available'] for a in self.runner.status()['agents']))
        self.fake('time.sleep(30)')
        with patch('server.lecture.study.TIMEOUT', 0.01):
            self.runner.submit('강의', 'codex', ['week_01_01'])
            self.assertEqual(self.finish()['status'], 'failed')
        self.assertFalse((self.notes / 'week_01_01.md').exists())

    def test_partial_completion_retries_only_remaining_lectures(self):
        (self.source / 'week_01_02.md').write_text('[00:01:00] 다음 내용')
        self.fake("if 'week_01_02.md' in prompt: sys.exit(1)")
        self.runner.submit('강의', 'codex', ['week_01_01', 'week_01_02'])
        job = self.finish()
        self.assertEqual((job['status'], job['completed'], job['total']), ('failed', 1, 2))
        first = self.notes / 'week_01_01.md'
        timestamp = first.stat().st_mtime_ns
        self.fake()
        self.runner.submit('강의', 'claude', ['week_01_02'])
        job = self.finish()
        self.assertEqual((job['status'], job['completed'], job['total']), ('done', 1, 1))
        self.assertEqual(first.stat().st_mtime_ns, timestamp)

    def test_only_selected_lecture_is_processed_and_duplicates_are_deduplicated(self):
        (self.source / 'week_01_02.md').write_text('[00:01:00] 다른 회차')
        self.runner.submit('강의', 'codex', ['week_01_02', 'week_01_02'])
        job = self.finish()
        self.assertEqual((job['total'], job['stems']), (1, ['week_01_02']))
        self.assertFalse((self.notes / 'week_01_01.md').exists())
        self.assertEqual((self.notes / 'week_01_02.md').read_text(), NOTE)

    def test_invalid_selection_never_falls_back_to_all(self):
        for stems in ([], ['week_99_99'], ['../week_01_01'], ['week_01_01', 'week_99_99']):
            with self.subTest(stems=stems), self.assertRaises(LayoutError):
                self.runner.submit('강의', 'codex', stems)
        self.assertIsNone(self.runner.status()['job'])
        self.assertFalse(self.notes.exists())


class StudyApiTests(WebTestCase):
    def test_guards_validation_and_note_reads(self):
        self.make_course()
        path = '/api/local/courses/강의/study'
        self.assertEqual(self.client.post(path, json={'agent': 'codex'}).status_code, 403)
        self.assertEqual(self.client.post(path, headers=H, json={'agent': 'arbitrary-command', 'stems': ['week_01_01']}).status_code, 422)
        self.assertEqual(self.client.get('/api/local/study', headers={'Host': 'evil.test'}).status_code, 403)
        notes = self.root / 'output' / '강의' / 'notes'
        notes.mkdir(parents=True)
        (notes / 'week_01_01.md').write_text(NOTE)
        response = self.client.get('/api/local/courses/강의/notes/week_01_01')
        self.assertEqual(response.json()['text'], NOTE)
        self.assertEqual(self.client.get('/api/local/courses/강의/notes/week_01_02').status_code, 404)
        self.assertEqual(self.client.get('/api/local/courses/강의/notes/not-a-stem').status_code, 422)
        with patch.object(self.client.app.state.study, 'submit', return_value={'status': 'waiting'}) as submit:
            self.assertEqual(self.client.post(path, headers=H, json={'agent': 'claude', 'stems': ['week_01_01']}).status_code, 202)
            submit.assert_called_once_with('강의', 'claude', ['week_01_01'])

    def test_selection_is_required_and_validated(self):
        self.make_course()
        path = '/api/local/courses/강의/study'
        for payload in ({'agent': 'codex'}, {'agent': 'codex', 'stems': []},
                        {'agent': 'codex', 'stems': ['../../secret']},
                        {'agent': 'codex', 'stems': 'week_01_01'}):
            self.assertEqual(self.client.post(path, headers=H, json=payload).status_code, 422)
        self.assertTrue(self.client.get('/api/local/study').json()['selectionSupported'])

    def test_selected_api_request_publishes_only_that_course_lecture(self):
        source = self.make_course() / '전사'
        source.mkdir()
        for stem in ('week_01_01', 'week_02_01'):
            (source / f'{stem}.md').write_text('[00:00:00] 전사')
        runner = self.client.app.state.study
        with patch('server.lecture.study.shutil.which', return_value=sys.executable), patch.object(
                runner, '_generate', side_effect=lambda binary, agent, prompt, result: result.write_text(NOTE)):
            response = self.client.post('/api/local/courses/강의/study', headers=H,
                                        json={'agent': 'claude', 'stems': ['week_02_01']})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()['stems'], ['week_02_01'])
            self.assertTrue(wait_for(lambda: runner.status()['job']['status'] == 'done'))
        courses = self.client.get('/api/local/courses').json()['courses']
        self.assertEqual([item['hasNote'] for item in courses[0]['lectures']], [False, True])


if __name__ == '__main__':
    unittest.main()
