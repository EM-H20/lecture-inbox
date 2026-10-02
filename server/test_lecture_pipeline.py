import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lecture.cli import main
from server.lecture.layout import TranscriptExists
from server.lecture.pipeline import transcribe_lecture
from server.lecture.transcript import Segment, Transcript
from server.lecture_testing import make_pdf


class FakeEngine:
    def __init__(self, segments=None, error=None):
        self.segments = [Segment(0.0, 2.4, "안녕하세요")] if segments is None else segments
        self.error = error
        self.calls = 0

    def transcribe(self, wav, source_filename):
        self.calls += 1
        if self.error:
            raise self.error
        return Transcript("ggml-small", "ko", source_filename, 60.0, self.segments)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "lec.mp4"
        self.source.write_bytes(b"video")
        self.wav = self.root / "fake.wav"

    def tearDown(self):
        self.temp.cleanup()

    def normalize(self, source):
        self.wav.write_bytes(b"RIFF")
        return self.wav

    def run_pipeline(self, engine, week=1, session=2, **kwargs):
        return transcribe_lecture(self.root, "강의", week, session, self.source, engine,
                                  normalize=self.normalize, **kwargs)

    def test_writes_transcripts_and_work_order_and_removes_the_wav(self):
        paths, messages = self.run_pipeline(FakeEngine())
        self.assertEqual([p.name for p in paths], ["week_01_02.md", "week_01_02.txt"])
        self.assertEqual(paths[0].read_text(encoding="utf-8"), "[00:00:00] 안녕하세요\n")
        work_order = self.root / "output" / "강의" / "정리-작업.md"
        self.assertIn("정리 대기", work_order.read_text(encoding="utf-8"))
        self.assertTrue(any("교안 없음" in m for m in messages))
        self.assertFalse(self.wav.exists())

    def test_existing_transcript_is_refused_before_transcribing(self):
        engine = FakeEngine()
        self.run_pipeline(engine)
        with self.assertRaises(TranscriptExists):
            self.run_pipeline(engine)
        self.assertEqual(engine.calls, 1)

    def test_force_overwrites(self):
        self.run_pipeline(FakeEngine())
        paths, _ = self.run_pipeline(FakeEngine([Segment(0.0, 1.0, "새 내용")]), force=True)
        self.assertEqual(paths[0].read_text(encoding="utf-8"), "[00:00:00] 새 내용\n")

    def test_engine_failure_removes_the_wav_and_writes_nothing(self):
        with self.assertRaises(RuntimeError):
            self.run_pipeline(FakeEngine(error=RuntimeError("boom")))
        self.assertFalse(self.wav.exists())
        self.assertFalse((self.root / "output").exists())
        self.assertFalse((self.root / "sources").exists())

    def test_silent_audio_writes_nothing(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_pipeline(FakeEngine(segments=[]))
        self.assertIn("음성", str(caught.exception))
        self.assertFalse(self.wav.exists())
        self.assertFalse((self.root / "output").exists())
        self.assertFalse((self.root / "sources").exists())

    def test_bad_pdf_does_not_block_the_transcript(self):
        documents = self.root / "sources" / "강의" / "교안"
        documents.mkdir(parents=True)
        (documents / "깨짐.pdf").write_bytes(b"garbage")
        paths, messages = self.run_pipeline(FakeEngine())
        self.assertTrue(paths[0].is_file())
        self.assertTrue(any("'깨짐' 준비 실패" in m for m in messages))

    def test_prepares_every_document_it_finds(self):
        documents = self.root / "sources" / "강의" / "교안"
        documents.mkdir(parents=True)
        (documents / "1주차.pdf").write_bytes(make_pdf(["a", "b"]))
        (documents / "2주차.pdf").write_bytes(make_pdf(["c"]))
        _, messages = self.run_pipeline(FakeEngine())
        self.assertTrue(any("'1주차'" in m and "2장 생성" in m for m in messages))
        self.assertTrue(any("'2주차'" in m and "1장 생성" in m for m in messages))

    def test_missing_source_file(self):
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_pipeline(FakeEngine())

    def test_reports_each_stage_in_order(self):
        stages = []
        self.run_pipeline(FakeEngine(), on_stage=stages.append)
        self.assertEqual(stages, ["converting", "transcribing", "saving"])

    def test_a_raising_stage_callback_aborts_and_removes_the_wav(self):
        def refuse(stage):
            if stage == "transcribing":
                raise RuntimeError("취소됨")

        engine = FakeEngine()
        with self.assertRaises(RuntimeError):
            self.run_pipeline(engine, on_stage=refuse)
        self.assertEqual(engine.calls, 0)
        self.assertFalse(self.wav.exists())
        self.assertFalse((self.root / "sources").exists())


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, argv, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv, root=self.root, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def test_prepare_writes_the_work_order(self):
        code, out, _ = self.call(["prepare", "--course", "강의"])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "output" / "강의" / "정리-작업.md").is_file())
        self.assertIn("교안 없음", out)

    def test_missing_input_file_reports_an_error(self):
        code, _, err = self.call(["transcribe", str(self.root / "none.mp4"), "--course", "강의",
                                  "--week", "1", "--session", "1"], engine_factory=lambda root: FakeEngine())
        self.assertEqual(code, 1)
        self.assertIn("파일을 찾을 수 없습니다", err)

    def test_invalid_week_reports_an_error(self):
        source = self.root / "lec.mp4"
        source.write_bytes(b"video")
        code, _, err = self.call(["transcribe", str(source), "--course", "강의", "--week", "0", "--session", "1"],
                                 engine_factory=lambda root: FakeEngine())
        self.assertEqual(code, 1)
        self.assertIn("주차", err)

    def test_transcribe_points_the_user_at_the_work_order(self):
        source = self.root / "lec.mp4"
        source.write_bytes(b"video")
        paths = [self.root / "sources" / "강의" / "전사" / "week_01_01.md"]
        with patch("server.lecture.cli.transcribe_lecture", return_value=(paths, ["교안 없음"])):
            code, out, _ = self.call(["transcribe", str(source), "--course", "강의", "--week", "1", "--session", "1"],
                                     engine_factory=lambda root: FakeEngine())
        self.assertEqual(code, 0)
        self.assertIn("sources/강의/전사/week_01_01.md", out)
        self.assertIn("output/강의/정리-작업.md대로", out)
