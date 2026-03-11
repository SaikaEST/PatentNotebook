from __future__ import annotations

from pathlib import Path

import httpx

from ep_ingest.browser_bypass import BrowserWarmupResult, PlaywrightBypassProvider
from ep_ingest.service import EpIngestionService


def _fixture(path: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / path).read_bytes()


class _FakeBypassProvider:
    def __init__(self) -> None:
        self.calls = 0

    def warmup(self, url: str) -> BrowserWarmupResult:
        self.calls += 1
        return BrowserWarmupResult(
            final_url=url,
            html="<html><body>warmed</body></html>",
            cookies=[
                {
                    "name": "cf_clearance",
                    "value": "ok",
                    "domain": "register.epo.org",
                    "path": "/",
                }
            ],
        )


def test_browser_fallback_unblocks_case_resolution(tmp_path: Path) -> None:
    case_html = _fixture("register_case_page.html")
    all_docs_html = _fixture("register_all_documents.html")
    pdf_search = _fixture("pdfs/doc_search_001.pdf")
    pdf_notice = _fixture("pdfs/doc_notice_001.pdf")
    blocked_html = (
        "<html><script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        cookie = request.headers.get("cookie", "")
        if "application?number=4674798" in url:
            if "cf_clearance=ok" in cookie:
                return httpx.Response(200, text=case_html.decode("utf-8"))
            return httpx.Response(200, text=blocked_html)
        if "tab=allDocuments" in url:
            return httpx.Response(200, text=all_docs_html.decode("utf-8"))
        if url.endswith("/download/doc_search_001.pdf"):
            return httpx.Response(200, content=pdf_search, headers={"Content-Type": "application/pdf"})
        if url.endswith("/download/doc_notice_001.pdf"):
            return httpx.Response(200, content=pdf_notice, headers={"Content-Type": "application/pdf"})
        return httpx.Response(404, text="not found")

    provider = _FakeBypassProvider()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = EpIngestionService(
        http_client=client,
        delay_seconds=0,
        concurrency=2,
        browser_fallback=True,
        browser_bypass_provider=provider,
    )
    dataset = service.run("EP4674798", out_dir=tmp_path)
    assert provider.calls == 1
    assert dataset.documents


def test_playwright_provider_detects_challenge_markup() -> None:
    html = "<html><body>Performing security verification<input name='cf-turnstile-response'></body></html>"
    assert PlaywrightBypassProvider._looks_like_challenge(html) is True
    assert PlaywrightBypassProvider._looks_like_challenge("<html><body>All documents</body></html>") is False
