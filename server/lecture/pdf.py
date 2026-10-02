"""교안 PDFs -> per-document page images + text, for the note-taking agent to read.

Documents live in sources/<course>/교안/<name>.pdf; their pages in sources/<course>/pages/<name>/pNNN.png|.txt.
"""
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from server.lecture.layout import documents_dir, pages_dir, sources_dir

MAX_PAGES = 500
MAX_BYTES = 200 * 1024**2
RENDER_SCALE = 2
MANIFEST = ".manifest.json"


class PdfError(Exception):
    pass


@dataclass(frozen=True)
class PrepareResult:
    document: str
    status: str  # "prepared" | "unchanged" | "failed"
    pages: int = 0
    error: str = ""


def list_documents(root: Path, course: str) -> list[str]:
    folder = documents_dir(root, course)
    return sorted(path.stem for path in folder.glob("*.pdf") if path.is_file()) if folder.is_dir() else []


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


def prepare_document(root: Path, course: str, document: str) -> PrepareResult:
    """Prepare one document; raises PdfError when it cannot be opened, is too big, or is damaged."""
    pdf_path = documents_dir(root, course) / f"{document}.pdf"
    if pdf_path.stat().st_size > MAX_BYTES:
        raise PdfError(f"교안 PDF가 너무 큽니다({MAX_BYTES // 1024**2}MB 초과).")
    digest = _sha256(pdf_path)
    target = pages_dir(root, course, document)
    manifest = _read_manifest(target / MANIFEST)
    if (manifest.get("sha256") == digest and manifest.get("scale") == RENDER_SCALE
            and len(list(target.glob("p*.png"))) == manifest.get("pages")):
        return PrepareResult(document, "unchanged", manifest["pages"])
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except pdfium.PdfiumError as error:
        raise PdfError(f"교안 PDF를 열 수 없습니다(손상되었거나 암호가 걸려 있을 수 있습니다): {error}") from None
    try:
        count = len(pdf)
        if count > MAX_PAGES:
            raise PdfError(f"교안 PDF 페이지가 너무 많습니다({count}쪽, 최대 {MAX_PAGES}쪽).")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".pages-", dir=target.parent))
        try:
            for index in range(count):
                name = f"p{index + 1:03d}"
                page = pdf[index]
                textpage = page.get_textpage()
                (staging / f"{name}.txt").write_text(textpage.get_text_range(), encoding="utf-8")
                page.render(scale=RENDER_SCALE).to_pil().save(staging / f"{name}.png")
                textpage.close()
                page.close()
            (staging / MANIFEST).write_text(
                json.dumps({"sha256": digest, "pages": count, "scale": RENDER_SCALE}), encoding="utf-8")
            shutil.rmtree(target, ignore_errors=True)
            staging.rename(target)
        except Exception as error:  # a damaged page must not turn into an unhandled crash
            shutil.rmtree(staging, ignore_errors=True)
            raise PdfError(f"교안 PDF 처리 실패: {error}") from None
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    finally:
        pdf.close()
    return PrepareResult(document, "prepared", count)


def prepare_pages(root: Path, course: str) -> list[PrepareResult]:
    """Prepare every document of the course; one broken document does not stop the others."""
    names = list_documents(root, course)
    results = []
    for name in names:
        try:
            results.append(prepare_document(root, course, name))
        except PdfError as error:
            shutil.rmtree(pages_dir(root, course, name), ignore_errors=True)  # old pages would describe the old file
            results.append(PrepareResult(name, "failed", 0, str(error)))
    pages_root = sources_dir(root, course) / "pages"
    if pages_root.is_dir():
        for child in pages_root.iterdir():
            if child.is_dir() and not child.name.startswith(".") and child.name not in names:
                shutil.rmtree(child, ignore_errors=True)  # its PDF was removed
    return results


def delete_document(root: Path, course: str, document: str) -> bool:
    pdf_path = documents_dir(root, course) / f"{document}.pdf"
    existed = pdf_path.is_file()
    pdf_path.unlink(missing_ok=True)
    shutil.rmtree(pages_dir(root, course, document), ignore_errors=True)
    return existed
