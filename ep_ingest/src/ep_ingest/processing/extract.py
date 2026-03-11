from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from ep_ingest.errors import ParsingError


def extract_text(content_type: str, local_path: str) -> str:
    path = Path(local_path)
    if not path.exists():
        raise ParsingError(f"Local artifact not found for extraction: {path}")
    if content_type == "pdf":
        return extract_pdf_text(path)
    if content_type == "html":
        return extract_html_text(path)
    raise ParsingError(f"Unsupported content type for extraction: {content_type}")


def extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return _extract_pdf_text_fallback(path)
    try:
        document = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise ParsingError(f"Failed to open PDF: {path}") from exc
    chunks: list[str] = []
    for page in document:
        text = page.get_text("text").strip()
        chunks.append(text)
    document.close()
    return "\n\n---PAGE BREAK---\n\n".join(chunks).strip()


def _extract_pdf_text_fallback(path: Path) -> str:
    data = path.read_bytes()
    text = data.decode("latin-1", errors="ignore")
    matches = re.findall(r"\((.*?)\)\s*Tj", text, flags=re.DOTALL)
    if not matches:
        return ""
    cleaned = [m.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\") for m in matches]
    return "\n".join(cleaned).strip()


def extract_html_text(path: Path) -> str:
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    body = soup.find("main") or soup.find("article") or soup.body or soup
    text = body.get_text("\n", strip=True)
    return text.strip()
