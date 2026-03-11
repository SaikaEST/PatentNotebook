from __future__ import annotations

import json
from pathlib import Path

import httpx

from ep_ingest.service import EpIngestionService
from ep_ingest.storage import build_output_paths


def _fixture(path: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / path).read_bytes()


def test_run_pipeline_with_recorded_fixtures(tmp_path: Path) -> None:
    case_html = _fixture("register_case_page.html")
    all_docs_html = _fixture("register_all_documents.html")
    pdf_search = _fixture("pdfs/doc_search_001.pdf")
    pdf_notice = _fixture("pdfs/doc_notice_001.pdf")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "application?number=4674798" in url:
            return httpx.Response(200, text=case_html.decode("utf-8"))
        if "tab=allDocuments" in url:
            return httpx.Response(200, text=all_docs_html.decode("utf-8"))
        if url.endswith("/download/doc_search_001.pdf"):
            return httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=pdf_search,
            )
        if url.endswith("/download/doc_notice_001.pdf"):
            return httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=pdf_notice,
            )
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = EpIngestionService(http_client=client, delay_seconds=0, concurrency=2)
    dataset = service.run("EP4674798", out_dir=tmp_path)

    assert dataset.jurisdiction == "EP"
    assert dataset.documents
    assert any(doc.doc_type_norm == "search_report" for doc in dataset.documents)
    assert any(doc.doc_type_norm == "procedural_notice" for doc in dataset.documents)
    assert dataset.timeline == sorted(
        dataset.timeline,
        key=lambda x: (x.date or "9999-12-31", x.doc_type_norm, x.document_type_raw.lower()),
    )

    paths = build_output_paths(tmp_path, dataset.patent_id, jurisdiction="EP")
    assert paths.documents_json.exists()
    assert paths.timeline_json.exists()
    assert paths.timeline_md.exists()

    payload = json.loads(paths.documents_json.read_text(encoding="utf-8"))
    assert payload["documents"]
