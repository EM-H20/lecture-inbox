"""Helpers shared by the lecture tests (not a test module)."""
import os
import tempfile
import threading
import time
import wave
from pathlib import Path

from server.lecture.transcript import Segment, Transcript


def write_silent_wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of Latin text per page (enough for pdfium to render and extract)."""
    count = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents {5 + 2 * i} 0 R "
                       f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        stream = f"BT /F1 24 Tf 20 100 Td ({text}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


class FakeEngine:
    """Stands in for WhisperCli. `gate` (a threading.Event) holds transcribe() until it is set or stop() is called."""
    def __init__(self, segments=None, gate=None, error=None):
        self.segments = [Segment(0.0, 2.4, "안녕하세요")] if segments is None else segments
        self.gate, self.error = gate, error
        self.started, self.stopped = threading.Event(), threading.Event()

    def transcribe(self, wav, source_filename):
        self.started.set()
        while self.gate is not None and not (self.gate.is_set() or self.stopped.is_set()):
            time.sleep(0.005)
        if self.stopped.is_set():
            raise RuntimeError("전사가 취소되었습니다.")
        if self.error:
            raise self.error
        return Transcript("ggml-small", "ko", source_filename, 60.0, self.segments)

    def stop(self):
        self.stopped.set()


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def make_fake_normalize(directory: Path):
    """A stand-in for ffmpeg normalisation: hands back a throwaway file the pipeline will delete."""
    def normalize(source):
        fd, name = tempfile.mkstemp(dir=directory, suffix=".wav")
        os.close(fd)
        return Path(name)
    return normalize
