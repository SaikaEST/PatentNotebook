from ep_ingest.identifiers import normalize_identifier


def test_normalize_publication_number() -> None:
    normalized = normalize_identifier(" ep4674798 ")
    assert normalized.normalized == "EP4674798"
    assert normalized.kind == "publication"
    assert normalized.publication_number == "EP4674798"
    assert normalized.patent_id == "EP:EP4674798"


def test_normalize_application_number() -> None:
    normalized = normalize_identifier("25187001.0")
    assert normalized.normalized == "EP25187001.0"
    assert normalized.kind == "application"
    assert normalized.application_number == "EP25187001.0"
