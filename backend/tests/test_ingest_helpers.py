from app.pipelines.adapters.registry import resolve_provider_order
from app.services.document_classifier import infer_doc_type


def test_resolve_provider_order_uses_jurisdiction_default_with_dms_fallback():
    order = resolve_provider_order(
        jurisdiction="US",
        providers=[],
        prefer_official=True,
        include_dms_fallback=True,
    )
    assert order == ["uspto", "dms"]


def test_resolve_provider_order_cn_defaults_to_cnipr():
    order = resolve_provider_order(
        jurisdiction="CN",
        providers=[],
        prefer_official=True,
        include_dms_fallback=True,
    )
    assert order == ["cnipr", "dms"]


def test_resolve_provider_order_filters_unknown_providers():
    order = resolve_provider_order(
        jurisdiction="EU",
        providers=["foo", "dms", "epo"],
        prefer_official=True,
        include_dms_fallback=True,
    )
    assert order == ["epo", "dms"]


def test_resolve_provider_order_keeps_cnipa_alias():
    order = resolve_provider_order(
        jurisdiction="CN",
        providers=["cnipa"],
        prefer_official=True,
        include_dms_fallback=True,
    )
    assert order == ["cnipa", "dms"]


def test_infer_doc_type_from_file_name():
    assert infer_doc_type("First Office Action.pdf") == "office_action"
    assert infer_doc_type("Applicant_Response_2025-01-18.docx") == "response"
    assert infer_doc_type("unknown_file.bin") == "other"
