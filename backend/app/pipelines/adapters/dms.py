import mimetypes
from pathlib import Path
from typing import Dict, List

from app.core.config import settings
from app.pipelines.adapters.base import IngestAdapter


class DMSAdapter(IngestAdapter):
    name = "dms"
    is_official = False

    def list_documents(self, case_no: str) -> List[Dict]:
        case_path = Path(settings.dms_root) / case_no
        if not case_path.exists() or not case_path.is_dir():
            return []

        pattern = "**/*" if settings.dms_recursive else "*"
        docs: List[Dict] = []
        for path in sorted(case_path.glob(pattern)):
            if not path.is_file():
                continue
            docs.append(
                {
                    "file_path": str(path),
                    "file_name": path.name,
                    "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "source_uri": str(path),
                }
            )
        return docs

    def fetch_document(self, doc_meta: dict) -> Dict:
        file_path = doc_meta.get("file_path")
        if not file_path:
            return {}

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return {}

        return {
            "file_name": doc_meta.get("file_name") or path.name,
            "content_type": doc_meta.get("content_type") or "application/octet-stream",
            "bytes": path.read_bytes(),
            "source_uri": doc_meta.get("source_uri") or str(path),
        }
