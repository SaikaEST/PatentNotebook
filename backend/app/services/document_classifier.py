from __future__ import annotations

import re
from typing import Optional


DOC_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"office[\s_-]?action|oa|first[\s_-]?action|审查意见", "office_action"),
    (r"search[\s_-]?report|isr|检索报告", "search_report"),
    (r"response|reply|argument|答复", "response"),
    (r"amendment|claim[\s_-]?amend|补正|修改", "amendment"),
    (r"decision|notice[\s_-]?of[\s_-]?allowance|授权|驳回", "decision"),
]


def infer_doc_type(file_name: Optional[str], fallback: str = "other") -> str:
    if not file_name:
        return fallback
    normalized = file_name.lower()
    for pattern, doc_type in DOC_TYPE_PATTERNS:
        if re.search(pattern, normalized):
            return doc_type
    return fallback
