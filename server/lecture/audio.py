"""ffmpeg normalisation and WAV slicing. Ported from Chuseok22/transcribe-inbox (MIT)."""
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

PAD_SECONDS = 0.5


def normalize_to_wav(source: Path, run=subprocess.run) -> Path:
    """Decode the audio stream to 16 kHz mono WAV. Never trims silence, so timestamps stay absolute."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg를 찾을 수 없습니다. `brew install ffmpeg`를 실행해 주세요.")
    fd, name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    output = Path(name)
    try:
        result = run([ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", str(source),
                      "-vn", "-ar", "16000", "-ac", "1", str(output)], capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg가 파일을 읽지 못했습니다: {source.name} (오디오가 없거나 지원하지 않는 형식일 수 있습니다)")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return output


def wav_duration_seconds(wav: Path) -> float:
    with wave.open(str(wav), "rb") as f:
        return f.getnframes() / float(f.getframerate())


def extract_wav_span(source: Path, start_seconds: float, end_seconds: float, dest: Path) -> float:
    """Copy [start-0.5s, end+0.5s] (clamped to the file) into dest; return the source time of dest's frame 0."""
    with wave.open(str(source), "rb") as src:
        rate = src.getframerate()
        total = src.getnframes() / float(rate)
        padded_start = min(max(0.0, start_seconds - PAD_SECONDS), total)
        padded_end = max(padded_start, min(total, end_seconds + PAD_SECONDS))
        first_frame = int(padded_start * rate)
        src.setpos(first_frame)
        frames = src.readframes(int(padded_end * rate) - first_frame)
        with wave.open(str(dest), "wb") as dst:
            dst.setnchannels(src.getnchannels())
            dst.setsampwidth(src.getsampwidth())
            dst.setframerate(rate)
            dst.writeframes(frames)
    return padded_start
