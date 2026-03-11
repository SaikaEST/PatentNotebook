from ep_ingest.processing.classify import classify_document


def test_classify_search_report_from_text() -> None:
    label = "Document"
    text = "EUROPEAN SEARCH REPORT\nThis is the report body."
    assert classify_document(label, text) == "search_report"


def test_classify_procedural_notice_from_label() -> None:
    label = "Notification of forthcoming publication"
    text = ""
    assert classify_document(label, text) == "procedural_notice"
