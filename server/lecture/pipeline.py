"""One lecture end to end: transcribe, publish, prepare the 교안 pages, refresh 정리-작업.md."""
import logging
from pathlib import Path

from server.lecture.audio import normalize_to_wav
from server.lecture.layout import ensure_free, publish_transcript
from server.lecture.pdf import PdfError, prepare_pages
from server.lecture.work_order import write_work_order

log = logging.getLogger(__name__)


def prepare_course(root: Path, course: str) -> list[str]:
    """Render the 교안 pages (if a PDF exists) and rewrite 정리-작업.md. Returns status lines for the user."""
    try:
        result = prepare_pages(root, course)
        note = {"missing": "교안 없음", "unchanged": f"교안 페이지 그대로 ({result.pages}장)",
                "prepared": f"교안 페이지 {result.pages}장 생성"}[result.status]
    except PdfError as error:
        log.warning("교안 준비 실패: %s", error)
        note = f"교안 준비 실패: {error}"
    return [note, f"작업 목록: {write_work_order(root, course).relative_to(root).as_posix()}"]


def transcribe_lecture(root: Path, course: str, week: int, session: int, source: Path, engine, *,
                       force: bool = False, normalize=normalize_to_wav) -> tuple[list[Path], list[str]]:
    if not source.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {source}")
    if not force:
        ensure_free(root, course, week, session)  # refuse before spending hours on a transcript we would not save
    wav = normalize(source)
    try:
        transcript = engine.transcribe(wav, source.name)
    finally:
        wav.unlink(missing_ok=True)
    if not transcript.segments:
        raise RuntimeError("음성이 감지되지 않았습니다. 파일에 말소리가 있는지 확인해 주세요.")
    paths = publish_transcript(root, course, week, session, transcript, overwrite=force)
    return paths, prepare_course(root, course)
