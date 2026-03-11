from app.pipelines.adapters.cnipr import CNIPRAdapter


class CNIPAAdapter(CNIPRAdapter):
    # Backward-compatible alias. Prefer using provider key "cnipr".
    name = "cnipa"
