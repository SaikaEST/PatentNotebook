from app.pipelines.adapters.registry import resolve_provider_order
from app.services.document_classifier import classify_doc_type, infer_doc_type, should_auto_include


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
    assert infer_doc_type("Claims.pdf") == "claims"
    assert infer_doc_type("Amended claims.pdf") == "amended_claims"
    assert infer_doc_type("Communication from the Examining Division.pdf") == "communication_from_examining_division"
    assert infer_doc_type("unknown_file.bin") == "other"


def test_classify_doc_type_prefers_requested_ep_categories():
    assert classify_doc_type(raw_label="Communication from the Examining Division", file_name="x.pdf") == "communication_from_examining_division"
    assert classify_doc_type(raw_label="Annex to the communication", file_name="x.pdf") == "annex_to_the_communication"
    assert classify_doc_type(raw_label="Reply to communication from the Examining Division", file_name="x.pdf") == "reply_to_communication_from_examining_division"
    assert classify_doc_type(raw_label="Claims", file_name="x.pdf") == "claims"
    assert classify_doc_type(raw_label="Amended claims", file_name="x.pdf") == "amended_claims"
    assert classify_doc_type(raw_label="Amended claims with annotations", file_name="x.pdf") == "amended_claims_with_annotations"
    assert classify_doc_type(raw_label="European search opinion", file_name="x.pdf") == "european_search_opinion"
    assert classify_doc_type(raw_label="Search report", file_name="x.pdf") == "other"


def test_should_auto_include_excludes_other():
    assert should_auto_include("claims") is True
    assert should_auto_include("other") is False
    assert should_auto_include(None) is False
