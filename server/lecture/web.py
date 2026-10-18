"""Local web API: pick a course, upload a PDF or a video, watch and cancel transcription jobs.

These routes have no login (the app only listens on 127.0.0.1), so local_only() keeps other websites
from driving them: a foreign Host is refused, and every change needs a header that browsers only
send cross-origin after a CORS preflight that this server answers for the dev page alone.
"""
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote

import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.lecture.catalog import list_courses
from server.lecture.exam import MAX_MEMO, MAX_PER_TYPE, delete_exam, list_exams, read_exam
from server.lecture.layout import LayoutError, documents_dir, pages_dir, safe_document, sources_dir, transcript_dir
from server.lecture.pdf import MAX_BYTES as MAX_PDF_BYTES
from server.lecture.pdf import MAX_PAGES, PdfError, delete_document, prepare_document
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


class StudyBody(BaseModel):
    agent: Literal["claude", "agy", "codex"]
    stems: list[Annotated[str, Field(pattern=r"^week_[0-9]{2}_[0-9]{2}$")]] = Field(min_length=1, max_length=9801)
    replace: bool = False


class ExamCounts(BaseModel):
    mcq: int = Field(ge=0, le=MAX_PER_TYPE)
    ox: int = Field(ge=0, le=MAX_PER_TYPE)
    short: int = Field(ge=0, le=MAX_PER_TYPE)
    essay: int = Field(ge=0, le=MAX_PER_TYPE)


class ExamBody(BaseModel):
    agent: Literal["claude", "agy", "codex"]
    stems: list[Annotated[str, Field(pattern=r"^week_[0-9]{2}_[0-9]{2}$")]] = Field(min_length=1, max_length=9801)
    counts: ExamCounts
    emphasis: bool = True
    memo: str = Field(default="", max_length=MAX_MEMO)


