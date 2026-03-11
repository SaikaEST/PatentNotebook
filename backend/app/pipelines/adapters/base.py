from typing import Dict, List, Protocol


class IngestAdapter(Protocol):
    name: str
    is_official: bool

    def list_documents(self, case_no: str) -> List[Dict]:
        ...

    def fetch_document(self, doc_meta: Dict) -> Dict:
        ...
