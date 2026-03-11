import re
from functools import lru_cache
from io import BytesIO
from typing import Dict, Iterable, List

from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.core.config import settings


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_document_bytes(data: bytes, filename: str | None = None) -> Dict:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _parse_pdf(data)
    if name.endswith(".html") or name.endswith(".htm"):
        return _parse_html(data)
    if name.endswith(".xml"):
        return _parse_xml(data)
    return _parse_text(data)


def _parse_pdf(data: bytes) -> Dict:
    reader = PdfReader(BytesIO(data))
    pages = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append({"page_no": idx, "text": _clean_text(text)})

    extraction_mode = "pdf_text"
    if _should_apply_ocr(pages):
        ocr_pages = _ocr_pdf_pages(data)
        if ocr_pages:
            merged_pages = []
            replaced_pages = 0
            for page in pages:
                page_no = page.get("page_no")
                raw_text = page.get("text", "")
                ocr_text = ocr_pages.get(page_no, "")
                if len(raw_text) < settings.pdf_ocr_page_min_chars and ocr_text:
                    replaced_pages += 1
                    merged_pages.append({"page_no": page_no, "text": _clean_text(ocr_text)})
                else:
                    merged_pages.append(page)
            pages = merged_pages
            if replaced_pages > 0:
                extraction_mode = "pdf_text_plus_ocr"

    return {"pages": pages, "meta": {"text_extraction": extraction_mode}}


def _parse_html(data: bytes) -> Dict:
    soup = BeautifulSoup(data, "html.parser")
    text = soup.get_text(" ")
    return {"pages": [{"page_no": 1, "text": _clean_text(text)}], "meta": {"text_extraction": "html_text"}}


def _parse_xml(data: bytes) -> Dict:
    soup = BeautifulSoup(data, "xml")
    text = soup.get_text(" ")
    return {"pages": [{"page_no": 1, "text": _clean_text(text)}], "meta": {"text_extraction": "xml_text"}}


def _parse_text(data: bytes) -> Dict:
    text = data.decode("utf-8", errors="ignore")
    return {"pages": [{"page_no": 1, "text": _clean_text(text)}], "meta": {"text_extraction": "plain_text"}}


def chunk_pages(pages: List[Dict], max_chars: int = 1500) -> Iterable[Dict]:
    for page in pages:
        text = page.get("text", "")
        page_no = page.get("page_no")
        for i in range(0, len(text), max_chars):
            yield {
                "page_no": page_no,
                "text": text[i : i + max_chars],
            }


def _should_apply_ocr(pages: List[Dict]) -> bool:
    if not settings.enable_pdf_ocr:
        return False
    if not pages:
        return False
    total_chars = sum(len((page.get("text") or "").strip()) for page in pages)
    if total_chars < settings.pdf_ocr_min_chars:
        return True
    short_pages = sum(
        1
        for page in pages
        if len((page.get("text") or "").strip()) < settings.pdf_ocr_page_min_chars
    )
    return short_pages >= max(1, len(pages) // 2)


@lru_cache(maxsize=1)
def _get_rapidocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None

    try:
        return RapidOCR()
    except Exception:
        return None


def _ocr_pdf_pages(data: bytes) -> Dict[int, str]:
    engine = _get_rapidocr_engine()
    if engine is None:
        return {}

    try:
        import fitz
        import numpy as np
    except Exception:
        return {}

    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return {}

    result: Dict[int, str] = {}
    max_pages = max(1, int(settings.pdf_ocr_max_pages))
    scale = float(settings.pdf_ocr_scale)
    matrix = fitz.Matrix(scale, scale)

    try:
        for page_index in range(min(len(pdf), max_pages)):
            page = pdf[page_index]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            channels = pix.n
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, channels
            )
            if channels == 4:
                image = image[:, :, :3]

            try:
                ocr_result, _ = engine(image)
            except Exception:
                continue

            text = _extract_ocr_text(ocr_result)
            if text:
                result[page_index + 1] = _clean_text(text)
    finally:
        pdf.close()

    return result


def _extract_ocr_text(ocr_result) -> str:
    if not ocr_result:
        return ""

    texts: List[str] = []
    for item in ocr_result:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue

        text_part = item[1]
        if isinstance(text_part, str):
            text = text_part
        elif isinstance(text_part, (list, tuple)) and text_part:
            text = str(text_part[0])
        else:
            text = ""

        if text:
            texts.append(text)

    return "\n".join(texts)
