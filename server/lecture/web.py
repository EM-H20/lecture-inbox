"""Local web API: pick a course, upload a PDF or a video, watch and cancel transcription jobs.

These routes have no login (the app only listens on 127.0.0.1), so local_only() keeps other websites
from driving them: a foreign Host is refused, and every change needs a header that browsers only
send cross-origin after a CORS preflight that this server answers for the dev page alone.
"""
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote

import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from server.lecture.catalog import list_courses
from server.lecture.layout import LayoutError, sources_dir, transcript_dir
from server.lecture.pdf import MAX_BYTES as MAX_PDF_BYTES
from server.lecture.pdf import MAX_PAGES, PDF_NAME, PdfError, prepare_pages
from server.lecture.transcriber import Transcriber
from server.lecture.work_order import write_work_order

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
MARKER_HEADER = "x-requested-with"
MARKER_VALUE = "lecture-inbox"
MAX_UPLOAD_BYTES = 8 * 1024**3
MIN_FREE_BYTES = 1024**3


def local_only(request: Request) -> None:
    if request.headers.get("host", "").rsplit(":", 1)[0] not in LOCAL_HOSTS:
        raise HTTPException(403, "허용되지 않는 접속 주소입니다.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(MARKER_HEADER) != MARKER_VALUE:
        raise HTTPException(403, "허용되지 않는 요청입니다.")


def get_transcriber(request: Request) -> Transcriber:
    return request.app.state.transcriber


class CourseBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class FromJobBody(BaseModel):
    jobId: str = Field(pattern=r"^[0-9a-f]{32}$")
    course: str = Field(min_length=1, max_length=100)
    week: int = Field(ge=1, le=99)
    session: int = Field(ge=1, le=99)
    force: bool = False


def course_folder(transcriber: Transcriber, course: str):
    """The existing sources/<course> folder, or a 4xx. The name is cleaned the same way as when it was created."""
    try:
        folder = sources_dir(transcriber.root, course)
    except LayoutError as error:
        raise HTTPException(400, str(error)) from None
    if not folder.is_dir():
        raise HTTPException(404, "강의를 찾을 수 없습니다. 먼저 강의를 만들어 주세요.")
    return folder


def size_label(limit: int) -> str:
    return f"{limit / 1024**3:g}GB" if limit >= 1024**3 else f"{limit / 1024**2:g}MB"


async def save_upload(request: Request, directory: Path, suffix: str, limit: int) -> Path:
    """Stream the request body to a new file in `directory`; abort and delete if it exceeds `limit`."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"파일이 너무 큽니다(최대 {size_label(limit)}).")
    directory.mkdir(parents=True, exist_ok=True)
    expected = int(declared) if declared.isdigit() else limit
    if shutil.disk_usage(directory).free < expected + MIN_FREE_BYTES:
        raise HTTPException(507, "디스크 여유 공간이 부족합니다.")
    fd, name = tempfile.mkstemp(dir=directory, suffix=suffix)
    os.close(fd)
    path, size = Path(name), 0
    try:
        with path.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"파일이 너무 큽니다(최대 {size_label(limit)}).")
                out.write(chunk)  # ponytail: blocking write on the event loop, fine for a single local user
        if size == 0:
            raise HTTPException(400, "빈 파일입니다.")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/local", dependencies=[Depends(local_only)])

    @router.get("/status")
    def status(transcriber: Transcriber = Depends(get_transcriber)):
        try:
            transcriber.engine_factory(transcriber.root)
            whisper, message = True, ""
        except RuntimeError as error:
            whisper, message = False, str(error)
        return {"ffmpeg": bool(shutil.which("ffmpeg")), "whisper": whisper, "whisperMessage": message}

    @router.get("/course-name")
    def course_name(name: str = Query(min_length=1, max_length=100),
                    transcriber: Transcriber = Depends(get_transcriber)):
        """What a new course would really be called, without creating anything."""
        try:
            folder = sources_dir(transcriber.root, name)
        except LayoutError as error:
            raise HTTPException(400, str(error)) from None
        return {"name": folder.name, "exists": folder.is_dir()}

    @router.get("/courses")
    def courses(transcriber: Transcriber = Depends(get_transcriber)):
        return {"courses": list_courses(transcriber.root)}

    @router.post("/courses")
    def create_course(body: CourseBody, transcriber: Transcriber = Depends(get_transcriber)):
        try:
            folder = sources_dir(transcriber.root, body.name)
        except LayoutError as error:
            raise HTTPException(400, str(error)) from None
        created = not folder.exists()
        folder.mkdir(parents=True, exist_ok=True)
        return {"name": folder.name, "created": created}

    @router.get("/courses/{course}/transcripts/{stem}")
    def transcript(course: str = PathParam(min_length=1, max_length=100),
                   stem: str = PathParam(pattern=r"^week_[0-9]{2}_[0-9]{2}$"),
                   transcriber: Transcriber = Depends(get_transcriber)):
        course_folder(transcriber, course)
        path = transcript_dir(transcriber.root, course) / f"{stem}.md"
        if not path.is_file():
            raise HTTPException(404, "전사체를 찾을 수 없습니다.")
        return {"stem": stem, "text": path.read_text(encoding="utf-8")}

    @router.put("/courses/{course}/pdf")
    async def upload_pdf(request: Request, course: str = PathParam(min_length=1, max_length=100),
                         transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        temp = await save_upload(request, transcriber.uploads_dir, ".pdf", MAX_PDF_BYTES)
        try:
            with temp.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise HTTPException(400, "PDF 파일이 아닙니다.")
            try:
                document = pdfium.PdfDocument(str(temp))
                try:
                    pages = len(document)
                finally:
                    document.close()
            except pdfium.PdfiumError:
                raise HTTPException(422, "교안 PDF를 열 수 없습니다(손상되었거나 암호가 걸려 있을 수 있습니다).") from None
            if pages > MAX_PAGES:  # checked before replacing, so a refused PDF never overwrites the good one
                raise HTTPException(422, f"교안 PDF 페이지가 너무 많습니다({pages}쪽, 최대 {MAX_PAGES}쪽).")
            os.replace(temp, folder / PDF_NAME)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        try:
            result = await run_in_threadpool(prepare_pages, transcriber.root, folder.name)
        except PdfError as error:
            raise HTTPException(422, str(error)) from None
        await run_in_threadpool(write_work_order, transcriber.root, folder.name)
        return {"status": result.status, "pages": result.pages}

    @router.put("/transcriptions", status_code=202)
    async def upload_video(request: Request, course: str = Query(min_length=1, max_length=100),
                           week: int = Query(ge=1, le=99), session: int = Query(ge=1, le=99), force: bool = False,
                           x_filename: str = Header(default=""),
                           transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        try:
            transcriber.precheck(folder.name, week, session, force)  # refuse before receiving gigabytes
        except LayoutError as error:
            raise HTTPException(409, str(error)) from None
        name = unquote(x_filename)[:200] or "video"
        extension = Path(name).suffix
        temp = await save_upload(request, transcriber.uploads_dir,
                                 extension if re.fullmatch(r"\.[A-Za-z0-9]{1,5}", extension) else "", MAX_UPLOAD_BYTES)
        try:
            job = transcriber.submit(course=folder.name, week=week, session=session, source=temp,
                                     filename=name, force=force)
        except LayoutError as error:
            temp.unlink(missing_ok=True)
            raise HTTPException(409, str(error)) from None
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        return job.public()

    @router.post("/transcriptions/from-job", status_code=202)
    def transcribe_school_video(body: FromJobBody, request: Request,
                                authorization: str | None = Header(default=None),
                                transcriber: Transcriber = Depends(get_transcriber)):
        store = request.app.state.store
        _, school = store.authenticate(authorization)
        folder = course_folder(transcriber, body.course)
        with store.lock:
            job = store.owned(school, body.jobId)
            if job.status != "ready" or job.cancelled.is_set() or job.expires <= time.time():
                raise HTTPException(409, "영상이 아직 준비되지 않았거나 만료되었습니다.")
            job.transfers += 1  # keeps the file from being cleaned up while it is transcribed

        def release():
            with store.lock:
                job.transfers -= 1
                if job.cancelled.is_set() or job.expires <= time.time():
                    store.remove(job)

        try:
            queued = transcriber.submit(course=folder.name, week=body.week, session=body.session,
                                        source=store.root / job.id / "video.mp4", filename=job.name,
                                        force=body.force, cleanup=False, release=release)
        except LayoutError as error:
            release()
            raise HTTPException(409, str(error)) from None
        except BaseException:
            release()
            raise
        return queued.public()

    @router.get("/transcriptions")
    def transcriptions(transcriber: Transcriber = Depends(get_transcriber)):
        return {"jobs": transcriber.list()}

    @router.delete("/transcriptions/{job_id}")
    def cancel_transcription(job_id: str = PathParam(min_length=1, max_length=64),
                             transcriber: Transcriber = Depends(get_transcriber)):
        try:
            return transcriber.cancel(job_id).public()
        except KeyError:
            raise HTTPException(404, "작업을 찾을 수 없습니다.") from None

    return router
