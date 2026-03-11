import json
import sys
import types
from types import SimpleNamespace

from app.pipelines.adapters.epo import EPOAdapter


def test_extract_publication_refs_from_biblio_xml():
    xml = """
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns:reg="http://www.epo.org/register">
  <reg:bibliographic-data>
    <reg:publication-reference>
      <reg:document-id>
        <reg:country>EP</reg:country>
        <reg:doc-number>4674798</reg:doc-number>
        <reg:kind>A1</reg:kind>
      </reg:document-id>
    </reg:publication-reference>
  </reg:bibliographic-data>
</ops:world-patent-data>
"""
    refs = EPOAdapter.extract_publication_refs_from_biblio_xml(xml)
    assert refs == ["EP4674798A1"]


def test_heuristic_image_paths_from_publication_ref():
    paths = EPOAdapter._heuristic_image_paths("EP4674798A1")
    assert paths == [
        "EP/4674798/A1/fullimage",
        "EP/4674798/A1/firstpage",
    ]


def test_match_comparison_category_keywords():
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="Amended claims with annotations",
            file_name="x.pdf",
        )
        == "amended_claims_with_annotations"
    )
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="Amended description with annotations",
            file_name="x.pdf",
        )
        == "amended_description_with_annotations"
    )
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="European search opinion",
            file_name="x.pdf",
        )
        == "european_search_opinion"
    )
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="Text intended for grant (clean copy)",
            file_name="x.pdf",
        )
        == "text_intended_for_grant_clean_copy"
    )
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="Claims",
            file_name="x.pdf",
        )
        == "claims"
    )
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="Description",
            file_name="x.pdf",
        )
        == "description"
    )


def test_match_comparison_category_ignores_translations():
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="German translation of claims",
            file_name="x.pdf",
        )
        is None
    )
    assert (
        EPOAdapter._match_comparison_category(
            document_type_raw="French translation of the description",
            file_name="x.pdf",
        )
        is None
    )


def test_export_comparison_candidates_creates_filtered_folder(tmp_path):
    files_dir = tmp_path / "EP" / "files" / "zip_archive"
    files_dir.mkdir(parents=True, exist_ok=True)

    claims_pdf = files_dir / "claims.pdf"
    opinion_pdf = files_dir / "european_search_opinion.pdf"
    ignored_pdf = files_dir / "random_notice.pdf"
    claims_pdf.write_bytes(b"%PDF-claims")
    opinion_pdf.write_bytes(b"%PDF-opinion")
    ignored_pdf.write_bytes(b"%PDF-random")

    adapter = EPOAdapter()
    docs = [
        {
            "local_path": str(claims_pdf),
            "file_name": claims_pdf.name,
            "document_type_raw": "Claims",
        },
        {
            "local_path": str(opinion_pdf),
            "file_name": opinion_pdf.name,
            "document_type_raw": "European search opinion",
        },
        {
            "local_path": str(ignored_pdf),
            "file_name": ignored_pdf.name,
            "document_type_raw": "Notification",
        },
    ]

    adapter._export_comparison_candidates(docs)

    comparison_dir = files_dir.parent / "comparison_candidates"
    manifest = comparison_dir / "manifest.json"
    assert manifest.exists()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["selected_count"] == 2
    assert set(payload["categories"]) == {"claims", "european_search_opinion"}

    copied_claims = comparison_dir / "claims" / "claims.pdf"
    copied_opinion = comparison_dir / "european_search_opinion" / "european_search_opinion.pdf"
    assert copied_claims.exists()
    assert copied_opinion.exists()


def test_list_documents_fallback_to_ops_when_register_empty(monkeypatch):
    adapter = EPOAdapter()
    adapter._ops = object()

    monkeypatch.setattr("app.pipelines.adapters.epo.settings.ep_register_only", False)
    monkeypatch.setattr(adapter, "_list_documents_from_register", lambda _: [])
    monkeypatch.setattr(adapter, "_collect_publication_refs", lambda _: ["EP1234567A1"])
    monkeypatch.setattr(
        adapter,
        "_image_paths_from_inquiry",
        lambda _: ["EP/1234567/A1/fullimage", "EP/1234567/A1/firstpage"],
    )

    docs = adapter.list_documents("EP1234567A1")
    assert len(docs) == 2
    assert docs[0]["file_name"] == "EP1234567A1_fullimage.pdf"
    assert docs[1]["file_name"] == "EP1234567A1_firstpage.pdf"


def test_list_documents_respects_register_only_mode(monkeypatch):
    adapter = EPOAdapter()
    adapter._ops = object()

    monkeypatch.setattr("app.pipelines.adapters.epo.settings.ep_register_only", True)
    monkeypatch.setattr(adapter, "_list_documents_from_register", lambda _: [])
    monkeypatch.setattr(adapter, "_collect_publication_refs", lambda _: ["EP1234567A1"])
    monkeypatch.setattr(adapter, "_image_paths_from_inquiry", lambda _: ["EP/1234567/A1/fullimage"])

    docs = adapter.list_documents("EP1234567A1")
    assert docs == []


