"""Where lecture files live. Every path is derived from `root` (the project folder)."""
import os
import shutil
import tempfile
from pathlib import Path

from server.lecture.transcript import Transcript, to_markdown
from server.school import safe_name



class LayoutError(ValueError):
    pass


class TranscriptExists(LayoutError):
    pass


def safe_course(name: str) -> str:
    if not name.strip():
        raise LayoutError("강의 이름을 입력해 주세요.")
    return safe_name(name)  # replaces path separators, so the result is always a single folder name


def output_dir(root: Path, course: str) -> Path:
    return root / "output" / safe_course(course)


def sources_dir(root: Path, course: str) -> Path:
    return root / "sources" / safe_course(course)


def safe_document(name: str) -> str:
    """A 교안 document's name: the uploaded file name without its .pdf, cleaned to a single folder/file name."""
    stem = name.strip()
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    if not stem.strip():
        raise LayoutError("교안 이름을 입력해 주세요.")
    return safe_name(stem)


def documents_dir(root: Path, course: str) -> Path:
    return sources_dir(root, course) / "교안"


def pages_dir(root: Path, course: str, document: str) -> Path:
    return sources_dir(root, course) / "pages" / document


def transcript_dir(root: Path, course: str) -> Path:
    return sources_dir(root, course) / "전사"  # transcripts are agent input, so they live with the 교안


def lecture_stem(week: int, session: int) -> str:
    for label, value in (("주차", week), ("차시", session)):
        if not 1 <= value <= 99:
            raise LayoutError(f"{label}는 1~99 사이 숫자여야 합니다.")
    return f"week_{week:02d}_{session:02d}"


def existing_transcripts(root: Path, course: str, week: int, session: int) -> list[Path]:
    folder, stem = transcript_dir(root, course), lecture_stem(week, session)
    path = folder / f"{stem}.md"
    return [path] if path.exists() else []


def ensure_free(root: Path, course: str, week: int, session: int) -> None:
    existing = existing_transcripts(root, course, week, session)
    if existing:
        raise TranscriptExists(f"이미 있습니다: {', '.join(p.name for p in existing)}. 덮어쓰려면 --force를 붙여 주세요.")


def publish_transcript(root: Path, course: str, week: int, session: int, transcript: Transcript,
                       overwrite: bool = False) -> list[Path]:
    """Write the transcript into a staging folder, then rename it into place."""
    if not overwrite:
        ensure_free(root, course, week, session)
    folder, stem = transcript_dir(root, course), lecture_stem(week, session)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{stem}.md"
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=folder))
    try:
        (staging / name).write_text(to_markdown(transcript), encoding="utf-8")
        os.replace(staging / name, folder / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return [folder / name]
