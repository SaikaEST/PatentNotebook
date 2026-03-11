from typing import List, Dict

from app.pipelines.adapters.base import IngestAdapter


class IngestPipeline:
    def __init__(self, adapter: IngestAdapter):
        self.adapter = adapter

    def run(self, case_no: str) -> List[Dict]:
        docs = self.adapter.list_documents(case_no)
        fetched = []
        for meta in docs:
            fetched.append(self.adapter.fetch_document(meta))
        return fetched
