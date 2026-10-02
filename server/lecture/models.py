"""Model download. The files are large, so this runs only when the user asks for it."""
import shutil
import urllib.request
from pathlib import Path

from server.lecture.whisper import VAD_MODEL_FILE

ASR_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{size}.bin"
VAD_URL = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/" + VAD_MODEL_FILE


def download_models(root: Path, size: str) -> None:
    folder = root / "models"
    folder.mkdir(exist_ok=True)
    for url, name in ((ASR_URL.format(size=size), f"ggml-{size}.bin"), (VAD_URL, VAD_MODEL_FILE)):
        target = folder / name
        if target.exists():
            print(f"이미 있음: {target}")
            continue
        print(f"받는 중: {url}")
        part = target.with_name(name + ".part")
        try:
            with urllib.request.urlopen(url) as response, part.open("wb") as out:
                shutil.copyfileobj(response, out)
            part.rename(target)
        finally:
            part.unlink(missing_ok=True)
        print(f"저장: {target}")
