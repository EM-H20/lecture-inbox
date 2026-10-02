"""Where lecture files live. Every path is derived from `root` (the project folder)."""
import os
import shutil
import tempfile
from pathlib import Path

from server.lecture.transcript import Transcript, to_markdown, to_plain_text
from server.school import safe_name

EXTENSIONS = (".md", ".txt")


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


def lecture_stem(week: int, session: int) -> str:
    for label, value in (("주차", week), ("차시", session)):
        if not 1 <= value <= 99:
            raise LayoutError(f"{label}는 1~99 사이 숫자여야 합니다.")
    return f"week_{week:02d}_{session:02d}"


def existing_transcripts(root: Path, course: str, week: int, session: int) -> list[Path]:
    folder, stem = output_dir(root, course), lecture_stem(week, session)
    return [folder / (stem + ext) for ext in EXTENSIONS if (folder / (stem + ext)).exists()]


def ensure_free(root: Path, course: str, week: int, session: int) -> None:
    existing = existing_transcripts(root, course, week, session)
    if existing:
        raise TranscriptExists(f"이미 있습니다: {', '.join(p.name for p in existing)}. 덮어쓰려면 --force를 붙여 주세요.")


def publish_transcript(root: Path, course: str, week: int, session: int, transcript: Transcript,
                       overwrite: bool = False) -> list[Path]:
    """Write .md and .txt into a staging folder, then rename them into place."""
    if not overwrite:
        ensure_free(root, course, week, session)
    folder, stem = output_dir(root, course), lecture_stem(week, session)
    folder.mkdir(parents=True, exist_ok=True)
    texts = {".md": to_markdown(transcript), ".txt": to_plain_text(transcript)}
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=folder))
    try:
        for ext, text in texts.items():
            (staging / (stem + ext)).write_text(text, encoding="utf-8")
        for ext in texts:
            os.replace(staging / (stem + ext), folder / (stem + ext))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return [folder / (stem + ext) for ext in texts]
