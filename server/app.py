"""Local API: per-user school sessions, bounded temporary downloads, browser delivery, and the /api/local lecture routes."""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import ipaddress
import logging
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Path as PathParam, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, SecretStr

from .school import SchoolExpired, SchoolSession, UserError, lecture_id, safe_name
from server.lecture.cli import PROJECT_ROOT
from server.lecture.transcriber import Transcriber
from server.lecture.study import StudyRunner
from server.lecture.web import create_router
from server.lecture.whisper import WhisperCli

# uvicorn configures this logger (INFO, stderr), so messages show in the dev terminal.
log = logging.getLogger("uvicorn.error")


@dataclass
class Session:
    school: SchoolSession
    expires: float
    owner: str = field(default_factory=lambda: secrets.token_hex(16))


@dataclass
class Job:
    owner: str
    lecture_id: str
    name: str
    id: str = field(default_factory=lambda: secrets.token_hex(16))
    status: str = "waiting"
    error: str = ""
    size: int = 0
    expires: float = 0
    cancelled: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen | None = None
    transfers: int = 0

    def public(self):
        return {"id": self.id, "name": self.name, "status": self.status, "error": self.error,
                "size": self.size, "expiresAt": self.expires or None}


def validate_cdn(url):
    """Only public HTTPS addresses extracted from the authenticated school page."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise UserError("영상 주소 형식이 올바르지 않습니다.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(addr[4][0]).is_global for addr in addresses):
            raise UserError("내부 네트워크 영상 주소는 처리하지 않습니다.")
    except OSError:
        raise UserError("영상 서버 주소에 연결할 수 없습니다.") from None


class Store:
    def __init__(self, root: Path, workers=2, max_jobs=12, max_bytes=2 * 1024**3):
        self.root = root
        self.lock = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self.jobs: dict[str, Job] = {}
        self.tickets: dict[str, tuple[str, str, float]] = {}
        self.login_attempts: dict[str, list[float]] = {}
        self.pepper = secrets.token_bytes(32)
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self.max_jobs, self.max_bytes = max_jobs, max_bytes
        self.file_ttl = int(os.getenv("FILE_TTL_SECONDS", "1800"))
        self.session_ttl = int(os.getenv("SESSION_TTL_SECONDS", "7200"))
        self.stop = threading.Event()

    def login_limit(self, ip, student_id):
        now = time.time()
        keys = ("ip:" + ip, hashlib.sha256(self.pepper + student_id.encode()).hexdigest())
        with self.lock:
            self.login_attempts = {k: [n for n in v if now - n < 900] for k, v in self.login_attempts.items() if v and now - v[-1] < 900}
            if len(self.login_attempts) > 2000 or any(len(self.login_attempts.get(k, [])) >= limit for k, limit in zip(keys, (20, 5))):
                raise HTTPException(429, "로그인 시도가 많습니다. 15분 뒤 다시 시도해 주세요.")
            if len(self.sessions) >= 100:
                raise HTTPException(503, "접속 인원이 많습니다. 잠시 후 다시 시도해 주세요.")
            for key in keys:
                self.login_attempts.setdefault(key, []).append(now)

    def authenticate(self, authorization):
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        with self.lock:
            session = self.sessions.get(token)
            if not session or session.expires <= time.time():
                raise HTTPException(401, "로그인이 만료되었습니다. 다시 로그인해 주세요.")
            return token, session

    def owned(self, session, job_id):
        job = self.jobs.get(job_id)
        if not job or job.owner != session.owner:
            raise HTTPException(404, "파일을 찾을 수 없습니다.")
        return job

    def remove(self, job):
        job.cancelled.set()
        if job.process and job.process.poll() is None:
            job.process.terminate()
        if job.status in {"waiting", "downloading"} or job.transfers:
            return
        shutil.rmtree(self.root / job.id, ignore_errors=True)
        self.jobs.pop(job.id, None)
        self.tickets = {key: value for key, value in self.tickets.items() if value[0] != job.id}

    def logout(self, token):
        with self.lock:
            session = self.sessions.pop(token, None)
            if session:
                for job in list(self.jobs.values()):
                    if job.owner == session.owner:
                        self.remove(job)

    def collect(self):
        with self.lock:
            now = time.time()
            for token, session in list(self.sessions.items()):
                if session.expires <= now:
                    self.logout(token)
            for job in list(self.jobs.values()):
                if job.expires and job.expires <= now:
                    self.remove(job)
            self.tickets = {k: v for k, v in self.tickets.items() if v[2] > now}

    def start(self, session, identifier, name):
        with self.lock:
            self.collect()
            if session.expires <= time.time() or session not in self.sessions.values():
                raise HTTPException(401, "로그인이 만료되었습니다.")
            if len(self.jobs) >= self.max_jobs:
                raise HTTPException(429, "서버 보관함이 가득 찼습니다. 잠시 후 다시 시도해 주세요.")
            owned = [j for j in self.jobs.values() if j.owner == session.owner]
            if any(j.status in {"waiting", "downloading"} for j in owned):
                raise HTTPException(409, "현재 영상 준비가 끝난 뒤 다음 강의를 추가해 주세요.")
            if len(owned) >= 3:
                raise HTTPException(429, "한 번에 3개까지 보관합니다. 받은 파일을 목록에서 정리해 주세요.")
            if shutil.disk_usage(self.root).free < self.max_bytes + 256 * 1024**2:
                raise HTTPException(503, "서버 임시 저장 공간이 부족합니다.")
            job = Job(session.owner, identifier, safe_name(name or "강의-" + identifier) + ".mp4")
            self.jobs[job.id] = job
            self.executor.submit(self.download, job, session.school)
            log.info("job %s queued (lecture %s)", job.id[:8], identifier)
            return job.public()

    def run_ffmpeg(self, job, stream, path, referer=False):
        args = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-rw_timeout", "30000000",
                "-tls_verify", "1", "-protocol_whitelist", "https,tls,tcp,crypto"]
        if referer:
            args += ["-headers", "Referer: https://ecampus.sejong.ac.kr/\r\n"]
        args += ["-i", stream, "-c", "copy", "-fs", str(self.max_bytes), "-f", "mp4", str(path)]
        # Temporary stderr may contain signed URLs: never forward it to clients or logs.
        with tempfile.TemporaryFile() as errors:
            with self.lock:
                if job.cancelled.is_set() or self.stop.is_set():
                    raise UserError("작업이 취소되었습니다.")
                job.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors)
                process = job.process
            try:
                process.wait(timeout=7200)
                errors.seek(0)
                stderr = errors.read(16384).decode(errors="replace")
                if process.returncode:
                    return "403" if "403" in stderr else "failed"
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise UserError("영상 준비가 2시간을 초과했습니다. 다시 시도해 주세요.") from None
            finally:
                job.process = None
        return "ok"

    def download(self, job, school):
        folder = self.root / job.id
        try:
            with self.lock:
                if job.cancelled.is_set():
                    raise UserError("작업이 취소되었습니다.")
                job.status = "downloading"
            folder.mkdir(mode=0o700)
            stream, _ = school.stream(job.lecture_id)
            validate_cdn(stream)
            partial = folder / "video.part"
            result = self.run_ffmpeg(job, stream, partial)
            if result == "403":
                log.info("job %s: ffmpeg got 403, retrying with referer", job.id[:8])
                result = self.run_ffmpeg(job, stream, partial, referer=True)
            if result != "ok":
                raise UserError("영상 다운로드에 실패했습니다. 학교에서 재생 가능한 강의인지 확인해 주세요.")
            if not partial.exists() or not 0 < partial.stat().st_size < self.max_bytes:
                raise UserError("영상이 비어 있거나 파일 크기 제한을 초과했습니다.")
            partial.rename(folder / "video.mp4")
            with self.lock:
                job.size = (folder / "video.mp4").stat().st_size
                job.status = "ready"
                job.expires = time.time() + self.file_ttl
            log.info("job %s ready (%.1f MB)", job.id[:8], job.size / 1024**2)
        except Exception as error:
            if isinstance(error, UserError):
                log.warning("job %s failed: %s", job.id[:8], error)
            else:
                log.exception("job %s crashed", job.id[:8])
            with self.lock:
                job.status = "failed"
                job.error = str(error) if isinstance(error, UserError) else "영상 준비 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
                job.expires = time.time() + self.file_ttl
            shutil.rmtree(folder, ignore_errors=True)
        finally:
            with self.lock:
                if job.cancelled.is_set() or self.stop.is_set():
                    self.remove(job)

    def ticket(self, session, job_id):
        with self.lock:
            job = self.owned(session, job_id)
            if job.status != "ready" or job.cancelled.is_set() or job.expires <= time.time():
                raise HTTPException(409, "파일이 아직 준비되지 않았거나 만료되었습니다.")
            # One short-lived ticket per job keeps repeated clicks bounded.
            self.tickets = {k: v for k, v in self.tickets.items() if v[0] != job.id}
            ticket = secrets.token_urlsafe(32)
            self.tickets[ticket] = (job.id, session.owner, time.time() + 60)
            return ticket

    def claim(self, ticket):
        with self.lock:
            entry = self.tickets.pop(ticket, None)
            if not entry or entry[2] <= time.time():
                raise HTTPException(410, "다운로드 링크가 만료됐습니다. 다운로드 버튼을 다시 눌러 주세요.")
            job = self.jobs.get(entry[0])
            logged_in = any(s.owner == entry[1] and s.expires > time.time() for s in self.sessions.values())
            if not job or not logged_in or job.cancelled.is_set() or job.status != "ready" or job.expires <= time.time():
                raise HTTPException(410, "파일 또는 로그인이 만료됐습니다.")
            job.transfers += 1
            log.info("job %s download started", job.id[:8])
            return job

    def close(self):
        self.stop.set()
        with self.lock:
            for token in list(self.sessions):
                self.logout(token)
        self.executor.shutdown(wait=True, cancel_futures=True)


class DownloadResponse(FileResponse):
    """Keep a temporary file alive until browser transfer (including disconnect) ends."""
    def __init__(self, store, job):
        self.store, self.job = store, job
        super().__init__(store.root / job.id / "video.mp4", filename=job.name, media_type="video/mp4")

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with self.store.lock:
                self.job.transfers -= 1
                if self.job.cancelled.is_set() or self.job.expires <= time.time():
                    self.store.remove(self.job)


class LoginBody(BaseModel):
    studentId: str = Field(pattern=r"^[0-9]{4,20}$")
    password: SecretStr = Field(min_length=1, max_length=512)


class JobBody(BaseModel):
    url: str = Field(max_length=2048)
    name: str = Field(default="", max_length=150)


def create_app(store=None, transcriber=None):
    transcriber = transcriber or Transcriber(Path(os.getenv("LECTURE_ROOT") or PROJECT_ROOT), WhisperCli.from_env)
    study = StudyRunner(transcriber.root)

    @asynccontextmanager
    async def lifespan(app):
        owned_temp = None
        lock_file = None
        if store is None:
            parent = Path(os.getenv("DOWNLOAD_ROOT", str(Path(tempfile.gettempdir()) / "lecture-inbox-service")))
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock_file = (parent / "service.lock").open("a")
            # ponytail: one API process; shared session/job storage is needed before scaling replicas.
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            transcriber.discard_stale_uploads()  # only the instance that holds the lock may wipe leftovers
            for stale in parent.glob("run-*"):
                if stale.is_dir():
                    shutil.rmtree(stale)
            owned_temp = tempfile.TemporaryDirectory(prefix="run-", dir=parent)
            app.state.store = Store(Path(owned_temp.name))
        else:
            app.state.store = store
        async def cleanup():
            while True:
                await asyncio.sleep(30)
                app.state.store.collect()
        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            await asyncio.to_thread(study.close)
            await asyncio.to_thread(transcriber.close)  # stop Whisper first so shutdown is quick
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.to_thread(app.state.store.close)
            if owned_temp:
                owned_temp.cleanup()
            if lock_file:
                lock_file.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.transcriber = transcriber
    app.state.study = study
    app.include_router(create_router())
    origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:4317,http://127.0.0.1:4317").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins],
                       allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Filename"])

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.method == "POST":
            if "transfer-encoding" in request.headers or (request.url.path in {"/api/login", "/api/jobs"} and "content-length" not in request.headers):
                return JSONResponse({"detail": "요청 크기를 명시해 주세요."}, status_code=411)
            try:
                if not 0 <= int(request.headers.get("content-length", "0")) <= 8192:
                    return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "잘못된 요청입니다."}, status_code=400)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff"})
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        # Pydantic's default errors can echo submitted credentials.
        return JSONResponse({"detail": "입력 형식을 확인해 주세요."}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"ok": True, "ffmpeg": bool(shutil.which("ffmpeg"))}

    @app.post("/api/login")
    def login(body: LoginBody, request: Request):
        state = request.app.state.store
        state.login_limit(request.client.host if request.client else "unknown", body.studentId)
        school = SchoolSession()
        try:
            school.login(body.studentId, body.password.get_secret_value())
        except UserError as error:
            log.warning("login failed: %s", error)
            raise HTTPException(401, str(error)) from None
        token = secrets.token_urlsafe(32)
        with state.lock:
            state.sessions[token] = Session(school, time.time() + state.session_ttl)
        log.info("login ok (active sessions: %d)", len(state.sessions))
        return {"token": token, "expiresAt": state.sessions[token].expires}

    @app.post("/api/logout")
    def logout(request: Request, authorization: str | None = Header(default=None)):
        state = request.app.state.store
        token, _ = state.authenticate(authorization)
        state.logout(token)
        return {"ok": True}

    def school_list(request, authorization, method, *args):
        state = request.app.state.store
        _, session = state.authenticate(authorization)
        try:
            result = getattr(session.school, method)(*args)
        except SchoolExpired as error:
            # Keep prepared files available; let the user explicitly log out/reconnect.
            raise HTTPException(409, str(error)) from None
        except UserError as error:
            raise HTTPException(502, str(error)) from None
        # A school response must not restore access after logout or local expiry.
        state.authenticate(authorization)
        return result

    @app.get("/api/courses")
    def courses(request: Request, authorization: str | None = Header(default=None),
                year: str = Query(default="all", pattern=r"^(all|[0-9]{4})$"),
                semester: str = Query(default="all", pattern=r"^(all|10|11|20|21)$")):
        return {"courses": school_list(request, authorization, "courses", year, semester)}

    @app.get("/api/courses/{course_id}/lectures")
    def lectures(request: Request, course_id: str = PathParam(pattern=r"^[0-9]{1,12}$"),
                 authorization: str | None = Header(default=None)):
        return {"lectures": school_list(request, authorization, "lectures", course_id)}

    @app.get("/api/jobs")
    def jobs(request: Request, authorization: str | None = Header(default=None)):
        state = request.app.state.store
        _, session = state.authenticate(authorization)
        with state.lock:
            return {"jobs": [j.public() for j in reversed(list(state.jobs.values())) if j.owner == session.owner and not j.cancelled.is_set()]}

    @app.post("/api/jobs", status_code=202)
    def start(body: JobBody, request: Request, authorization: str | None = Header(default=None)):
        state = request.app.state.store
        _, session = state.authenticate(authorization)
        try:
            identifier = lecture_id(body.url)
        except UserError as error:
            raise HTTPException(400, str(error)) from None
        return state.start(session, identifier, body.name)

    @app.delete("/api/jobs/{job_id}")
    def delete(job_id: str, request: Request, authorization: str | None = Header(default=None)):
        state = request.app.state.store
        _, session = state.authenticate(authorization)
        with state.lock:
            state.remove(state.owned(session, job_id))
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/ticket")
    def ticket(job_id: str, request: Request, authorization: str | None = Header(default=None)):
        state = request.app.state.store
        _, session = state.authenticate(authorization)
        return {"path": "/api/download/" + state.ticket(session, job_id)}

    @app.get("/api/download/{ticket}")
    def download(ticket: str, request: Request):
        state = request.app.state.store
        return DownloadResponse(state, state.claim(ticket))

    return app


app = create_app()
