import hashlib
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient

from server.app import Job, Session, Store, create_app
from server.lecture.transcriber import Transcriber
from server.lecture_testing import FakeEngine, make_fake_normalize, make_pdf, wait_for

H = {"X-Requested-With": "lecture-inbox"}
BASE = "http://127.0.0.1:4318"


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "project"
        self.root.mkdir()
        (base / "store").mkdir()
        self.gate = threading.Event()
        self.engine_kwargs = {}
        self.engines = []
        self.transcriber = Transcriber(self.root, self.make_engine, normalize=make_fake_normalize(self.root))
        self.store = Store(base / "store", max_bytes=1024)
        self.context = TestClient(create_app(self.store, self.transcriber), base_url=BASE)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.gate.set()
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def make_engine(self, root):
        engine = FakeEngine(**self.engine_kwargs)
        self.engines.append(engine)
        return engine

    def make_course(self, name="강의"):
        folder = self.root / "sources" / name
        folder.mkdir(parents=True, exist_ok=True)
        return folder


class GuardTests(WebTestCase):
    def test_wrong_host_is_refused(self):
        response = self.client.get("/api/local/courses", headers={"Host": "evil.example.com"})
        self.assertEqual(response.status_code, 403)

    def test_localhost_name_is_allowed_with_any_port(self):
        for host in ("localhost:4317", "127.0.0.1", "localhost"):
            self.assertEqual(self.client.get("/api/local/courses", headers={"Host": host}).status_code, 200, host)

    def test_changes_need_the_marker_header_but_reads_do_not(self):
        self.assertEqual(self.client.get("/api/local/courses").status_code, 200)
        self.assertEqual(self.client.post("/api/local/courses", json={"name": "a"}).status_code, 403)
        self.assertEqual(self.client.post("/api/local/courses", json={"name": "a"}, headers=H).status_code, 200)

    def test_put_and_delete_also_need_the_marker_header(self):
        self.make_course()
        params = {"course": "강의", "week": 1, "session": 1}
        self.assertEqual(self.client.put("/api/local/transcriptions", params=params, content=b"x").status_code, 403)
        self.assertEqual(self.client.put("/api/local/courses/강의/documents/1주차.pdf", content=b"x").status_code, 403)
        self.assertEqual(self.client.delete("/api/local/transcriptions/abc").status_code, 403)
        self.assertEqual(self.client.delete("/api/local/courses/강의/documents/1주차").status_code, 403)

    def test_other_sites_get_no_cors_permission(self):
        response = self.client.options("/api/local/transcriptions", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "x-requested-with"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_the_dev_page_may_preflight_put_with_the_marker_header(self):
        response = self.client.options("/api/local/transcriptions", headers={
            "Origin": "http://127.0.0.1:4317", "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "x-requested-with,x-filename"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:4317")
        self.assertIn("PUT", response.headers["access-control-allow-methods"])
        self.assertIn("x-requested-with", response.headers["access-control-allow-headers"].lower())


class CourseTests(WebTestCase):
    def test_status_reports_tools(self):
        body = self.client.get("/api/local/status").json()
        self.assertEqual((body["whisper"], body["whisperMessage"]), (True, ""))
        self.assertIn("ffmpeg", body)

    def test_status_explains_a_missing_model(self):
        def missing(root):
            raise RuntimeError("모델 파일이 없습니다")

        self.transcriber.engine_factory = missing
        body = self.client.get("/api/local/status").json()
        self.assertEqual((body["whisper"], body["whisperMessage"]), (False, "모델 파일이 없습니다"))

    def test_starts_empty(self):
        self.assertEqual(self.client.get("/api/local/courses").json(), {"courses": []})

    def test_create_then_list(self):
        first = self.client.post("/api/local/courses", json={"name": "자료구조"}, headers=H).json()
        again = self.client.post("/api/local/courses", json={"name": "자료구조"}, headers=H).json()
        self.assertEqual((first, again), ({"name": "자료구조", "created": True}, {"name": "자료구조", "created": False}))
        self.assertEqual(self.client.get("/api/local/courses").json()["courses"],
                         [{"name": "자료구조", "documents": [], "lectures": []}])

    def test_hostile_and_blank_names(self):
        name = self.client.post("/api/local/courses", json={"name": "../../x"}, headers=H).json()["name"]
        self.assertNotIn("/", name)
        self.assertTrue((self.root / "sources" / name).is_dir())
        self.assertFalse((self.root.parent / "x").exists())
        self.assertEqual(self.client.post("/api/local/courses", json={"name": "   "}, headers=H).status_code, 400)
        self.assertEqual(self.client.post("/api/local/courses", json={"name": ""}, headers=H).status_code, 422)


class CourseNameTests(WebTestCase):
    def test_previews_the_cleaned_name_and_whether_it_exists(self):
        self.make_course("자료구조")
        existing = self.client.get("/api/local/course-name", params={"name": "자료구조"}).json()
        hostile = self.client.get("/api/local/course-name", params={"name": "../../x"}).json()
        self.assertEqual(existing, {"name": "자료구조", "exists": True})
        self.assertEqual(hostile, {"name": "_.._x", "exists": False})

    def test_blank_or_missing_names_are_refused(self):
        self.assertEqual(self.client.get("/api/local/course-name", params={"name": "   "}).status_code, 400)
        self.assertEqual(self.client.get("/api/local/course-name").status_code, 422)

    def test_previewing_creates_nothing(self):
        self.client.get("/api/local/course-name", params={"name": "새강의"})
        self.assertFalse((self.root / "sources" / "새강의").exists())


class TranscriptViewTests(WebTestCase):
    def test_reads_a_transcript(self):
        folder = self.make_course() / "전사"
        folder.mkdir()
        (folder / "week_01_01.md").write_text("[00:00:00] 안녕하세요\n", encoding="utf-8")
        response = self.client.get(f"/api/local/courses/{quote('강의')}/transcripts/week_01_01")
        self.assertEqual(response.json(), {"stem": "week_01_01", "text": "[00:00:00] 안녕하세요\n"})

    def test_unknown_or_malformed_stems(self):
        self.make_course()
        self.assertEqual(self.client.get("/api/local/courses/강의/transcripts/week_09_09").status_code, 404)
        self.assertEqual(self.client.get("/api/local/courses/강의/transcripts/week_1_1").status_code, 422)
        self.assertEqual(self.client.get("/api/local/courses/강의/transcripts/passwd").status_code, 422)


class DocumentTests(WebTestCase):
    def put_doc(self, name, content, course="강의"):
        return self.client.put(f"/api/local/courses/{quote(course)}/documents/{quote(name)}", content=content, headers=H)

    def courses(self):
        return self.client.get("/api/local/courses").json()["courses"]

    def test_saves_the_document_and_prepares_its_pages(self):
        folder = self.make_course()
        response = self.put_doc("1주차.pdf", make_pdf(["Hello", "World"]))
        self.assertEqual((response.status_code, response.json()), (200, {"document": "1주차", "status": "prepared", "pages": 2}))
        self.assertTrue((folder / "교안" / "1주차.pdf").is_file())
        self.assertTrue((folder / "pages" / "1주차" / "p002.png").is_file())
        self.assertTrue((self.root / "output" / "강의" / "정리-작업.md").is_file())
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])

    def test_several_documents_live_side_by_side(self):
        self.make_course()
        self.put_doc("1주차.pdf", make_pdf(["a", "b"]))
        self.put_doc("2주차 실습", make_pdf(["c"]))
        self.assertEqual(self.courses()[0]["documents"], [{"name": "1주차", "pages": 2}, {"name": "2주차 실습", "pages": 1}])

    def test_the_same_name_replaces_the_document(self):
        folder = self.make_course()
        self.put_doc("1주차.pdf", make_pdf(["a", "b", "c"]))
        self.put_doc("1주차.pdf", make_pdf(["a"]))
        self.assertEqual(self.courses()[0]["documents"], [{"name": "1주차", "pages": 1}])
        self.assertFalse((folder / "pages" / "1주차" / "p002.png").exists())

    def test_hostile_names_stay_inside_the_documents_folder(self):
        folder = self.make_course()
        self.assertEqual(self.put_doc("..hidden.pdf", make_pdf(["a"])).json()["document"], "hidden")
        self.assertEqual(self.put_doc("a\\b.pdf", make_pdf(["a"])).json()["document"], "a_b")
        self.assertEqual(sorted(p.name for p in (folder / "교안").iterdir()), ["a_b.pdf", "hidden.pdf"])
        self.assertEqual(self.put_doc(".pdf", make_pdf(["a"])).status_code, 400)

    def test_a_non_pdf_is_refused_and_nothing_is_saved(self):
        folder = self.make_course()
        self.assertEqual(self.put_doc("1주차.pdf", b"hello").status_code, 400)
        self.assertEqual(list((folder / "교안").glob("*")) if (folder / "교안").exists() else [], [])
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])

    def test_a_corrupt_pdf_is_refused_and_the_old_one_is_kept(self):
        folder = self.make_course()
        good = make_pdf(["Hello"])
        self.put_doc("1주차.pdf", good)
        self.assertEqual(self.put_doc("1주차.pdf", b"%PDF-1.4\ngarbage").status_code, 422)
        self.assertEqual(hashlib.sha256((folder / "교안" / "1주차.pdf").read_bytes()).digest(), hashlib.sha256(good).digest())

    def test_a_pdf_with_too_many_pages_is_refused_and_the_old_one_is_kept(self):
        folder = self.make_course()
        good = make_pdf(["Hello"])
        self.put_doc("1주차.pdf", good)
        with patch("server.lecture.web.MAX_PAGES", 1):
            response = self.put_doc("1주차.pdf", make_pdf(["a", "b"]))
        self.assertEqual(response.status_code, 422)
        self.assertEqual((folder / "교안" / "1주차.pdf").read_bytes(), good)
        self.assertEqual(len(list((folder / "pages" / "1주차").glob("p*.png"))), 1)

    def test_unknown_course_is_404(self):
        self.assertEqual(self.put_doc("1주차.pdf", make_pdf(["a"]), course="없는강의").status_code, 404)

    def test_an_oversized_pdf_is_refused(self):
        self.make_course()
        with patch("server.lecture.web.MAX_PDF_BYTES", 10):
            self.assertEqual(self.put_doc("1주차.pdf", make_pdf(["a"])).status_code, 413)

    def test_delete_removes_the_document_and_its_pages(self):
        folder = self.make_course()
        self.put_doc("1주차.pdf", make_pdf(["a"]))
        self.put_doc("2주차.pdf", make_pdf(["b"]))
        response = self.client.delete(f"/api/local/courses/{quote('강의')}/documents/{quote('1주차')}", headers=H)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.courses()[0]["documents"], [{"name": "2주차", "pages": 1}])
        self.assertFalse((folder / "교안" / "1주차.pdf").exists() or (folder / "pages" / "1주차").exists())
        again = self.client.delete(f"/api/local/courses/{quote('강의')}/documents/{quote('1주차')}", headers=H)
        self.assertEqual(again.status_code, 404)


