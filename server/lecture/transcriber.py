"""Queue that transcribes one video at a time. Jobs live in memory only; saved files outlive a restart."""
import logging
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from server.lecture.audio import normalize_to_wav
from server.lecture.layout import LayoutError, TranscriptExists, ensure_free, existing_transcripts, safe_course
from server.lecture.pipeline import transcribe_lecture

log = logging.getLogger("uvicorn.error")

ACTIVE = ("waiting", "converting", "transcribing", "saving")
MAX_FINISHED_KEPT = 30
EXPECTED_ERRORS = (LayoutError, RuntimeError, FileNotFoundError)
CANCELLED_MESSAGE = "전사가 취소되었습니다."


@dataclass
class TranscriptionJob:
    course: str
    week: int
    session: int
    filename: str
    source: Path
    force: bool = False
    cleanup: bool = True  # uploads are deleted when the job ends; borrowed files (school videos) are not
    release: Callable[[], None] | None = None
    id: str = field(default_factory=lambda: secrets.token_hex(8))
    status: str = "waiting"
    error: str = ""
    started: float = 0.0
    finished: float = 0.0
    cancelled: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        end = self.finished or time.time()
        return {"id": self.id, "course": self.course, "week": self.week, "session": self.session,
                "filename": self.filename, "status": self.status, "error": self.error,
                "elapsedSeconds": int(end - self.started) if self.started else 0}


class Transcriber:
    def __init__(self, root, engine_factory, normalize=normalize_to_wav):
        self.root, self.engine_factory, self.normalize = Path(root), engine_factory, normalize
        self.uploads_dir = self.root / ".uploads"
        self.lock = threading.RLock()
        self.jobs: dict[str, TranscriptionJob] = {}
        self.engines: dict[str, object] = {}
        self.executor = ThreadPoolExecutor(max_workers=1)  # one transcription at a time
        self.closed = threading.Event()

    def discard_stale_uploads(self) -> None:
        shutil.rmtree(self.uploads_dir, ignore_errors=True)

    def precheck(self, course: str, week: int, session: int, force: bool = False) -> None:
        """Raise before any bytes are received if this lecture cannot be queued."""
        safe = safe_course(course)
        (existing_transcripts if force else ensure_free)(self.root, safe, week, session)
        with self.lock:
            if any(job.course == safe and job.week == week and job.session == session and job.status in ACTIVE
                   for job in self.jobs.values()):
                raise TranscriptExists("같은 회차를 이미 전사하고 있거나 대기 중입니다.")

    def submit(self, *, course: str, week: int, session: int, source: Path, filename: str, force: bool = False,
               cleanup: bool = True, release: Callable[[], None] | None = None) -> TranscriptionJob:
        if self.closed.is_set():
            raise RuntimeError("서버를 종료하는 중입니다.")
        self.precheck(course, week, session, force)
        job = TranscriptionJob(safe_course(course), week, session, filename, Path(source), force, cleanup, release)
        with self.lock:
            self.jobs[job.id] = job
            finished = [j for j in self.jobs.values() if j.status not in ACTIVE]
            for old in finished[:-MAX_FINISHED_KEPT]:
                del self.jobs[old.id]
        self.executor.submit(self._run, job)
        return job

    def list(self) -> list[dict]:
        with self.lock:
            return [job.public() for job in reversed(list(self.jobs.values()))]

    def cancel(self, job_id: str) -> TranscriptionJob:
        with self.lock:
            job = self.jobs[job_id]  # KeyError for an unknown id
            if job.status not in ACTIVE:
                return job
            job.cancelled.set()
            engine = self.engines.get(job_id)
            queued = job.status == "waiting"
            if queued:
                job.status = "cancelled"  # claimed under the lock so _run skips it
        if engine:
            engine.stop()
        if queued:
            self._finish(job, "cancelled")
        return job

    def close(self) -> None:
        """Stop everything: running Whisper is terminated, queued jobs are dropped, uploads are deleted."""
        self.closed.set()
        with self.lock:
            active = [job for job in self.jobs.values() if job.status in ACTIVE]
            queued = [job for job in active if job.status == "waiting"]
            for job in active:
                job.cancelled.set()
            for job in queued:
                job.status = "cancelled"
            engines = list(self.engines.values())
        for engine in engines:
            engine.stop()
        for job in queued:
            self._finish(job, "cancelled")
        self.executor.shutdown(wait=True, cancel_futures=True)

    def _stage(self, job: TranscriptionJob, stage: str) -> None:
        with self.lock:
            if job.cancelled.is_set() or self.closed.is_set():
                raise RuntimeError(CANCELLED_MESSAGE)
            job.status = stage

    def _run(self, job: TranscriptionJob) -> None:
        with self.lock:
            if job.status != "waiting":  # cancelled while queued
                return
            job.status, job.started = "converting", time.time()
        try:
            engine = self.engine_factory(self.root)
            with self.lock:
                self.engines[job.id] = engine
                if job.cancelled.is_set() or self.closed.is_set():
                    engine.stop()  # the cancel arrived before the engine existed
            transcribe_lecture(self.root, job.course, job.week, job.session, job.source, engine,
                               force=job.force, normalize=self.normalize,
                               on_stage=lambda stage: self._stage(job, stage))
        except Exception as error:
            if job.cancelled.is_set() or self.closed.is_set():
                self._finish(job, "cancelled")
            elif isinstance(error, EXPECTED_ERRORS):
                self._finish(job, "failed", str(error))
            else:
                log.exception("transcription job %s crashed", job.id)
                self._finish(job, "failed", "전사 중 오류가 발생했습니다. 터미널의 서버 로그를 확인해 주세요.")
        else:
            self._finish(job, "done")

    def _finish(self, job: TranscriptionJob, status: str, error: str = "") -> None:
        with self.lock:
            job.status, job.error, job.finished = status, error, time.time()
            self.engines.pop(job.id, None)
            release, job.release = job.release, None
        if job.cleanup:
            job.source.unlink(missing_ok=True)
        if release:
            release()
