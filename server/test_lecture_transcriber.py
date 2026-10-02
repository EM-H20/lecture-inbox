import tempfile
import threading
import unittest
from pathlib import Path

from server.lecture.layout import LayoutError, TranscriptExists
from server.lecture.transcriber import Transcriber
from server.lecture_testing import FakeEngine, make_fake_normalize, wait_for


class TranscriberTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gate = threading.Event()
        self.engine_kwargs = {}
        self.engines = []
        self.transcriber = Transcriber(self.root, self.make_engine, normalize=make_fake_normalize(self.root))

    def tearDown(self):
        self.gate.set()
        self.transcriber.close()
        self.temp.cleanup()

    def make_engine(self, root):
        engine = FakeEngine(**self.engine_kwargs)
        self.engines.append(engine)
        return engine

    def upload(self, name="lec.mp4"):
        folder = self.transcriber.uploads_dir
        folder.mkdir(exist_ok=True)
        path = folder / name
        path.write_bytes(b"video")
        return path

    def submit(self, source, session=2, **kwargs):
        return self.transcriber.submit(course="강의", week=1, session=session, source=source,
                                       filename=source.name, **kwargs)

    def transcript(self, session=2):
        return self.root / "sources" / "강의" / "전사" / f"week_01_{session:02d}.md"

    def test_runs_a_job_to_done_and_removes_the_upload(self):
        source = self.upload()
        job = self.submit(source)
        self.assertTrue(wait_for(lambda: job.status == "done"))
        self.assertTrue(self.transcript().is_file())
        self.assertFalse(source.exists())

    def test_failure_is_reported_and_removes_the_upload(self):
        self.engine_kwargs = {"error": RuntimeError("boom")}
        source = self.upload()
        job = self.submit(source)
        self.assertTrue(wait_for(lambda: job.status == "failed"))
        self.assertEqual(job.error, "boom")
        self.assertFalse(source.exists())
        self.assertFalse(self.transcript().exists())

    def test_unexpected_error_hides_the_details(self):
        self.engine_kwargs = {"error": ValueError("secret path /Users/x")}
        job = self.submit(self.upload())
        self.assertTrue(wait_for(lambda: job.status == "failed"))
        self.assertNotIn("secret", job.error)
        self.assertIn("오류", job.error)

    def test_jobs_run_one_at_a_time_in_order(self):
        self.engine_kwargs = {"gate": self.gate}
        first = self.submit(self.upload("a.mp4"), session=1)
        second = self.submit(self.upload("b.mp4"), session=2)
        self.assertTrue(wait_for(lambda: first.status == "transcribing"))
        self.assertEqual(second.status, "waiting")
        self.assertEqual(len(self.engines), 1)
        self.gate.set()
        self.assertTrue(wait_for(lambda: first.status == "done" and second.status == "done"))
        self.assertTrue(self.transcript(1).is_file() and self.transcript(2).is_file())

    def test_cancel_a_queued_job(self):
        self.engine_kwargs = {"gate": self.gate}
        first = self.submit(self.upload("a.mp4"), session=1)
        queued_source = self.upload("b.mp4")
        second = self.submit(queued_source, session=2)
        self.assertTrue(wait_for(lambda: first.status == "transcribing"))
        self.transcriber.cancel(second.id)
        self.assertEqual(second.status, "cancelled")
        self.assertFalse(queued_source.exists())
        self.gate.set()
        self.assertTrue(wait_for(lambda: first.status == "done"))
        self.assertEqual(len(self.engines), 1)  # the cancelled job never reached an engine
        self.assertFalse(self.transcript(2).exists())

    def test_cancel_a_running_job_stops_the_engine(self):
        self.engine_kwargs = {"gate": self.gate}
        source = self.upload()
        job = self.submit(source)
        self.assertTrue(wait_for(lambda: job.status == "transcribing"))
        self.transcriber.cancel(job.id)
        self.assertTrue(wait_for(lambda: job.status == "cancelled"))
        self.assertTrue(self.engines[0].stopped.is_set())
        self.assertFalse(source.exists())
        self.assertFalse(self.transcript().exists())

    def test_existing_transcript_is_refused_unless_forced(self):
        first = self.submit(self.upload("a.mp4"))
        self.assertTrue(wait_for(lambda: first.status == "done"))
        with self.assertRaises(TranscriptExists):
            self.submit(self.upload("b.mp4"))
        forced = self.submit(self.upload("c.mp4"), force=True)
        self.assertTrue(wait_for(lambda: forced.status == "done"))

    def test_same_lecture_already_queued_is_refused(self):
        self.engine_kwargs = {"gate": self.gate}
        first = self.submit(self.upload("a.mp4"))
        self.assertTrue(wait_for(lambda: first.status == "transcribing"))
        with self.assertRaises(TranscriptExists):
            self.submit(self.upload("b.mp4"))

    def test_invalid_course_or_numbers_are_refused(self):
        source = self.upload()
        with self.assertRaises(LayoutError):
            self.transcriber.submit(course="   ", week=1, session=1, source=source, filename="x")
        with self.assertRaises(LayoutError):
            self.transcriber.submit(course="강의", week=0, session=1, source=source, filename="x")

    def test_close_cancels_running_and_queued_jobs_and_cleans_uploads(self):
        self.engine_kwargs = {"gate": self.gate}
        first_source, second_source = self.upload("a.mp4"), self.upload("b.mp4")
        first = self.submit(first_source, session=1)
        second = self.submit(second_source, session=2)
        self.assertTrue(wait_for(lambda: first.status == "transcribing"))
        self.transcriber.close()
        self.assertEqual((first.status, second.status), ("cancelled", "cancelled"))
        self.assertTrue(self.engines[0].stopped.is_set())
        self.assertFalse(first_source.exists() or second_source.exists())

    def test_close_keeps_finished_transcripts(self):
        job = self.submit(self.upload())
        self.assertTrue(wait_for(lambda: job.status == "done"))
        self.transcriber.close()
        self.assertTrue(self.transcript().is_file())

    def test_a_job_submitted_after_close_is_refused(self):
        self.transcriber.close()
        with self.assertRaises(RuntimeError):
            self.submit(self.upload())

    def test_release_hook_runs_once_and_borrowed_files_are_kept(self):
        released = []
        borrowed = self.root / "borrowed.mp4"
        borrowed.write_bytes(b"video")
        job = self.submit(borrowed, cleanup=False, release=lambda: released.append(1))
        self.assertTrue(wait_for(lambda: job.status == "done"))
        self.assertTrue(wait_for(lambda: released == [1]))
        self.assertTrue(borrowed.exists())

    def test_status_and_elapsed_time_are_visible_while_running(self):
        self.engine_kwargs = {"gate": self.gate}
        job = self.submit(self.upload())
        self.assertTrue(wait_for(lambda: job.status == "transcribing"))
        info = self.transcriber.list()[0]
        self.assertEqual((info["id"], info["status"], info["course"]), (job.id, "transcribing", "강의"))
        self.assertGreaterEqual(info["elapsedSeconds"], 0)
