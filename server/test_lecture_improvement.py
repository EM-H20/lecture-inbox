import contextlib
import copy
import fcntl
import io
import json
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

from server.lecture.improvement import (DEFAULTS, GUIDELINES, WEIGHTS, apply_source_patches, assess_round, audit_trace, convergence,
                                        digest, initialize, invoke, read_json, run_loop,
                                        score_review, validate_policy, validate_rubric, verify_inputs, write_json)
from server.test_lecture_study import NOTE


def candidate(agent, score=100, **changes):
    return dict(candidate_id=agent, agent_id=agent, score=score, components=dict(WEIGHTS),
                mechanical_pass=True, guidelines_pass=True, critical_errors=0, judge_gap=0, **changes)


def rounds(count=3):
    return [dict(guidance_sha256='same', candidates=[candidate('codex'), candidate('claude')]) for _ in range(count)]


class SourcePatchTests(unittest.TestCase):
    def proposal(self, *pairs):
        return dict(patches=[dict(old=a, new=b, reason='수정 이유', evidence='전사 근거') for a, b in pairs],
                    unresolved=[], opened_pages=['page.png'])

    def test_edits_use_original_offsets_and_preserve_surrounding_text(self):
        review = self.proposal(('left', 'right'), ('right', 'done'))
        self.assertEqual(apply_source_patches('앞 left / right 뒤', review), '앞 right / done 뒤')
        self.assertEqual(apply_source_patches('앞 제외 뒤', self.proposal(('제외 ', ''))), '앞 뒤')

    def test_ambiguous_missing_and_overlapping_edits_are_rejected(self):
        for text, pairs in [('aaa', [('aa', 'x')]), ('a a', [('a', 'x')]),
                            ('abc', [('missing', 'x')]), ('abc', [('ab', 'x'), ('bc', 'y')])]:
            with self.subTest(text=text, pairs=pairs), self.assertRaises(ValueError):
                apply_source_patches(text, self.proposal(*pairs))


