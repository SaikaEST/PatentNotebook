from ep_ingest.errors import NotFoundError
from ep_ingest.errors import NetworkError
from ep_ingest.ops_exam_files import OpsExamFileService, _extract_ops_image_path


class _DummyOpsClient:
    def __init__(self, image_payloads: dict[str, str]) -> None:
        self.image_payloads = image_payloads

    def published_images_inquiry(self, *, reference_type: str, epodoc_input: str, accept: str = "application/xml") -> str:  # noqa: ARG002
        if epodoc_input not in self.image_payloads:
            raise NotFoundError("not found")
        if self.image_payloads[epodoc_input] == "__406__":
            raise NetworkError("OPS returned status 406 for published-data/images/publication/epodoc/...")
        return self.image_payloads[epodoc_input]


def test_extract_examination_events_filters_non_exam_items() -> None:
    service = OpsExamFileService(ops_client=_DummyOpsClient({}))
    payloads = {
        "events": """
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns:reg="http://www.epo.org/register">
  <reg:register-documents>
    <reg:dossier-event id="EVT_1" event-type="new">
      <reg:event-date><reg:date>20240115</reg:date></reg:event-date>
      <reg:event-code>0001</reg:event-code>
      <reg:event-text event-text-type="DESCRIPTION">Communication from Examining Division dispatched</reg:event-text>
    </reg:dossier-event>
    <reg:dossier-event id="EVT_2" event-type="new">
      <reg:event-date><reg:date>20240201</reg:date></reg:event-date>
      <reg:event-code>0002</reg:event-code>
      <reg:event-text event-text-type="DESCRIPTION">Renewal fee paid</reg:event-text>
    </reg:dossier-event>
  </reg:register-documents>
</ops:world-patent-data>
""",
        "procedural-steps": """
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns:reg="http://www.epo.org/register">
  <reg:register-documents>
    <reg:procedural-step>
      <reg:procedural-step-date>20240302</reg:procedural-step-date>
      <reg:procedural-step-title>Applicant response to examination communication</reg:procedural-step-title>
    </reg:procedural-step>
  </reg:register-documents>
</ops:world-patent-data>
""",
    }

    all_events = service._extract_all_events(payloads)
    events = service._filter_examination_events(all_events)
    assert len(events) == 2
    assert events[0]["date"] == "2024-01-15"
    assert "examining division" in events[0]["detail"].lower()
    assert events[1]["date"] == "2024-03-02"
    assert "response" in events[1]["detail"].lower()


def test_extract_examination_events_excludes_validation_language_steps() -> None:
    service = OpsExamFileService(ops_client=_DummyOpsClient({}))
    payloads = {
        "procedural-steps": """
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns:reg="http://www.epo.org/register">
  <reg:register-documents>
    <reg:procedural-step>
      <reg:procedural-step-code>VAPT</reg:procedural-step-code>
      <reg:procedural-step-text>Validation of the patent</reg:procedural-step-text>
    </reg:procedural-step>
    <reg:procedural-step>
      <reg:procedural-step-code>PROL</reg:procedural-step-code>
      <reg:procedural-step-text>Language of the procedure</reg:procedural-step-text>
    </reg:procedural-step>
  </reg:register-documents>
</ops:world-patent-data>
""",
    }
    all_events = service._extract_all_events(payloads)
    assert service._filter_examination_events(all_events) == []


def test_collect_image_candidates_prefers_exam_or_fullimage() -> None:
    xml = """
<ops:world-patent-data xmlns:ops="http://ops.epo.org">
  <ops:document-instance desc="European search report">
    <ops:document-instance-link href="https://ops.epo.org/3.2/rest-services/published-data/images/EP/3675492/A1/fullimage"/>
  </ops:document-instance>
  <ops:document-instance desc="Claims">
    <ops:document-instance-link href="https://ops.epo.org/3.2/rest-services/published-data/images/EP/3675492/A1/claims"/>
  </ops:document-instance>
</ops:world-patent-data>
"""
    service = OpsExamFileService(ops_client=_DummyOpsClient({"EP3675492A1": xml}))
    candidates = service._collect_image_candidates(["EP3675492A1"])

    assert len(candidates) == 2
    assert candidates[0]["publication_ref"] == "EP3675492A1"
    assert candidates[0]["image_path"] == "EP/3675492/A1/fullimage"
    assert candidates[1]["image_path"] == "EP/3675492/A1/claims"


def test_extract_ops_image_path() -> None:
    href = "https://ops.epo.org/3.2/rest-services/published-data/images/EP/1000000/A1/fullimage"
    assert _extract_ops_image_path(href) == "EP/1000000/A1/fullimage"


def test_collect_image_candidates_skips_network_errors() -> None:
    xml = """
<ops:world-patent-data xmlns:ops="http://ops.epo.org">
  <ops:document-instance desc="European search report">
    <ops:document-instance-link href="https://ops.epo.org/3.2/rest-services/published-data/images/EP/3675492/A1/fullimage"/>
  </ops:document-instance>
</ops:world-patent-data>
"""
    service = OpsExamFileService(
        ops_client=_DummyOpsClient({"EP25187001P": "__406__", "EP3675492A1": xml})
    )
    candidates = service._collect_image_candidates(["EP25187001P", "EP3675492A1"])
    assert len(candidates) == 1
    assert candidates[0]["publication_ref"] == "EP3675492A1"


def test_collect_publication_refs_from_biblio_document_id() -> None:
    service = OpsExamFileService(ops_client=_DummyOpsClient({}))
    biblio = """
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
    refs = service._collect_publication_refs(
        normalized=type("N", (), {"publication_number": "EP4674798"})(),
        register_text="",
        payloads={"biblio": biblio},
    )
    assert "EP4674798A1" in refs


def test_build_heuristic_image_candidates() -> None:
    candidates = OpsExamFileService._build_heuristic_image_candidates(["EP4674798A1", "EP4674798"])
    paths = [item["image_path"] for item in candidates]
    assert "EP/4674798/A1/fullimage" in paths
    assert "EP/4674798/A1/firstpage" in paths


def test_events_to_markdown_contains_table_rows() -> None:
    markdown = OpsExamFileService._events_to_markdown(
        title="Examination Events",
        patent_id="EP:EP4674708",
        identifier="EP4674708",
        events=[
            {
                "source": "events",
                "date": "2025-12-05",
                "detail": "0009171 | Request for examination filed",
            }
        ],
    )
    assert "# Examination Events" in markdown
    assert "| 2025-12-05 | events | 0009171 \\| Request for examination filed |" in markdown


def test_extract_all_events_keeps_non_exam_event() -> None:
    service = OpsExamFileService(ops_client=_DummyOpsClient({}))
    payloads = {
        "events": """
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns:reg="http://www.epo.org/register">
  <reg:register-documents>
    <reg:dossier-event id="EVT_2" event-type="new">
      <reg:event-date><reg:date>20240201</reg:date></reg:event-date>
      <reg:event-code>0002</reg:event-code>
      <reg:event-text event-text-type="DESCRIPTION">Renewal fee paid</reg:event-text>
    </reg:dossier-event>
  </reg:register-documents>
</ops:world-patent-data>
""",
    }
    events = service._extract_all_events(payloads)
    assert len(events) == 1
    assert "renewal fee paid" in events[0]["detail"].lower()
