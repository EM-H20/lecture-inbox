import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from server.lecture.layout import LayoutError
from server.lecture.study import ACTIVE, StudyRunner, note_problems
from server.lecture_testing import wait_for
from server.test_lecture_web import WebTestCase, H

NOTE = ('# 강의 — 주제\n\n01주차 01번째 강의 · 교안 연결 확인 필요 · 전사 약 00:00:00–00:00:00\n\n'
        '## 핵심 암기사항\n\n근거\n\n## 1. 개념\n\n설명\n\n## 예상문제와 해설\n\n연습문제\n\n'
        '### 1. 질문\n\n**정답:** 답\n\n## 불확실한 내용\n\n확인된 불확실 사항 없음\n')


class NoteShapeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        pages = self.root / 'sources' / '강의' / 'pages' / '1주차 교안'
        pages.mkdir(parents=True)
        (pages / 'p003.png').write_bytes(b'png')

    def tearDown(self):
        self.temp.cleanup()

    def problems(self, text):
        return note_problems(text, '강의', self.root)

    def test_valid_note_and_existing_page_image_pass(self):
        image = '\n![표](<../../../sources/강의/pages/1주차 교안/p003.png>)\n'
        self.assertEqual(self.problems(NOTE.replace('설명\n', '설명\n' + image)), [])

    def test_shape_drift_between_agents_is_rejected(self):
        cases = {
            'summary last': NOTE.replace('## 핵심 암기사항\n\n근거\n\n', '') + '## 핵심 암기사항\n\n근거\n',
            'generic title': NOTE.replace('# 강의 — 주제', '# 강의 — 시험 대비\n# 회차'),
            'no metadata line': NOTE.replace('01주차 01번째 강의 · 교안 연결 확인 필요 · 전사 약 00:00:00–00:00:00\n\n', ''),
            'unnumbered concept': NOTE.replace('## 1. 개념', '## 개념'),
            'no concept': NOTE.replace('## 1. 개념\n\n설명\n\n', ''),
            'inline answer': NOTE.replace('### 1. 질문\n\n**정답:**', '### 1. 질문\n질문 본문\n**정답:**'),
            'no question': NOTE.replace('### 1. 질문\n\n**정답:** 답\n\n', ''),
            'fenced document': '```markdown\n' + NOTE + '```\n',
            'missing image': NOTE.replace('설명', '![x](<../../../sources/강의/pages/1주차 교안/p999.png>)'),
            'outside image': NOTE.replace('설명', '![x](../../../sources/다른강의/pages/a/p001.png)'),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertNotEqual(self.problems(text), [])

    def test_headings_inside_code_blocks_are_ignored(self):
        self.assertEqual(self.problems(NOTE.replace('설명', '```md\n## 핵심 암기사항\n```')), [])


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

    def fake(self, before='', note=NOTE, after=''):
        self.binary.write_text(f'''#!{sys.executable}
import json, sys, time, subprocess
from pathlib import Path
args = sys.argv[1:]
# Antigravity takes the prompt as the --print argument; the others read stdin.
prompt = args[args.index('--print') + 1] if '--mode' in args else sys.stdin.read()
Path('invocation.json').write_text(json.dumps(dict(args=args, prompt=prompt)))
{before}
note = {note!r}
{after}
if '-o' in args:
    Path(args[args.index('-o') + 1]).write_text(note)
elif '--mode' in args:
    print(json.dumps(dict(status='SUCCESS', response=note)))
else:
    print(json.dumps(dict(result=note, is_error=False)))
''')
        self.binary.chmod(0o700)

    def finish(self):
        self.assertTrue(wait_for(lambda: self.runner.status()['job']['status'] not in ACTIVE))
        return self.runner.status()['job']

    def test_each_agent_output_and_command(self):
        for agent in ('claude', 'agy', 'codex'):
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
                self.assertEqual('셸 명령이 차단' in invocation['prompt'], agent == 'agy')
                if agent == 'claude':
                    self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
                elif agent == 'agy':
                    self.assertEqual(args[args.index('--mode') + 1], 'plan')
                    self.assertIn('--sandbox', args)
                    self.assertIn('output/강의/정리-작업.md', invocation['prompt'])
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
        failed_turn = f"print(json.dumps(dict(status='ERROR', response={NOTE!r}))); sys.exit(0)"
        for before, note in [('sys.exit(1)', NOTE), ('', ''), ('', '작업을 완료했습니다.'), (failed_turn, NOTE)]:
            self.fake(before, note)
            self.runner.submit('강의', 'agy', ['week_01_01'])
            self.assertEqual(self.finish()['status'], 'failed')
            self.assertFalse((self.notes / 'week_01_01.md').exists())

    def test_misshapen_note_is_retried_once_with_server_feedback(self):
        bad = NOTE.replace('## 핵심 암기사항\n\n근거\n\n', '') + '## 핵심 암기사항\n\n근거\n'
        self.fake(after=f"note = {NOTE!r} if '형식 검사' in prompt and '거부' in prompt else {bad!r}")
        self.runner.submit('강의', 'claude', ['week_01_01'])
        self.assertEqual(self.finish()['status'], 'done')
        self.assertEqual((self.notes / 'week_01_01.md').read_text(), NOTE)
        self.fake(note=bad)
        (self.notes / 'week_01_01.md').unlink()
        self.runner.submit('강의', 'claude', ['week_01_01'])
        job = self.finish()
        self.assertEqual(job['status'], 'failed')
        self.assertIn('핵심 암기사항', job['error'])
        self.assertFalse((self.notes / 'week_01_01.md').exists())

    def test_each_agent_retries_missing_timestamps_and_rejects_persistent_errors(self):
        bad = NOTE.replace('설명', '근거: 전사 [00:00:05]')
        for agent in ('claude', 'agy', 'codex'):
            with self.subTest(agent=agent):
                self.fake(after=f"note = {NOTE!r} if '00:00:05은 전사체에 없습니다' in prompt else {bad!r}")
                self.runner.submit('강의', agent, ['week_01_01'])
                self.assertEqual(self.finish()['status'], 'done')
                note = self.notes / 'week_01_01.md'
                self.assertEqual(note.read_text(), NOTE)
                note.unlink()
                self.fake(note=bad)
                self.runner.submit('강의', agent, ['week_01_01'])
                self.assertEqual(self.finish()['status'], 'failed')
                self.assertFalse(note.exists())

    def test_invalid_timestamp_does_not_replace_existing_note(self):
        self.notes.mkdir(parents=True)
        note = self.notes / 'week_01_01.md'
        note.write_text('기존 노트')
        self.fake(note=NOTE.replace('설명', '근거: 전사 [00:00:05]'))
        self.runner.submit('강의', 'codex', ['week_01_01'], replace=True)
        self.assertEqual(self.finish()['status'], 'failed')
        self.assertEqual(note.read_text(), '기존 노트')
        self.assertFalse((self.notes / '.history').exists())

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

    def test_replace_regenerates_existing_note_and_archives_the_old_one(self):
        self.notes.mkdir(parents=True)
        note = self.notes / 'week_01_01.md'
        note.write_text('내가 고친 기존 노트')
        self.runner.submit('강의', 'codex', ['week_01_01'], replace=True)
        self.assertEqual(self.finish()['status'], 'done')
        self.assertEqual(note.read_text(), NOTE)
        archived = list((self.notes / '.history').glob('week_01_01-*.md'))
        self.assertEqual([path.read_text() for path in archived], ['내가 고친 기존 노트'])

    def test_replace_keeps_old_note_when_generation_fails(self):
        self.notes.mkdir(parents=True)
        note = self.notes / 'week_01_01.md'
        note.write_text('기존 노트')
        self.fake('sys.exit(1)')
        self.runner.submit('강의', 'codex', ['week_01_01'], replace=True)
        self.assertEqual(self.finish()['status'], 'failed')
        self.assertEqual(note.read_text(), '기존 노트')
        self.assertFalse((self.notes / '.history').exists())

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
        self.fake(note=NOTE.replace('00:00:00', '00:01:00'))
        self.runner.submit('강의', 'claude', ['week_01_02'])
        job = self.finish()
        self.assertEqual((job['status'], job['completed'], job['total']), ('done', 1, 1))
        self.assertEqual(first.stat().st_mtime_ns, timestamp)

    def test_only_selected_lecture_is_processed_and_duplicates_are_deduplicated(self):
        (self.source / 'week_01_02.md').write_text('[00:01:00] 다른 회차')
        selected_note = NOTE.replace('00:00:00', '00:01:00')
        self.fake(note=selected_note)
        self.runner.submit('강의', 'codex', ['week_01_02', 'week_01_02'])
        job = self.finish()
        self.assertEqual((job['total'], job['stems']), (1, ['week_01_02']))
        self.assertFalse((self.notes / 'week_01_01.md').exists())
        self.assertEqual((self.notes / 'week_01_02.md').read_text(), selected_note)

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
            submit.assert_called_once_with('강의', 'claude', ['week_01_01'], False)
            self.client.post(path, headers=H, json={'agent': 'codex', 'stems': ['week_01_01'], 'replace': True})
            submit.assert_called_with('강의', 'codex', ['week_01_01'], True)

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

class PageImageApiTests(WebTestCase):
    def test_page_images_are_limited_to_generated_paths(self):
        folder = self.make_course() / 'pages' / '한글 교안'
        folder.mkdir(parents=True)
        png = b'\x89PNG\r\n\x1a\nimage'
        (folder / 'p010.png').write_bytes(png)
        url = '/api/local/courses/강의/pages/한글 교안/p010.png'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, png)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(self.client.get(url, headers={'Host': 'evil.test'}).status_code, 403)
        self.assertEqual(self.client.get(url.replace('p010.png', 'p999.png')).status_code, 404)
        self.assertEqual(self.client.get(url.replace('p010.png', 'p010.txt')).status_code, 422)
        self.assertNotEqual(self.client.get(url.replace('한글 교안', '%2e%2e%5csecret')).status_code, 200)
        other = self.make_course('다른 강의') / 'pages' / '문서'
        other.mkdir(parents=True)
        target = other / 'p001.png'
        target.write_bytes(png)
        (folder / 'p011.png').symlink_to(target)
        self.assertEqual(self.client.get(url.replace('p010.png', 'p011.png')).status_code, 404)
        (folder.parent / '링크').symlink_to(other)
        self.assertEqual(self.client.get('/api/local/courses/강의/pages/링크/p001.png').status_code, 404)

    def test_page_picker_lists_only_existing_safe_images(self):
        folder = self.make_course() / 'pages' / '한글 교안'
        folder.mkdir(parents=True)
        for name in ('p002.png', 'p010.png', 'p001.txt', 'preview.png'):
            (folder / name).write_text('page')
        (folder / 'p003.png').symlink_to(folder / 'p002.png')
        (folder.parent / '링크').symlink_to(folder)
        self.assertEqual(self.client.get('/api/local/courses/강의/pages').json(), {
            'documents': [{'name': '한글 교안', 'pages': ['p002.png', 'p010.png']}]})
        self.make_course('빈 강의')
        self.assertEqual(self.client.get('/api/local/courses/빈 강의/pages').json(), {'documents': []})
        self.assertEqual(self.client.get('/api/local/courses/강의/pages', headers={'Host': 'evil.test'}).status_code, 403)


class NoteEditApiTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.make_course()
        self.note = self.root / 'output' / '강의' / 'notes' / 'week_01_01.md'
        self.note.parent.mkdir(parents=True)
        self.note.write_text(NOTE, encoding='utf-8')
        self.url = '/api/local/courses/강의/notes/week_01_01'

    def test_edit_persists_and_retry_is_idempotent(self):
        payload = {'text': NOTE + '\n내 메모와 교안 사진', 'originalText': NOTE}
        for _ in range(2):
            response = self.client.put(self.url, headers=H, json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['text'], payload['text'])
        self.assertEqual(self.client.get(self.url).json()['text'], payload['text'])
        self.assertEqual(self.note.read_text(), payload['text'])

    def test_edit_validation_and_local_guard_preserve_note(self):
        payload = {'text': '수정', 'originalText': NOTE}
        self.assertEqual(self.client.put(self.url, json=payload).status_code, 403)
        self.assertEqual(self.client.put(self.url, headers={**H, 'Host': 'evil.test'}, json=payload).status_code, 403)
        for invalid in ({'text': '수정'}, {'text': '', 'originalText': NOTE}, {'text': '  \n ', 'originalText': NOTE},
                        {'text': 'x' * 1_000_001, 'originalText': NOTE}):
            self.assertEqual(self.client.put(self.url, headers=H, json=invalid).status_code, 422)
        self.assertEqual(self.client.put(self.url.replace('week_01_01', 'week_02_01'), headers=H, json=payload).status_code, 404)
        self.assertEqual(self.note.read_text(), NOTE)

    def test_two_tabs_cannot_overwrite_each_others_changes(self):
        def save(text):
            return self.client.put(self.url, headers=H, json={'text': text, 'originalText': NOTE})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['첫 번째 수정', '두 번째 수정']))
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        winner = next(result.json()['text'] for result in results if result.status_code == 200)
        self.assertEqual(self.note.read_text(), winner)

    def test_failed_replace_preserves_previous_note_and_cleans_temporary_file(self):
        with patch('server.lecture.web.os.replace', side_effect=OSError('disk full')):
            response = self.client.put(self.url, headers=H, json={'text': '수정', 'originalText': NOTE})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.note.read_text(), NOTE)
        self.assertEqual(list(self.note.parent.glob('.note-*')), [])

    def test_symlinks_cannot_edit_other_files(self):
        other = self.root / 'other.md'
        other.write_text('보존')
        self.note.unlink()
        self.note.symlink_to(other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.put(self.url, headers=H, json={'text': '수정', 'originalText': '보존'}).status_code, 404)
        self.assertEqual(other.read_text(), '보존')


if __name__ == '__main__':
    unittest.main()