class ConvergenceTests(unittest.TestCase):
    def test_convergence_requires_quality_full_coverage_fixed_guidance_and_stability(self):
        self.assertTrue(convergence(rounds(), DEFAULTS, ['codex', 'claude'])['converged'])
        cases = {}
        r = rounds(2); cases['too few'] = r
        r = rounds(); r[0]['guidance_sha256'] = 'old'; cases['changed prompt'] = r
        r = rounds(); r[1]['candidates'].pop(); cases['missing provider'] = r
        r = rounds(); r[1]['candidates'][0]['score'] = 80; cases['low quality'] = r
        r = rounds(); r[1]['candidates'][0]['critical_errors'] = 1; cases['critical error'] = r
        r = rounds(); r[1]['candidates'][0]['mechanical_pass'] = False; cases['bad timestamp'] = r
        r = rounds(); r[1]['candidates'][0]['guidelines_pass'] = False; cases['bad questions'] = r
        r = rounds(); r[1]['candidates'][0]['judge_gap'] = 4; cases['judge disagreement'] = r
        r = rounds(); r[1]['candidates'][0]['components']['errors'] = 7.5; cases['masked component'] = r
        r = rounds(); r[1]['candidates'][0]['score'] = 98; cases['round drift'] = r
        r = rounds(); r[1]['candidates'][0]['score'] = 96; cases['provider gap'] = r
        r = rounds(); r[1]['candidates'][0]['components']['facts'] = 38; cases['component drift'] = r
        r = rounds(); r[1]['candidates'][0]['components']['facts'] = 37; cases['component gap'] = r
        for name, data in cases.items():
            with self.subTest(name):
                self.assertFalse(convergence(data, DEFAULTS, ['codex', 'claude'])['converged'])
        self.assertFalse(convergence([], DEFAULTS, ['codex', 'claude'])['converged'])

    def test_bad_thresholds_and_plateaus_cannot_be_success(self):
        for overrides in ({'min_score': float('nan')}, {'window': 1}, {'window': 3.5},
                          {'max_rounds': 2}, {'agent_gap': -1}, {'min_score': 101}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_policy(dict(DEFAULTS, **overrides))
        data = rounds()
        for r in data:
            for c in r['candidates']:
                c['score'] = 50
        self.assertFalse(convergence(data, DEFAULTS, ['codex', 'claude'])['converged'])

    def test_equal_judge_totals_cannot_hide_disagreeing_components(self):
        data = rounds()
        a, b = dict(WEIGHTS, facts=37), dict(WEIGHTS, traps=27)
        data[-1]['candidates'][0]['judge_scores'] = {'a': {'components': a}, 'b': {'components': b}}
        self.assertFalse(convergence(data, DEFAULTS, ['codex', 'claude'])['converged'])

    def test_trace_rejects_global_reads_and_counts_image_input(self):
        workspace = Path('/tmp/corpus')
        events = [dict(type='item.completed', item=dict(type='command_execution', command='cat /Users/a/.codex/skills/task-observer/SKILL.md'))]
        self.assertTrue(audit_trace(events, workspace)['violations'])
        events = [dict(type='assistant', message=dict(content=[dict(type='tool_use', input=dict(file_path='/tmp/corpus/p001.png'))]))]
        self.assertEqual(audit_trace(events, workspace), dict(opened_pages=['p001.png'], violations=[]))
        events = [dict(type='assistant', message=dict(content=[dict(type='tool_use', input=dict(path='/tmp/corpus', pattern='*.png'))]))]
        self.assertEqual(audit_trace(events, workspace)['violations'], [])
        self.assertEqual(audit_trace([], workspace, ['p001.png'])['opened_pages'], ['p001.png'])


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = 'sources/강의/pages/교안/p001.png'
        p = self.root / self.page
        p.parent.mkdir(parents=True)
        p.write_bytes(b'png')
        self.transcript = self.root / 'sources/강의/전사/week_01_01.md'
        self.transcript.parent.mkdir(parents=True)
        self.transcript.write_text('[00:00:00] 내용')
        (self.root / '정리-지침.md').write_text('기본 지침')
        self.rubric = dict(version='test-v1', reviewed=True, transcript_sha256=digest(self.transcript),
                           scope_pages=[self.page], allowed_pages=[],
                           facts=[dict(id='F1', claim='내용', accept='동의어 허용', timestamps=['00:00:00'], pages=[self.page])],
                           traps=[dict(id='T1', claim='함정', accept='구분', timestamps=['00:00:00'], pages=[self.page])])
        write_json(self.root / 'rubric.json', self.rubric)
        self.review = dict(facts=[dict(id='F1', **{'pass': True}, note_lines=[9], reason='근거 일치')],
                           traps=[dict(id='T1', **{'pass': True}, note_lines=[9], reason='조건 일치')],
                           guidelines=[dict(id=k, **{'pass': True}, note_lines=[1], reason='지침 일치') for k in GUIDELINES],
                           citations=[dict(claim='내용', source='전사 [00:00:00]', note_line=9, supported=True, reason='실제 내용')],
                           covered_facts=['F1'], errors=[], opened_pages=[self.page])
        self.calls = []

    def setup_run(self, source_review=False, **policy):
        with patch('server.lecture.improvement.shutil.which', return_value='/fake'), \
                patch('server.lecture.improvement.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'fake-version')):
            return initialize(self.root, self.root / 'run', '강의', self.transcript, self.root / 'rubric.json',
                              ['codex', 'claude'], ['codex', 'claude'], dict(DEFAULTS, **policy), source_review=source_review)

    def fake(self, agent, workspace, prompt, folder, timeout):
        folder.mkdir(parents=True, exist_ok=False)
        self.calls.append((agent, prompt, folder))
        require_files = (workspace / 'sources/강의/전사/week_01_01.md').is_file()
        self.assertTrue(require_files)
        self.assertFalse((workspace / 'state.json').exists())
        if folder.name.startswith('generate-'):
            self.assertFalse((workspace / 'frozen-rubric.json').exists())
            self.assertFalse((workspace / 'candidate.md').exists())
            return NOTE
        if folder.name.startswith('source-pass-'):
            self.assertFalse((workspace / 'frozen-rubric.json').exists())
            self.assertFalse((workspace / 'candidate-lines.txt').exists())
            self.assertTrue((workspace / 'common-guidance.md').exists())
            self.assertIsInstance(read_json(workspace / 'transcript-quote-hints.json'), list)
            self.assertEqual(agent, 'codex')
            return json.dumps(dict(patches=[], unresolved=[], opened_pages=[self.page]))
        if folder.name.startswith('judge-'):
            self.assertTrue((workspace / 'candidate-lines.txt').exists())
            self.assertNotIn('private-mapping', prompt)
            return json.dumps(self.review)
        if folder.name.startswith('guidance-check-'):
            return json.dumps(dict(generalizable=True, preserves_requirements=True, reason='절차만 변경'))
        return '원자료를 다시 확인한다.'

    def test_scores_are_computed_and_missing_judgments_fail_closed(self):
        mechanical = {'timestamps': {'total': 2, 'missing': []}}
        self.assertEqual(score_review(self.review, self.rubric, NOTE, mechanical)['score'], 100)
        bad = copy.deepcopy(self.review); bad['facts'] = []
        with self.assertRaisesRegex(ValueError, '항목 수'):
            score_review(bad, self.rubric, NOTE, mechanical)
        bad = copy.deepcopy(self.review); bad['facts'][0]['pass'] = 'true'
        with self.assertRaises(ValueError):
            score_review(bad, self.rubric, NOTE, mechanical)
        bad = copy.deepcopy(self.review); bad['facts'][0]['note_lines'] = [999]
        with self.assertRaises(ValueError):
            score_review(bad, self.rubric, NOTE, mechanical)
        bad = copy.deepcopy(self.review); bad['opened_pages'] = []
        with self.assertRaises(ValueError):
            score_review(bad, self.rubric, NOTE, mechanical)
        bad = copy.deepcopy(self.review); bad['citations'] *= 2
        with self.assertRaises(ValueError):
            score_review(bad, self.rubric, NOTE, mechanical)

    def test_three_fresh_rounds_two_blind_judges_and_no_original_mutation(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        run = self.setup_run()
        with patch('server.lecture.improvement.invoke', side_effect=self.fake), contextlib.redirect_stdout(io.StringIO()):
            state = run_loop(run)
            self.assertEqual(state['status'], 'converged')
            self.assertEqual(len(state['rounds']), 3)
            self.assertEqual(len(self.calls), 18)
            run_loop(run)
            self.assertEqual(len(self.calls), 18)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse((self.root / 'output').exists())

    def test_quality_failure_improves_shared_guidance_and_budget_is_not_success(self):
        run = self.setup_run(max_rounds=3)
        self.review['traps'][0]['pass'] = False
        with patch('server.lecture.improvement.invoke', side_effect=self.fake), contextlib.redirect_stdout(io.StringIO()):
            state = run_loop(run)
        self.assertEqual(state['status'], 'stalled')
        self.assertFalse(state['decision']['converged'])
        self.assertEqual(len(state['rounds']), 2)
        improved_prompts = [p for _, p, f in self.calls if f.name.startswith('generate-') and 'round-002' in str(f)]
        self.assertEqual(len(improved_prompts), 2)
        self.assertTrue(all('원자료를 다시 확인한다.' in p for p in improved_prompts))

    def test_source_review_empty_pass_stops_and_never_receives_gold(self):
        run = self.setup_run(source_review=True)
        with patch('server.lecture.improvement.invoke', side_effect=self.fake), contextlib.redirect_stdout(io.StringIO()):
            state = run_loop(run)
        self.assertEqual(state['status'], 'converged')
        self.assertEqual(len(self.calls), 24)
        self.assertEqual(len(list(run.glob('round-*/N*/source-pass-*.json'))), 6)
        for row in state['rounds']:
            for c in row['candidates']:
                self.assertIn('draft.md', c['artifact_hashes'])
                self.assertIn('source-pass-001.json', c['artifact_hashes'])

    def test_source_review_resume_reuses_draft_and_completed_pass_with_two_pass_cap(self):
        run = self.setup_run(source_review=True)
        fail_once = True
        def review(*args):
            nonlocal fail_once
            result = self.fake(*args)
            _, workspace, _, folder, _ = args
            if not folder.name.startswith('source-pass-'):
                return result
            text = (workspace / 'candidate.md').read_text()
            if folder.name.startswith('source-pass-001-'):
                self.assertEqual(text, NOTE)
                old, new = '설명', '설명 보완'
            else:
                self.assertTrue(folder.name.startswith('source-pass-002-'))
                self.assertEqual(text, NOTE.replace('설명', '설명 보완'))
                if fail_once:
                    fail_once = False
                    raise RuntimeError('source review disconnected')
                old, new = '설명 보완', '설명 보완 확인'
            return json.dumps(dict(patches=[dict(old=old, new=new, reason='원자료 대조', evidence='전사')],
                                   unresolved=[], opened_pages=[self.page]))
        with patch('server.lecture.improvement.invoke', side_effect=review), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                run_loop(run)
            draft = next(run.glob('round-*/N*/draft.md'))
            self.assertEqual(draft.read_text(), NOTE)
            self.assertFalse((draft.parent / 'candidate.md').exists())
            draft.write_text(NOTE + 'changed')
            with self.assertRaisesRegex(ValueError, '저장된 초안'):
                run_loop(run)
            draft.write_text(NOTE)
            hints_path = draft.parent / 'quote-hints-001.json'
            saved_hints = hints_path.read_text()
            hints_path.write_text('tampered')
            with self.assertRaisesRegex(ValueError, '전사 문자열 점검'):
                run_loop(run)
            hints_path.write_text(saved_hints)
            state = run_loop(run)
        self.assertEqual(state['status'], 'converged')
        self.assertEqual(len([f for _, _, f in self.calls if f.name.startswith('generate-')]), 6)
        self.assertEqual(len([f for _, _, f in self.calls if f.name.startswith('source-pass-001-')]), 6)
        for note in run.glob('round-*/N*/candidate.md'):
            self.assertEqual(note.read_text(), NOTE.replace('설명', '설명 보완 확인'))

    def test_literal_hints_are_recomputed_after_a_source_patch_without_grades(self):
        self.transcript.write_text('[00:00:00] 내용\n[00:00:05] 전사원문\n')
        self.rubric['transcript_sha256'] = digest(self.transcript)
        write_json(self.root / 'rubric.json', self.rubric)
        table = '\n| 본문 표기 | 전사 표현 | 근거 |\n|---|---|---|\n| 표준어 | 전사원문 | [00:00:00] |\n'
        old, new = '| 전사원문 | [00:00:00] |', '| 전사원문 | [00:00:00], [00:00:05] |'
        run = self.setup_run(source_review=True)
        def with_hints(*args):
            result = self.fake(*args)
            _, workspace, _, folder, _ = args
            if folder.name.startswith('generate-'):
                return NOTE + table
            if folder.name.startswith('source-pass-'):
                hints = read_json(workspace / 'transcript-quote-hints.json')
                if folder.name.startswith('source-pass-001-'):
                    self.assertEqual(len(hints), 1)
                    self.assertEqual(hints[0]['matching_timestamps'], ['00:00:05'])
                    return json.dumps(dict(patches=[dict(old=old, new=new, reason='원문 확인', evidence='전사 [00:00:05]')],
                                           unresolved=[], opened_pages=[self.page]))
                self.assertEqual(hints, [])
            return result
        with patch('server.lecture.improvement.invoke', side_effect=with_hints), contextlib.redirect_stdout(io.StringIO()):
            state = run_loop(run)
        self.assertEqual(state['status'], 'converged')
        for row in state['rounds']:
            for c in row['candidates']:
                self.assertIn('quote-hints-001.json', c['artifact_hashes'])
                self.assertIn('quote-hints-002.json', c['artifact_hashes'])

    def test_source_review_invalid_image_report_cannot_publish_candidate(self):
        run = self.setup_run(source_review=True)
        def invalid(*args):
            result = self.fake(*args)
            if args[3].name.startswith('source-pass-'):
                return json.dumps(dict(patches=[], unresolved=[], opened_pages=['missing.png']))
            return result
        with patch('server.lecture.improvement.invoke', side_effect=invalid), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, '없는 PNG'):
                run_loop(run)
        self.assertFalse(list(run.glob('round-*/N*/candidate.md')))
        self.assertEqual(next(run.glob('round-*/N*/draft.md')).read_text(), NOTE)

    def test_decomposed_korean_source_names_match_composed_rubric_paths(self):
        page = self.root / self.page
        decomposed = self.root / unicodedata.normalize('NFD', self.page)
        if not decomposed.exists():
            decomposed.parent.mkdir(parents=True, exist_ok=True)
            page.rename(decomposed)
        validate_rubric(self.rubric, self.root, self.transcript)

    def test_improvement_interruption_resumes_pending_phase_without_regeneration(self):
        run = self.setup_run()
        self.review['traps'][0]['pass'] = False
        def fail_improvement(*args):
            if args[3].name.startswith('improve-'):
                raise RuntimeError('connection lost')
            return self.fake(*args)
        with patch('server.lecture.improvement.invoke', side_effect=fail_improvement), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'connection lost'):
                run_loop(run)
        saved = read_json(run / 'state.json')
        self.assertEqual(saved['status'], 'execution_failed')
        self.assertEqual(saved['pending_improvement'], 1)
        self.review['traps'][0]['pass'] = True
        with patch('server.lecture.improvement.invoke', side_effect=self.fake), contextlib.redirect_stdout(io.StringIO()):
            state = run_loop(run)
        self.assertEqual(state['status'], 'converged')
        self.assertEqual(len(state['rounds']), 4)
        self.assertEqual(len([f for _, _, f in self.calls if f.name.startswith('generate-') and 'round-001' in str(f)]), 2)

    def test_max_rounds_and_input_tampering(self):
        run = self.setup_run(max_rounds=3)
        self.review['traps'][0]['pass'] = False
        def always_improve(*args):
            if args[3].name.startswith('improve-'):
                return '공통 점검 절차 ' + str(len(self.calls))
            return self.fake(*args)
        with patch('server.lecture.improvement.invoke', side_effect=always_improve), contextlib.redirect_stdout(io.StringIO()):
            state = run_loop(run)
        self.assertEqual(state['status'], 'max_rounds')
        self.assertFalse(state['decision']['converged'])
        (run / 'rubric.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, '라벨'):
            run_loop(run)

    def test_duplicate_runner_is_rejected_by_live_lock(self):
        run = self.setup_run()
        with (run / 'run.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, '이미 실행'):
                run_loop(run)

    def test_resume_rejects_changed_runner_or_validator(self):
        run = self.setup_run()
        config = read_json(run / 'config.json')
        verify_inputs(run, config)
        for name in ('study.py', 'improvement.py'):
            changed = copy.deepcopy(config)
            changed['implementation_hashes'][name] = 'changed'
            with self.assertRaisesRegex(ValueError, '실험 코드'):
                verify_inputs(run, changed)
        config['protocol'] = 'note-improvement-v2'
        with self.assertRaisesRegex(ValueError, '실험 실행·검사 규칙'):
            verify_inputs(run, config)

    def test_non_generalizable_improvement_cannot_reach_generators(self):
        run = self.setup_run()
        self.review['traps'][0]['pass'] = False
        def leak(*args):
            if args[3].name.startswith('guidance-check-'):
                return json.dumps(dict(generalizable=False, preserves_requirements=True, reason='정답 유출'))
            return self.fake(*args)
        with patch('server.lecture.improvement.invoke', side_effect=leak), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, '정답 유출'):
                run_loop(run)
        state = read_json(run / 'state.json')
        self.assertEqual(state['guidance'], 'guidance-000.md')
        self.assertEqual(len(state['rounds']), 1)
        self.assertEqual(state['status'], 'execution_failed')

    def test_real_process_adapters_capture_all_providers_and_reject_failure(self):
        binary = self.root / 'fake-cli'
        binary.write_text(f'''#!{sys.executable}
import json,sys
from pathlib import Path
args=sys.argv[1:]
if '-o' in args:
 Path(args[args.index('-o')+1]).write_text('complete')
 print(json.dumps({{'type':'turn.completed'}}))
else:
 print(json.dumps({{'type':'assistant','message':{{}}}}))
 if '--mode' in args:
  print(json.dumps({{'event':'result','result':{{'status':'SUCCESS','response':'complete','denied_actions':[]}}}}))
 else:
  print(json.dumps({{'type':'result','result':'complete','is_error':False}}))
''')
        binary.chmod(0o700)
        with patch('server.lecture.improvement.shutil.which', return_value=str(binary)):
            for agent in ['codex', 'claude', 'agy']:
                result = invoke(agent, self.root, 'test', self.root / ('call-' + agent), 3)
                self.assertEqual(result, 'complete')
                meta = read_json(self.root / ('call-' + agent) / 'invocation.json')
                self.assertEqual(meta['returncode'], 0)
                self.assertIn('--sandbox' if agent != 'claude' else '--restricted', meta['command'])
                if agent == 'codex':
                    self.assertIn('skills.include_instructions=false', meta['command'])
                    self.assertTrue(any(arg.startswith('developer_instructions=') for arg in meta['command']))
        binary.write_text(f'#!{sys.executable}\nimport sys\nsys.exit(5)\n')
        with patch('server.lecture.improvement.shutil.which', return_value=str(binary)), self.assertRaises(ValueError):
            invoke('codex', self.root, 'test', self.root / 'failed', 3)


if __name__ == '__main__':
    unittest.main()
