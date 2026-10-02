"""교안 PDF -> page images + per-page text, for the note-taking agent to read."""
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from server.lecture.layout import sources_dir

PDF_NAME = "교안.pdf"
MAX_PAGES = 500
MAX_BYTES = 200 * 1024**2
RENDER_SCALE = 2
MANIFEST = ".manifest.json"


class PdfError(Exception):
    pass


@dataclass(frozen=True)
class PrepareResult:
    status: str  # "missing" | "unchanged" | "prepared"
    pages: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prepare_pages(root: Path, course: str) -> PrepareResult:
    folder = sources_dir(root, course)
    pdf_path = folder / PDF_NAME
    if not pdf_path.is_file():
        return PrepareResult("missing")
    if pdf_path.stat().st_size > MAX_BYTES:
        raise PdfError(f"교안 PDF가 너무 큽니다({MAX_BYTES // 1024**2}MB 초과).")
    digest = _sha256(pdf_path)
    pages_dir = folder / "pages"
    manifest = _read_manifest(pages_dir / MANIFEST)
    if (manifest.get("sha256") == digest and manifest.get("scale") == RENDER_SCALE
            and len(list(pages_dir.glob("p*.png"))) == manifest.get("pages")):
        return PrepareResult("unchanged", manifest["pages"])
    try:
        document = pdfium.PdfDocument(str(pdf_path))
    except pdfium.PdfiumError as error:
        raise PdfError(f"교안 PDF를 열 수 없습니다(손상되었거나 암호가 걸려 있을 수 있습니다): {error}") from None
    try:
        count = len(document)
        if count > MAX_PAGES:
            raise PdfError(f"교안 PDF 페이지가 너무 많습니다({count}쪽, 최대 {MAX_PAGES}쪽).")
        staging = Path(tempfile.mkdtemp(prefix=".pages-", dir=folder))
        try:
            for index in range(count):
                name = f"p{index + 1:03d}"
                page = document[index]
                textpage = page.get_textpage()
                (staging / f"{name}.txt").write_text(textpage.get_text_range(), encoding="utf-8")
                page.render(scale=RENDER_SCALE).to_pil().save(staging / f"{name}.png")
                textpage.close()
                page.close()
            (staging / MANIFEST).write_text(
                json.dumps({"sha256": digest, "pages": count, "scale": RENDER_SCALE}), encoding="utf-8")
            shutil.rmtree(pages_dir, ignore_errors=True)
            staging.rename(pages_dir)
        except Exception as error:  # a damaged page must not turn into an unhandled crash after the transcript is saved
            shutil.rmtree(staging, ignore_errors=True)
            raise PdfError(f"교안 PDF 처리 실패: {error}") from None
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    finally:
        document.close()
    return PrepareResult("prepared", count)
