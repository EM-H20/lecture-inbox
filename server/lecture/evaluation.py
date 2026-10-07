"""Read-only mechanical audit; semantic quality is deliberately left unscored."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from server.lecture.layout import LayoutError, safe_course
from server.lecture.study import note_problems, timestamp_audit


def main(argv=None):
    parser = argparse.ArgumentParser(description="기존 노트의 형식·전사 시각 검사 (내용 채점 아님)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--course", required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--notes", type=Path, nargs="+", required=True)
    args = parser.parse_args(argv)
    try:
        course = safe_course(args.course)
        transcript_bytes = (args.root / args.transcript).read_bytes()
        transcript = transcript_bytes.decode("utf-8")
        if not timestamp_audit("", transcript)["source_timestamp_count"]:
            raise ValueError("전사체에 [HH:MM:SS] 발언 시작 시각이 없습니다.")
        results = []
        for index, path in enumerate(args.notes, 1):
            note_bytes = (args.root / path).read_bytes()
            text = note_bytes.decode("utf-8")
            problems = note_problems(text, course, args.root, transcript)
            results.append({"candidate_id": f"N{index:03}",
                            "note_sha256": hashlib.sha256(note_bytes).hexdigest(),
                            "timestamps": timestamp_audit(text, transcript),
                            "mechanical_pass": not problems, "problems": problems,
                            "semantic_status": "not_evaluated", "reliability_score": None})
        print(json.dumps({"protocol": "note-reliability-v2", "mode": "mechanical-only",
                          "transcript_sha256": hashlib.sha256(transcript_bytes).hexdigest(),
                          "notes": results}, ensure_ascii=False, indent=2))
        return 0 if all(item["mechanical_pass"] for item in results) else 1
    except (OSError, ValueError, LayoutError) as error:
        print(f"평가 입력을 읽을 수 없습니다: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