class NoteBody(BaseModel):
    text: str = Field(min_length=1, max_length=1_000_000)
    originalText: str = Field(max_length=1_000_000)


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
    # ponytail: one local server process; use a shared file lock if multi-worker serving is introduced.
    note_lock = threading.Lock()

    def note_path(transcriber, course, stem):
        folder = course_folder(transcriber, course)
        path = transcriber.root.resolve() / "output" / folder.name / "notes" / f"{stem}.md"
        if folder.name != course or path.resolve() != path.absolute() or not path.is_file():
            raise HTTPException(404, "정리 노트를 찾을 수 없습니다.")
        return path

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

    @router.get("/study")
    def study_status(request: Request):
        return request.app.state.study.status()

    @router.post("/courses/{course}/study", status_code=202)
    def start_study(body: StudyBody, request: Request, course: str = PathParam(min_length=1, max_length=100),
                    transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        try:
            return request.app.state.study.submit(folder.name, body.agent, body.stems, body.replace)
        except LayoutError as error:
            raise HTTPException(409, str(error)) from None

    @router.delete("/study/{job_id}")
    def cancel_study(request: Request, job_id: str = PathParam(pattern=r"^[0-9a-f]{16}$")):
        try:
            return request.app.state.study.cancel(job_id)
        except KeyError:
            raise HTTPException(404, "정리 작업을 찾을 수 없습니다.") from None

    @router.get("/courses/{course}/exams")
    def exams(course: str = PathParam(min_length=1, max_length=100),
              transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        return {"exams": list_exams(transcriber.root, folder.name)}

    @router.get("/courses/{course}/exams/{exam_id}")
    def exam(course: str = PathParam(min_length=1, max_length=100),
             exam_id: str = PathParam(pattern=r"^[0-9]{8}-[0-9]{6}$"),
             transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        try:
            return {"id": exam_id, **read_exam(transcriber.root, folder.name, exam_id)}
        except FileNotFoundError:
            raise HTTPException(404, "시험지를 찾을 수 없습니다. 목록을 새로고침해 주세요.") from None
        except ValueError:
            raise HTTPException(422, "읽을 수 없는 시험지입니다. 파일이 손상되었거나 지원하지 않는 형식입니다.") from None

    @router.delete("/courses/{course}/exams/{exam_id}")
    def remove_exam(course: str = PathParam(min_length=1, max_length=100),
                    exam_id: str = PathParam(pattern=r"^[0-9]{8}-[0-9]{6}$"),
                    transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        if not delete_exam(transcriber.root, folder.name, exam_id):
            raise HTTPException(404, "시험지를 찾을 수 없습니다. 목록을 새로고침해 주세요.")
        return {"ok": True}

    @router.post("/courses/{course}/exams", status_code=202)
    def start_exam(body: ExamBody, request: Request, course: str = PathParam(min_length=1, max_length=100),
                   transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        try:
            return request.app.state.study.submit_exam(folder.name, body.agent, body.stems, body.counts.model_dump(),
                                                       body.emphasis, body.memo)
        except LayoutError as error:
            raise HTTPException(409, str(error)) from None

    @router.get("/courses/{course}/notes/{stem}")
    def note(course: str = PathParam(min_length=1, max_length=100),
             stem: str = PathParam(pattern=r"^week_[0-9]{2}_[0-9]{2}$"),
             transcriber: Transcriber = Depends(get_transcriber)):
        path = note_path(transcriber, course, stem)
        return {"stem": stem, "text": path.read_text(encoding="utf-8")}

    @router.put("/courses/{course}/notes/{stem}")
    def update_note(body: NoteBody, course: str = PathParam(min_length=1, max_length=100),
                    stem: str = PathParam(pattern=r"^week_[0-9]{2}_[0-9]{2}$"),
                    transcriber: Transcriber = Depends(get_transcriber)):
        if not body.text.strip():
            raise HTTPException(422, "노트 내용을 입력해 주세요.")
        with note_lock:
            path = note_path(transcriber, course, stem)
            current = path.read_text(encoding="utf-8")
            # A lost success response may be retried with the same original text.
            if current != body.text and current != body.originalText:
                raise HTTPException(409, "다른 곳에서 노트가 수정되었습니다. 작성한 내용을 저장해 둔 뒤 최신 노트를 다시 열어 주세요.")
            if current != body.text:
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".note-", dir=path.parent, delete=False) as out:
                        temporary = Path(out.name)
                        out.write(body.text)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(temporary, path)
                except OSError:
                    raise HTTPException(500, "노트를 저장하지 못했습니다. 작성한 내용은 화면에 남아 있으니 다시 시도해 주세요.") from None
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        return {"stem": stem, "text": body.text}

    @router.delete("/courses/{course}/notes/{stem}")
    def remove_note(request: Request, course: str = PathParam(min_length=1, max_length=100),
                    stem: str = PathParam(pattern=r"^week_[0-9]{2}_[0-9]{2}$"),
                    transcriber: Transcriber = Depends(get_transcriber)):
        with note_lock:
            note_path(transcriber, course, stem)  # 404 for a missing note or one that is a symlink
            try:
                if not request.app.state.study.archive_note(course, stem):
                    raise HTTPException(404, "정리 노트를 찾을 수 없습니다.")
            except LayoutError as error:
                raise HTTPException(409, str(error)) from None
        write_work_order(transcriber.root, course)
        return {"ok": True}

    @router.get("/courses/{course}/pages")
    def page_catalog(course: str = PathParam(min_length=1, max_length=100),
                     transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        base = transcriber.root.resolve() / "sources" / folder.name / "pages"
        documents = []
        if folder.name != course or not base.is_dir() or base.resolve() != base.absolute():
            return {"documents": documents}
        for directory in sorted(base.iterdir()):
            if not directory.is_dir() or directory.is_symlink() or directory.name.startswith("."):
                continue
            pages = [path.name for path in sorted(directory.glob("p*.png"))
                     if re.fullmatch(r"p[0-9]{3,}\.png", path.name) and path.is_file() and not path.is_symlink()]
            if pages:
                documents.append({"name": directory.name, "pages": pages})
        return {"documents": documents}

    @router.get("/courses/{course}/pages/{document}/{page}")
    def page_image(course: str = PathParam(min_length=1, max_length=100),
                   document: str = PathParam(min_length=1, max_length=200),
                   page: str = PathParam(pattern=r"^p[0-9]{3,}\.png$"),
                   transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        if folder.name != course or document in (".", "..") or re.search(r"[/\\\x00-\x1f]", document):
            raise HTTPException(400, "허용되지 않는 교안 경로입니다.")
        path = transcriber.root.resolve() / "sources" / folder.name / "pages" / document / page
        # Pages are generated files, never symlinks into another course or outside sources.
        if path.resolve() != path.absolute() or not path.is_file():
            raise HTTPException(404, "교안 페이지를 찾을 수 없습니다.")
        return FileResponse(path, media_type="image/png", headers={
            "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        })

    @router.put("/courses/{course}/documents/{name}")
    async def upload_document(request: Request, course: str = PathParam(min_length=1, max_length=100),
                              name: str = PathParam(min_length=1, max_length=200),
                              transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        try:
            document = safe_document(name)
        except LayoutError as error:
            raise HTTPException(400, str(error)) from None
        temp = await save_upload(request, transcriber.uploads_dir, ".pdf", MAX_PDF_BYTES)
        try:
            with temp.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise HTTPException(400, "PDF 파일이 아닙니다.")
            try:
                pdf = pdfium.PdfDocument(str(temp))
                try:
                    pages = len(pdf)
                finally:
                    pdf.close()
            except pdfium.PdfiumError:
                raise HTTPException(422, "교안 PDF를 열 수 없습니다(손상되었거나 암호가 걸려 있을 수 있습니다).") from None
            if pages > MAX_PAGES:  # checked before replacing, so a refused PDF never overwrites the good one
                raise HTTPException(422, f"교안 PDF 페이지가 너무 많습니다({pages}쪽, 최대 {MAX_PAGES}쪽).")
            target = documents_dir(transcriber.root, folder.name)
            target.mkdir(parents=True, exist_ok=True)
            os.replace(temp, target / f"{document}.pdf")
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        try:
            result = await run_in_threadpool(prepare_document, transcriber.root, folder.name, document)
        except PdfError as error:
            shutil.rmtree(pages_dir(transcriber.root, folder.name, document), ignore_errors=True)  # stale pages of the old file
            raise HTTPException(422, str(error)) from None
        await run_in_threadpool(write_work_order, transcriber.root, folder.name)
        return {"document": document, "status": result.status, "pages": result.pages}

    @router.delete("/courses/{course}/documents/{name}")
    def remove_document(course: str = PathParam(min_length=1, max_length=100),
                        name: str = PathParam(min_length=1, max_length=200),
                        transcriber: Transcriber = Depends(get_transcriber)):
        folder = course_folder(transcriber, course)
        try:
            document = safe_document(name)
        except LayoutError as error:
            raise HTTPException(400, str(error)) from None
        if not delete_document(transcriber.root, folder.name, document):
            raise HTTPException(404, "교안을 찾을 수 없습니다.")
        write_work_order(transcriber.root, folder.name)
        return {"ok": True}

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
