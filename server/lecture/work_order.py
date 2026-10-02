"""정리-작업.md: the per-course job list an agent reads. Rebuilt from the files on disk every time."""
from pathlib import Path

from server.lecture.layout import documents_dir, output_dir, pages_dir, sources_dir, transcript_dir
from server.lecture.pdf import list_documents

GUIDE_NAME = "정리-지침.md"


def build_work_order(root: Path, course: str) -> str:
    out, src = output_dir(root, course), sources_dir(root, course)
    name = out.name

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    prepare = f'npm run lecture -- prepare --course "{name}"'
    lines = [f"# 정리 작업: {name}", "", f"먼저 프로젝트 루트의 `{GUIDE_NAME}`를 읽고 그 지침대로 정리하세요.", "", "## 교안", ""]
    documents = list_documents(root, course)
    if not documents:
        lines.append(f"- 교안 없음: `{rel(documents_dir(root, course))}/`에 PDF를 넣고 `{prepare}`를 실행하면 페이지가 준비됩니다. 교안이 없으면 전사체만으로 정리하세요.")
    else:
        lines.append(f"- 교안 {len(documents)}개. 파일 이름(예: 주차)과 전사 내용을 보고 어느 교안이 어느 회차인지 판단하세요.")
        lines.append("- 교안 내용은 해당 쪽 이미지를 직접 열어 확인하세요(표·수식·그림 속 글자는 텍스트로 제대로 안 나옵니다). 텍스트는 찾기 위한 참고용입니다.")
        for document in documents:
            folder = pages_dir(root, course, document)
            pages = sorted(folder.glob("p*.txt"))
            if not pages:
                lines.append(f"  - `{document}` — 페이지가 아직 준비되지 않았습니다. `{prepare}`를 실행하세요.")
                continue
            lines.append(f"  - `{document}` — {len(pages)}쪽 · 이미지 `{rel(folder)}/pNNN.png`, 텍스트 `{rel(folder)}/pNNN.txt`")
            if all(not page.read_text(encoding="utf-8").strip() for page in pages):
                lines.append(f"  - ⚠ `{document}`의 모든 페이지 추출 텍스트가 비어 있습니다(이미지로 된 교안). 쪽 이미지만으로 매핑하세요.")

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
