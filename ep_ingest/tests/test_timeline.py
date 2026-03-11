from ep_ingest.models import DocumentRecord
from ep_ingest.processing.timeline import build_timeline


def test_timeline_sorted_by_date_type_label() -> None:
    docs = [
        DocumentRecord(
            register_document_id="b",
            date="2025-11-14",
            document_type_raw="Notification of forthcoming publication",
            procedure="Publication",
            pages=1,
            file_url="https://example.invalid/b.pdf",
            content_type="pdf",
            doc_type_norm="procedural_notice",
        ),
        DocumentRecord(
            register_document_id="a",
            date="2025-10-02",
            document_type_raw="European search report",
            procedure="Search",
            pages=2,
            file_url="https://example.invalid/a.pdf",
            content_type="pdf",
            doc_type_norm="search_report",
        ),
    ]
    timeline = build_timeline(docs)
    assert [entry.register_document_id for entry in timeline] == ["a", "b"]
