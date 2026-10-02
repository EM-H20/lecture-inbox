"""정리-작업.md: the per-course job list an agent reads. Rebuilt from the files on disk every time."""
from pathlib import Path

from server.lecture.layout import output_dir, sources_dir, transcript_dir
from server.lecture.pdf import PDF_NAME

GUIDE_NAME = "정리-지침.md"


def build_work_order(root: Path, course: str) -> str:
    out, src = output_dir(root, course), sources_dir(root, course)
    name = out.name

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    prepare = f'npm run lecture -- prepare --course "{name}"'
    lines = [f"# 정리 작업: {name}", "", f"먼저 프로젝트 루트의 `{GUIDE_NAME}`를 읽고 그 지침대로 정리하세요.", "", "## 교안", ""]
    pages = sorted((src / "pages").glob("p*.txt"))
    if pages:
        lines.append(f"- 페이지 {len(pages)}장이 준비되어 있습니다. 이미지: `{rel(src)}/pages/pNNN.png`, 텍스트: `{rel(src)}/pages/pNNN.txt`")
        if all(not page.read_text(encoding="utf-8").strip() for page in pages):
            lines.append("- ⚠ 모든 페이지의 추출 텍스트가 비어 있습니다(스캔본일 수 있음). 페이지 이미지를 직접 읽고 매핑하세요.")
    elif (src / PDF_NAME).is_file():
        lines.append(f"- 교안은 있지만 페이지가 아직 준비되지 않았습니다. `{prepare}`를 실행하세요.")
    else:
        lines.append(f"- 교안 없음: `{rel(src)}/{PDF_NAME}`를 넣고 `{prepare}`를 실행하면 페이지가 준비됩니다. 교안이 없으면 전사체만으로 정리하세요.")

    lines += ["", "## 회차", ""]
    lectures = sorted(transcript_dir(root, course).glob("week_[0-9][0-9]_[0-9][0-9].md"))
    if not lectures:
        lines.append("아직 전사체가 없습니다.")
    else:
        lines += ["| 회차 | 전사체 | 노트(작성할 위치) | 상태 |", "|---|---|---|---|"]
        waiting = 0
        for lecture in lectures:
            note = out / "notes" / lecture.name
            done = note.is_file()
            waiting += not done
            lines.append(f"| {lecture.stem} | `{rel(lecture)}` | `{rel(note)}` | {'정리 완료' if done else '정리 대기'} |")
        lines += ["", f"정리 대기: {waiting}개"]
    return "\n".join(lines) + "\n"


def write_work_order(root: Path, course: str) -> Path:
    path = output_dir(root, course) / "정리-작업.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_work_order(root, course), encoding="utf-8")
    return path
