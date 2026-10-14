"""Read-only view of sources/ and output/ for the course picker."""
import re
from pathlib import Path

from server.lecture.layout import pages_dir
from server.lecture.pdf import list_documents
from server.school import safe_name

STEM = re.compile(r"^week_([0-9]{2})_([0-9]{2})$")
META = re.compile(r"^\d{2}주차 \d{2}번째 강의 · (.+) · 전사 약 ")


def note_handouts(text: str) -> list[str]:
    """Handout names cited on a note's metadata line; a hint for picking lectures, not a page link."""
    line = next((item for item in text.splitlines()[1:] if item.strip()), "")
    match = META.match(line)
    names = []
    for part in match[1].split(" · ") if match else []:
        hit = re.match(r"교안 (.+?)(?: p\.\S.*)?$", part)
        if hit and hit[1] != "연결 확인 필요" and hit[1] not in names:
            names.append(hit[1])
    return names


def list_courses(root: Path) -> list[dict]:
    base = root / "sources"
    if not base.is_dir():
        return []
    courses = []
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.name.startswith(".") or safe_name(folder.name) != folder.name:
            continue
        lectures = []
        for path in sorted((folder / "전사").glob("week_[0-9][0-9]_[0-9][0-9].md")):
            week, session = (int(part) for part in STEM.match(path.stem).groups())
            note = root / "output" / folder.name / "notes" / path.name
            has_note = note.is_file()
            # errors="replace": a hand-edited note must never break the course list.
            handouts = note_handouts(note.read_text(encoding="utf-8", errors="replace")) if has_note else []
            lectures.append({"stem": path.stem, "week": week, "session": session,
                             "hasNote": has_note, "handouts": handouts})
        documents = [{"name": name, "pages": len(list(pages_dir(root, folder.name, name).glob("p*.png")))}
                     for name in list_documents(root, folder.name)]
        courses.append({"name": folder.name, "documents": documents, "lectures": lectures})
    return courses
