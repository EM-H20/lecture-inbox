import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from server.lecture.evaluation import main
from server.lecture.study import note_problems, timestamp_audit
from server.test_lecture_study import NOTE


class EvidenceTests(unittest.TestCase):
    def test_occurrences_metadata_and_reversed_ranges(self):
        transcript = '[00:00:00] 첫 발언\n[00:00:10] 다음\n[00:00:10] 같은 시각\n'
        text = NOTE.replace('설명', '근거: 전사 약 [00:00:10]–[00:00:00], [00:00:05], [00:00:05]')
        audit = timestamp_audit(text, transcript)
        self.assertEqual(audit['source_timestamp_count'], 2)
        self.assertEqual(audit['total'], 6)
        self.assertEqual([x['timestamp'] for x in audit['missing']], ['00:00:05', '00:00:05'])
        self.assertEqual(len(audit['reversed_ranges']), 1)
        line = audit['missing'][0]['line']
        self.assertIn('[00:00:05]', text.splitlines()[line - 1])
        self.assertEqual(timestamp_audit(text, '[00:00:05] 다른 회차')['total'], 6)
        self.assertEqual(len(timestamp_audit(text, '[00:00:05] 다른 회차')['missing']), 4)

    def test_code_examples_and_bare_times_are_not_citations(self):
        text = '시계는 12:00:00\n```md\n전사 [01:00:00]\n```\n전사 [00:00:00]\n'
        audit = timestamp_audit(text, '[00:00:00] 실제 발언')
        self.assertEqual(audit['total'], 1)
        self.assertEqual(audit['missing'], [])
        self.assertEqual(note_problems(NOTE, '강의', '.', '[00:00:00] 내용'), [])
        self.assertTrue(note_problems(NOTE, '강의', '.', '발언 시각 없는 전사'))

    def test_malformed_timestamp_is_counted_and_cannot_pass_by_normalization(self):
        transcript = '[00:30:05] 실제 발언'
        text = NOTE.replace('00:00:00–00:00:00', '00:30:5–00:30:05').replace(
            '설명', '전사 [00:30:5], [0:30:05], [00:30:005], [00:30:05]')
        audit = timestamp_audit(text, transcript)
        self.assertEqual(audit['total'], 6)
        self.assertEqual([r['timestamp'] for r in audit['missing']],
                         ['00:30:5', '00:30:5', '0:30:05', '00:30:005'])
        self.assertEqual(audit['reversed_ranges'], [])
        self.assertTrue(any('00:30:5' in p for p in note_problems(text, '강의', '.', transcript)))

    def test_existing_endpoints_can_still_make_an_invalid_range(self):
        text = NOTE.replace('00:00:00–00:00:00', '00:00:10–00:00:00')
        transcript = '[00:00:00] 처음\n[00:00:10] 나중'
        self.assertEqual(timestamp_audit(text, transcript)['missing'], [])
        self.assertTrue(any('역전' in x for x in note_problems(text, '강의', '.', transcript)))
        bracketed = text.replace('00:00:10–00:00:00', '[00:00:10]–[00:00:00]')
        self.assertEqual(len(timestamp_audit(bracketed, transcript)['reversed_ranges']), 1)
        self.assertTrue(timestamp_audit('[00:99:00]', transcript)['missing'])

    def test_metadata_format_error_does_not_hide_bare_citations(self):
        text = NOTE.replace('01주차 01번째', '1주차 1번째').replace(
            '00:00:00–00:00:00', '00:00:00–00:00:09')
        audit = timestamp_audit(text, '[00:00:00] 실제 발언')
        self.assertEqual(audit['total'], 2)
        self.assertEqual(audit['missing'], [{'line': 3, 'timestamp': '00:00:09'}])
        problems = note_problems(text, '강의', '.', '[00:00:00] 실제 발언')
        self.assertTrue(any('NN주차' in p for p in problems))
        self.assertTrue(any('00:00:09' in p for p in problems))

    def test_cli_is_read_only_blinded_and_does_not_claim_semantic_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript = root / 'transcript.md'
            transcript.write_text('[00:00:00] 내용')
            good, bad = root / 'provider-one.md', root / 'provider-two.md'
            good.write_text(NOTE)
            bad.write_text(NOTE.replace('설명', '전사 [00:42:01]'))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(['--root', folder, '--course', '강의', '--transcript', 'transcript.md',
                               '--notes', good.name, bad.name])
            self.assertEqual(result, 1)
            report = json.loads(output.getvalue())
            self.assertEqual([n['candidate_id'] for n in report['notes']], ['N001', 'N002'])
            self.assertEqual([n['mechanical_pass'] for n in report['notes']], [True, False])
            self.assertNotIn('provider-', output.getvalue())
            self.assertIsNone(report['notes'][0]['reliability_score'])
            self.assertEqual(report['notes'][0]['semantic_status'], 'not_evaluated')
            self.assertEqual(report['notes'][0]['note_sha256'], hashlib.sha256(good.read_bytes()).hexdigest())
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_cli_missing_input_is_not_a_quality_failure(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root', folder, '--course', '강의', '--transcript', 'missing.md',
                                   '--notes', 'missing-note.md']), 2)
            (Path(folder) / 'untimed.md').write_text('발언 시각 없는 전사')
            self.assertEqual(main(['--root', folder, '--course', '강의', '--transcript', 'untimed.md',
                                   '--notes', 'missing-note.md']), 2)
