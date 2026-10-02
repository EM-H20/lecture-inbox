"""whisper-cli (whisper.cpp) adapter. Ported from Chuseok22/transcribe-inbox (MIT).

`-mc 0` stops repetition loops from carrying across decode windows; any loop that still
happens inside one window is re-decoded from the isolated clip, then marked if it persists.
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from server.lecture.audio import extract_wav_span, wav_duration_seconds
from server.lecture.repetition import find_repetition_span
from server.lecture.transcript import Segment, Transcript

log = logging.getLogger(__name__)

MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")
VAD_MODEL_FILE = "ggml-silero-v6.2.0.bin"
MAX_RETRY_SPAN_SECONDS = 180.0
REPETITION_PLACEHOLDER = "[⚠️ 반복 감지 - 확인 필요] "
RETRY_PERTURBATIONS = ([], ["-et", "2.6", "-tp", "0.5"])
CANCELLED = "전사가 취소되었습니다."


class WhisperCli:
    def __init__(self, binary: str, model_path: str, vad_model_path: str, popen=subprocess.Popen):
        self.binary, self.model_path, self.vad_model_path, self.popen = binary, model_path, vad_model_path, popen
        self._stopped = threading.Event()
        self._process = None

    def stop(self) -> None:
        """Ask a running (or about to run) transcription to end; later _run calls refuse to start."""
        self._stopped.set()
        process = self._process
        if process is not None:
            process.terminate()

    @classmethod
    def from_env(cls, root: Path) -> "WhisperCli":
        binary = os.environ.get("WHISPER_CLI_BINARY") or shutil.which("whisper-cli")
        if not binary:
            raise RuntimeError("whisper-cli를 찾을 수 없습니다. `brew install whisper-cpp`를 실행해 주세요.")
        size = os.environ.get("WHISPER_MODEL", "large-v3")
        if size not in MODEL_SIZES:
            raise RuntimeError(f"WHISPER_MODEL은 {', '.join(MODEL_SIZES)} 중 하나여야 합니다.")
        model, vad = root / "models" / f"ggml-{size}.bin", root / "models" / VAD_MODEL_FILE
        for path in (model, vad):
            if not path.is_file():
                raise RuntimeError(f"모델 파일이 없습니다: {path}\n`npm run lecture -- models --size {size}`로 받아 주세요.")
        return cls(binary, str(model), str(vad))

    def transcribe(self, wav: Path, source_filename: str, language: str = "ko") -> Transcript:
        segments = self._segments(self._run(wav, ["-mc", "0", "-l", language]))
        return Transcript(
            model=Path(self.model_path).stem,
            language=language,
            source_filename=source_filename,
            duration_seconds=wav_duration_seconds(wav),  # from the WAV header: VAD trims trailing silence
            segments=self._resolve_repetitions(segments, wav, language),
        )

    def _run(self, wav: Path, extra_args: list[str]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "result"
            args = [self.binary, "--vad", "--vad-model", self.vad_model_path, "-m", self.model_path,
                    "-oj", "-of", str(prefix), "-f", str(wav), *extra_args]
            if self._stopped.is_set():
                raise RuntimeError(CANCELLED)
            process = self.popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self._process = process
            try:
                if self._stopped.is_set():  # stop() raced with the launch
                    process.terminate()
                _, stderr = process.communicate()
            finally:
                self._process = None
            if self._stopped.is_set():
                raise RuntimeError(CANCELLED)
            if process.returncode != 0:
                raise RuntimeError(f"whisper-cli exited {process.returncode}: {(stderr or b'').decode(errors='replace')[-500:]}")
            # whisper.cpp can split one Hangul character across segments and emit invalid UTF-8
            # (upstream ggml-org/whisper.cpp#1798): decode leniently instead of failing the whole run.
            return json.loads((prefix.parent / "result.json").read_bytes().decode("utf-8", errors="replace"))

    @staticmethod
    def _segments(raw: dict, offset: float = 0.0) -> list[Segment]:
        return [Segment(offset + e["offsets"]["from"] / 1000.0, offset + e["offsets"]["to"] / 1000.0, e["text"].strip())
                for e in raw.get("transcription", []) if e["text"].strip()]

    def _resolve_repetitions(self, segments: list[Segment], wav: Path, language: str) -> list[Segment]:
        search_from = 0
        with tempfile.TemporaryDirectory() as tmp:
            while True:
                span = find_repetition_span(segments[search_from:])
                if span is None:
                    return segments
                start, end = search_from + span[0], search_from + span[1]
                fixed = self._retry_span(segments[start:end + 1], wav, language, Path(tmp))
                segments = segments[:start] + fixed + segments[end + 1:]
                search_from = start + len(fixed)  # always moves forward, so the loop terminates

    def _retry_span(self, span: list[Segment], wav: Path, language: str, tmp: Path) -> list[Segment]:
        first, last = span[0], span[-1]
        placeholder = [Segment(first.start, last.end, REPETITION_PLACEHOLDER + first.text)]
        if last.end - first.start > MAX_RETRY_SPAN_SECONDS:
            log.warning("반복 구간 %.0f–%.0f초가 너무 길어 재시도 없이 표시만 합니다.", first.start, last.end)
            return placeholder
        clip = tmp / "retry.wav"
        offset = extract_wav_span(wav, first.start, last.end, clip)
        for extra in RETRY_PERTURBATIONS:
            try:
                raw = self._run(clip, ["-mc", "0", *extra, "-l", language])
            except Exception:  # a failed retry must not sink an otherwise good transcription
                if self._stopped.is_set():
                    raise  # ...but a cancelled run must end here instead of falling through to a placeholder
                log.warning("반복 구간 재디코딩 실패 (%.0f–%.0f초)", first.start, last.end, exc_info=True)
                continue
            retried = self._segments(raw, offset)
            if retried and find_repetition_span(retried) is None:
                return retried
        log.warning("반복 구간 %.0f–%.0f초를 해결하지 못해 표시합니다.", first.start, last.end)
        return placeholder
