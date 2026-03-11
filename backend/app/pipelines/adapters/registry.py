from typing import Dict, List

from app.pipelines.adapters.base import IngestAdapter
from app.pipelines.adapters.cnipa import CNIPAAdapter
from app.pipelines.adapters.cnipr import CNIPRAdapter
from app.pipelines.adapters.dms import DMSAdapter
from app.pipelines.adapters.epo import EPOAdapter
from app.pipelines.adapters.uspto import USPTOAdapter

ADAPTERS: Dict[str, IngestAdapter] = {
    "cnipr": CNIPRAdapter(),
    "cnipa": CNIPAAdapter(),
    "epo": EPOAdapter(),
    "uspto": USPTOAdapter(),
    "dms": DMSAdapter(),
}

JURISDICTION_DEFAULTS = {
    "CN": ["cnipr"],
    "EU": ["epo"],
    "US": ["uspto"],
}


def resolve_provider_order(
    jurisdiction: str | None,
    providers: List[str] | None,
    prefer_official: bool,
    include_dms_fallback: bool,
) -> List[str]:
    normalized = [p.lower() for p in (providers or []) if p]
    if not normalized:
        normalized = JURISDICTION_DEFAULTS.get((jurisdiction or "").upper(), []).copy()

    normalized = [p for p in normalized if p in ADAPTERS]
    if include_dms_fallback and "dms" not in normalized:
        normalized.append("dms")

    if prefer_official:
        normalized.sort(key=lambda p: 1 if p == "dms" else 0)
    return normalized