def test_list_documents_from_register_keeps_html_documents(monkeypatch, tmp_path):
    pdf_path = tmp_path / "zip_archive" / "claims.pdf"
    html_path = tmp_path / "zip_archive" / "notice.html"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-claims")
    html_path.write_text("<html><body>notice</body></html>", encoding="utf-8")

    dataset = SimpleNamespace(
        register_case_id="EP1234567",
        documents=[
            SimpleNamespace(
                local_path=str(pdf_path),
                document_type_raw="Claims",
                file_url="https://register.epo.org/doc?pdf=1",
                register_document_id="DOC001",
            ),
            SimpleNamespace(
                local_path=str(html_path),
                document_type_raw="Register notice",
                file_url="https://register.epo.org/doc?html=1",
                register_document_id="DOC002",
            ),
        ],
    )

    class FakeService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fetch(self, case_no, out_dir):
            return dataset

    fake_pkg = types.ModuleType("ep_ingest")
    fake_service = types.ModuleType("ep_ingest.service")
    fake_service.EpIngestionService = FakeService
    fake_identifiers = types.ModuleType("ep_ingest.identifiers")
    fake_identifiers.normalize_identifier = lambda case_no: SimpleNamespace(patent_id="EP:EP1234567")
    fake_storage = types.ModuleType("ep_ingest.storage")
    fake_storage.build_output_paths = lambda out_root, patent_id, jurisdiction="EP": SimpleNamespace(
        cache_dir=tmp_path / "cache"
    )

    monkeypatch.setitem(sys.modules, "ep_ingest", fake_pkg)
    monkeypatch.setitem(sys.modules, "ep_ingest.service", fake_service)
    monkeypatch.setitem(sys.modules, "ep_ingest.identifiers", fake_identifiers)
    monkeypatch.setitem(sys.modules, "ep_ingest.storage", fake_storage)

    docs = EPOAdapter()._list_documents_from_register("EP1234567")

    assert [doc["file_name"] for doc in docs] == ["claims.pdf", "notice.html"]
    assert [doc["content_type"] for doc in docs] == ["application/pdf", "text/html"]


def test_list_documents_from_register_uses_all_zip_archive_files(monkeypatch, tmp_path):
    zip_dir = tmp_path / "EP" / "files" / "zip_archive"
    zip_dir.mkdir(parents=True, exist_ok=True)
    claims_path = zip_dir / "claims.pdf"
    html_path = zip_dir / "notice.html"
    toc_path = zip_dir / "toc.xml"
    claims_path.write_bytes(b"%PDF-claims")
    html_path.write_text("<html><body>notice</body></html>", encoding="utf-8")
    toc_path.write_text("<toc/>", encoding="utf-8")

    dataset = SimpleNamespace(
        register_case_id="EP17893014",
        documents=[
            SimpleNamespace(
                local_path=str(claims_path),
                document_type_raw="Claims",
                file_url="https://register.epo.org/doc?pdf=1",
                register_document_id="DOC001",
            )
        ],
    )

    class FakeService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fetch(self, case_no, out_dir):
            return dataset

    fake_pkg = types.ModuleType("ep_ingest")
    fake_service = types.ModuleType("ep_ingest.service")
    fake_service.EpIngestionService = FakeService
    fake_identifiers = types.ModuleType("ep_ingest.identifiers")
    fake_identifiers.normalize_identifier = lambda case_no: SimpleNamespace(patent_id="EP:EP17893014")
    fake_storage = types.ModuleType("ep_ingest.storage")
    fake_storage.build_output_paths = lambda out_root, patent_id, jurisdiction="EP": SimpleNamespace(
        cache_dir=tmp_path / "cache",
        files_dir=tmp_path / "EP" / "files",
    )

    monkeypatch.setitem(sys.modules, "ep_ingest", fake_pkg)
    monkeypatch.setitem(sys.modules, "ep_ingest.service", fake_service)
    monkeypatch.setitem(sys.modules, "ep_ingest.identifiers", fake_identifiers)
    monkeypatch.setitem(sys.modules, "ep_ingest.storage", fake_storage)

    docs = EPOAdapter()._list_documents_from_register("EP17893014")

    assert [doc["file_name"] for doc in docs] == ["claims.pdf", "notice.html", "toc.xml"]
    assert [doc["content_type"] for doc in docs] == [
        "application/pdf",
        "text/html",
        "application/xml",
    ]


def test_fetch_document_reads_local_html_payload(tmp_path):
    html_path = tmp_path / "register_notice.html"
    html_path.write_text("<html><body>hello</body></html>", encoding="utf-8")

    fetched = EPOAdapter().fetch_document({"local_path": str(html_path)})

    assert fetched["file_name"] == "register_notice.html"
    assert fetched["content_type"] == "text/html"
    assert b"hello" in fetched["bytes"]