class VideoUploadTests(WebTestCase):
    def put_video(self, content=b"video-bytes", course="강의", week=1, session=2, name="강의 1.mp4", **extra):
        params = {"course": course, "week": week, "session": session, **extra}
        return self.client.put("/api/local/transcriptions", params=params, content=content,
                               headers={**H, "X-Filename": quote(name)})

    def transcript(self, session=2):
        return self.root / "sources" / "강의" / "전사" / f"week_01_{session:02d}.md"

    def job(self, job_id):
        return next(job for job in self.client.get("/api/local/transcriptions").json()["jobs"] if job["id"] == job_id)

    def test_upload_transcribes_saves_and_removes_the_upload(self):
        self.make_course()
        response = self.put_video()
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual((body["course"], body["week"], body["session"], body["filename"]), ("강의", 1, 2, "강의 1.mp4"))
        self.assertTrue(wait_for(lambda: self.job(body["id"])["status"] == "done"))
        self.assertTrue(self.transcript().is_file())
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])

    def test_an_upload_larger_than_the_json_request_limit_is_accepted(self):
        self.make_course()
        self.assertEqual(self.put_video(content=b"x" * 20000).status_code, 202)  # POST bodies stop at 8 KiB

    def test_unknown_course_is_404_and_invalid_numbers_are_422(self):
        self.assertEqual(self.put_video().status_code, 404)
        self.make_course()
        self.assertEqual(self.put_video(week=0).status_code, 422)
        self.assertEqual(self.put_video(session=100).status_code, 422)

    def test_hostile_course_name_cannot_escape(self):
        self.make_course()
        self.assertEqual(self.put_video(course="../..").status_code, 404)
        self.assertEqual(self.put_video(course="   ").status_code, 400)

    def test_existing_lecture_is_refused_before_the_body_is_read(self):
        self.make_course()
        first = self.put_video().json()
        self.assertTrue(wait_for(lambda: self.job(first["id"])["status"] == "done"))
        with patch("server.lecture.web.save_upload", side_effect=AssertionError("the body was read")) as save:
            again = self.put_video(content=b"x" * 1000)
        self.assertEqual(again.status_code, 409)
        save.assert_not_called()
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])
        forced = self.put_video(force="true")
        self.assertEqual(forced.status_code, 202)

    def test_a_declared_size_over_the_limit_is_refused(self):
        self.make_course()
        with patch("server.lecture.web.MAX_UPLOAD_BYTES", 10):
            self.assertEqual(self.put_video(content=b"x" * 20).status_code, 413)
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])

    def test_a_streamed_upload_over_the_limit_is_aborted_and_deleted(self):
        self.make_course()
        with patch("server.lecture.web.MAX_UPLOAD_BYTES", 10):
            response = self.put_video(content=iter([b"x" * 8, b"x" * 8]))  # chunked: no Content-Length
        self.assertEqual(response.status_code, 413)
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])

    def test_low_disk_space_is_refused(self):
        self.make_course()
        with patch("server.lecture.web.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
            self.assertEqual(self.put_video().status_code, 507)

    def test_an_empty_upload_is_refused(self):
        self.make_course()
        self.assertEqual(self.put_video(content=b"").status_code, 400)
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])

    def test_cancel_a_running_job(self):
        self.make_course()
        self.engine_kwargs = {"gate": self.gate}
        job_id = self.put_video().json()["id"]
        self.assertTrue(wait_for(lambda: self.job(job_id)["status"] == "transcribing"))
        response = self.client.delete(f"/api/local/transcriptions/{job_id}", headers=H)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(wait_for(lambda: self.job(job_id)["status"] == "cancelled"))
        self.assertFalse(self.transcript().exists())
        self.assertEqual(list(self.transcriber.uploads_dir.glob("*")), [])

    def test_cancelling_an_unknown_job_is_404(self):
        self.assertEqual(self.client.delete("/api/local/transcriptions/nope", headers=H).status_code, 404)

    def test_job_list_is_newest_first(self):
        self.make_course()
        first = self.put_video(session=1).json()["id"]
        second = self.put_video(session=2).json()["id"]
        jobs = self.client.get("/api/local/transcriptions").json()["jobs"]
        self.assertEqual([job["id"] for job in jobs], [second, first])


class FromJobTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.make_course()
        self.school = Session(school=object(), expires=time.time() + 3600)
        self.store.sessions["tok"] = self.school
        self.auth = {**H, "Authorization": "Bearer tok"}
        self.job = self.add_job(self.school.owner)

    def add_job(self, owner, status="ready", expires=None):
        job = Job(owner=owner, lecture_id="1", name="강의.mp4")
        job.status, job.expires = status, expires if expires is not None else time.time() + 600
        (self.store.root / job.id).mkdir()
        (self.store.root / job.id / "video.mp4").write_bytes(b"video")
        self.store.jobs[job.id] = job
        return job

    def post(self, job=None, headers=None, **extra):
        body = {"jobId": (job or self.job).id, "course": "강의", "week": 1, "session": 3, **extra}
        return self.client.post("/api/local/transcriptions/from-job", json=body, headers=headers or self.auth)

    def transcript(self):
        return self.root / "sources" / "강의" / "전사" / "week_01_03.md"

    def test_transcribes_the_downloaded_video_and_keeps_the_file(self):
        response = self.post()
        self.assertEqual(response.status_code, 202)
        job_id = response.json()["id"]
        self.assertTrue(wait_for(lambda: next(j for j in self.transcriber.list() if j["id"] == job_id)["status"] == "done"))
        self.assertTrue(self.transcript().is_file())
        self.assertTrue((self.store.root / self.job.id / "video.mp4").is_file())
        self.assertTrue(wait_for(lambda: self.job.transfers == 0))

    def test_the_file_is_protected_while_transcribing_and_released_after_cancel(self):
        self.engine_kwargs = {"gate": self.gate}
        job_id = self.post().json()["id"]
        self.assertTrue(wait_for(lambda: self.engines and self.engines[0].started.is_set()))
        self.assertEqual(self.job.transfers, 1)
        self.client.delete(f"/api/local/transcriptions/{job_id}", headers=H)
        self.assertTrue(wait_for(lambda: self.job.transfers == 0))

    def test_an_expired_download_is_cleaned_up_after_the_transcription(self):
        self.engine_kwargs = {"gate": self.gate}
        self.post()
        self.assertTrue(wait_for(lambda: self.engines and self.engines[0].started.is_set()))
        self.job.expires = 0  # the 30-minute file lifetime ran out mid-transcription
        self.gate.set()
        self.assertTrue(wait_for(lambda: self.job.id not in self.store.jobs))
        self.assertFalse((self.store.root / self.job.id).exists())

    def test_needs_a_school_login(self):
        self.assertEqual(self.post(headers=H).status_code, 401)

    def test_someone_elses_job_is_404(self):
        other = self.add_job("another-owner")
        self.assertEqual(self.post(job=other).status_code, 404)
        self.assertEqual(other.transfers, 0)

    def test_a_video_that_is_not_ready_is_refused(self):
        waiting = self.add_job(self.school.owner, status="downloading")
        self.assertEqual(self.post(job=waiting).status_code, 409)
        self.assertEqual(waiting.transfers, 0)

    def test_an_existing_lecture_is_refused_and_releases_the_file(self):
        self.post()
        self.assertTrue(wait_for(lambda: self.transcript().is_file()))
        again = self.post()
        self.assertEqual(again.status_code, 409)
        self.assertTrue(wait_for(lambda: self.job.transfers == 0))


class StartupTests(unittest.TestCase):
    def test_a_second_instance_does_not_wipe_the_first_ones_uploads(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"DOWNLOAD_ROOT": str(Path(temp) / "svc")}):
            root = Path(temp) / "project"
            root.mkdir()

            def instance():
                return TestClient(create_app(None, Transcriber(root, lambda r: FakeEngine())), base_url=BASE)

            with instance():
                uploads = root / ".uploads"
                uploads.mkdir(exist_ok=True)
                (uploads / "in-flight.mp4").write_bytes(b"x")
                with self.assertRaises(OSError):  # the service lock refuses a second instance
                    with instance():
                        pass
                self.assertTrue((uploads / "in-flight.mp4").exists())
