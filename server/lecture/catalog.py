"""Read-only view of sources/ and output/ for the course picker."""
import re
from pathlib import Path

from server.lecture.pdf import PDF_NAME
from server.school import safe_name

STEM = re.compile(r"^week_([0-9]{2})_([0-9]{2})$")


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
            lectures.append({"stem": path.stem, "week": week, "session": session,
                             "hasNote": (root / "output" / folder.name / "notes" / path.name).is_file()})
        courses.append({"name": folder.name, "hasPdf": (folder / PDF_NAME).is_file(),
                        "pages": len(list((folder / "pages").glob("p*.png"))), "lectures": lectures})
    return courses
