"""python -m server.lecture {transcribe,prepare,models}"""
import argparse
import logging
import sys
from pathlib import Path

from server.lecture.layout import LayoutError, output_dir
from server.lecture.models import download_models
from server.lecture.pipeline import prepare_course, transcribe_lecture
from server.lecture.whisper import MODEL_SIZES, WhisperCli

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="npm run lecture --", description="강의 전사와 교안 정리 입력 준비")
    commands = parser.add_subparsers(dest="command", required=True)
    transcribe = commands.add_parser("transcribe", help="강의 영상·음성을 전사합니다.")
    transcribe.add_argument("file", type=Path)
    transcribe.add_argument("--course", required=True, help="강의 이름(폴더 이름이 됩니다)")
    transcribe.add_argument("--week", type=int, required=True, help="주차")
    transcribe.add_argument("--session", type=int, required=True, help="그 주차의 몇 번째 강의인지")
    transcribe.add_argument("--force", action="store_true", help="이미 있는 전사체를 덮어씁니다.")
    prepare = commands.add_parser("prepare", help="교안 PDF를 페이지로 만들고 정리-작업.md를 갱신합니다.")
    prepare.add_argument("--course", required=True)
    models = commands.add_parser("models", help="whisper 모델 파일을 내려받습니다.")
    models.add_argument("--size", default="large-v3", choices=MODEL_SIZES)
    return parser


def main(argv=None, root: Path = PROJECT_ROOT, engine_factory=WhisperCli.from_env) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "models":
            download_models(root, args.size)
        elif args.command == "prepare":
            print("\n".join(prepare_course(root, args.course)))
        else:
            paths, notes = transcribe_lecture(root, args.course, args.week, args.session,
                                              args.file.expanduser(), engine_factory(root), force=args.force)
            print("전사 완료:")
            for path in paths:
                print(f"  {path.relative_to(root).as_posix()}")
            print("\n".join(notes))
            folder = output_dir(root, args.course).relative_to(root).as_posix()
            print(f'\n이제 에이전트에게 말하세요: "{folder}/정리-작업.md대로 정리해줘"')
        return 0
    except (LayoutError, FileNotFoundError, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
