from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

from ep_ingest.http_client import HttpResult
from ep_ingest.metrics import Metrics
from ep_ingest.models import DocumentRecord, IdentifierMapping, PatentDataset
from ep_ingest.processing.comparison_candidates import export_comparison_candidates
from ep_ingest.scraper.register import RegisterScraper, ZipArchivePayload
from ep_ingest.service import EpIngestionService
from ep_ingest.storage import build_output_paths


class _DummyFetcher:
    def __init__(self, zip_payload: bytes) -> None:
        self.zip_payload = zip_payload
        self.calls: list[dict[str, object]] = []

    def post_form(
        self,
        url: str,
        form_data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        self.calls.append(
            {
                "url": url,
                "form_data": dict(form_data),
                "headers": dict(headers or {}),
            }
        )
        return HttpResult(
            url=url,
            status_code=200,
            content=self.zip_payload,
            headers={"content-type": "application/zip"},
        )

    def try_browser_bypass(self, url: str) -> bool:
        return False


def _build_zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_extract_zip_archive_files_posts_page_form_data(tmp_path: Path) -> None:
    fetcher = _DummyFetcher(
        _build_zip_bytes(
            {
                "Claims.pdf": b"%PDF-claims",
                "Description.pdf": b"%PDF-description",
            }
        )
    )
    scraper = RegisterScraper(
        fetcher=fetcher,
        metrics=Metrics(),
        logger=logging.getLogger(__name__),
        concurrency=1,
    )
    payload = ZipArchivePayload(
        action_url="https://register.epo.org/download",
        application_number="EP17893014",
        document_ids=["DOC001", "DOC002"],
        form_data={
            "number": "EP17893014",
            "output": "zip",
            "unip": "false",
            "csrfToken": "token-123",
        },
        referer_url="https://register.epo.org/application?tab=doclist&number=EP17893014&lng=en",
    )

    extracted = scraper._extract_zip_archive_files(payload, tmp_path)

    assert len(extracted) == 2
    assert {path.name for path in extracted} == {"Claims.pdf", "Description.pdf"}
    assert len(fetcher.calls) == 1
    call = fetcher.calls[0]
    assert call["url"] == "https://register.epo.org/download"
    assert call["form_data"] == {
        "number": "EP17893014",
        "output": "zip",
        "unip": "false",
        "csrfToken": "token-123",
        "documentIdentifiers": "DOC001+DOC002",
    }
    assert call["headers"] == {
        "Accept": "application/zip, application/octet-stream;q=0.9, */*;q=0.8",
        "Origin": "https://register.epo.org",
        "Referer": "https://register.epo.org/application?tab=doclist&number=EP17893014&lng=en",
    }


def test_extract_zip_archive_files_keeps_existing_archive_when_refresh_fails(tmp_path: Path) -> None:
    fetcher = _DummyFetcher(b"not-a-real-zip")
    scraper = RegisterScraper(
        fetcher=fetcher,
        metrics=Metrics(),
        logger=logging.getLogger(__name__),
        concurrency=1,
    )
    payload = ZipArchivePayload(
        action_url="https://register.epo.org/download",
        application_number="EP12157717",
        document_ids=["DOC001"],
        form_data={"number": "EP12157717"},
        referer_url="https://register.epo.org/application?tab=doclist&number=EP12157717&lng=en",
    )
    existing_dir = tmp_path / "zip_archive"
    existing_dir.mkdir(parents=True, exist_ok=True)
    existing_file = existing_dir / "existing.pdf"
    existing_file.write_bytes(b"%PDF-existing")

    extracted = scraper._extract_zip_archive_files(payload, tmp_path)

    assert extracted == []
    assert existing_file.exists()
    assert existing_file.read_bytes() == b"%PDF-existing"


def test_fetch_exports_comparison_candidates(monkeypatch, tmp_path: Path) -> None:
    service = EpIngestionService(delay_seconds=0, browser_fallback=False)
    paths = build_output_paths(tmp_path, "EP:EP17893014", jurisdiction="EP")
    zip_dir = paths.files_dir / "zip_archive"
    zip_dir.mkdir(parents=True, exist_ok=True)
    claims_file = zip_dir / "17893014-2017-01-01-CLMS-Claims.pdf"
    claims_file.write_bytes(b"%PDF-claims")

    dataset = PatentDataset(
        patent_id="EP:EP17893014",
        jurisdiction="EP",
        register_case_id="EP17893014",
        identifiers=IdentifierMapping(publication_number="EP17893014"),
        documents=[
            DocumentRecord(
                register_document_id="DOC001",
                date="2017-01-01",
                document_type_raw="Claims",
                procedure="Search / examination",
                pages=4,
                file_url="https://register.epo.org/application?documentId=DOC001",
                content_type="pdf",
                local_path=str(claims_file),
            )
        ],
        metrics={},
    )

    def fake_acquire(identifier: str, out_dir: str | Path, logger):
        return dataset, paths, Metrics()

    monkeypatch.setattr(service, "_acquire", fake_acquire)

    result = service.fetch("EP17893014", out_dir=tmp_path)

    manifest_path = paths.files_dir / "comparison_candidates" / "manifest.json"
    assert result.documents
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["selected_count"] == 1
    assert payload["categories"] == ["claims"]
    copied = paths.files_dir / "comparison_candidates" / "claims" / claims_file.name
    assert copied.exists()


def test_export_comparison_candidates_is_idempotent(tmp_path: Path) -> None:
    files_dir = tmp_path / "EP" / "files"
    zip_dir = files_dir / "zip_archive"
    zip_dir.mkdir(parents=True, exist_ok=True)
    claims_file = zip_dir / "claims.pdf"
    claims_file.write_bytes(b"%PDF-claims")

    documents = [
        DocumentRecord(
            register_document_id="DOC001",
            date="2017-01-01",
            document_type_raw="Claims",
            procedure="Search / examination",
            pages=4,
            file_url="https://register.epo.org/application?documentId=DOC001",
            content_type="pdf",
            local_path=str(claims_file),
        )
    ]

    first = export_comparison_candidates(documents, files_dir)
    second = export_comparison_candidates(documents, files_dir)

    comparison_dir = files_dir / "comparison_candidates" / "claims"
    copied_files = sorted(path.name for path in comparison_dir.glob("*.pdf"))
    manifest = json.loads((files_dir / "comparison_candidates" / "manifest.json").read_text(encoding="utf-8"))

    assert first["selected_count"] == 1
    assert second["selected_count"] == 1
    assert copied_files == ["claims.pdf"]
    assert Path(manifest["files"][0]["target_path"]).name == "claims.pdf"
