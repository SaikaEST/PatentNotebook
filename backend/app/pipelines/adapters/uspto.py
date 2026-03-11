from app.pipelines.adapters.base import IngestAdapter


class USPTOAdapter(IngestAdapter):
    name = "uspto"
    is_official = True

    def list_documents(self, case_no: str):
        # Placeholder: official integration can be added here with ToS-compliant APIs.
        return []

    def fetch_document(self, doc_meta: dict):
        return {}
