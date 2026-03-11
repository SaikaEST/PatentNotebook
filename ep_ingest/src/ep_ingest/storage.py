from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def patent_id_to_fs_name(patent_id: str) -> str:
    # Keep deterministic path names that work on Windows and Linux.
    safe = patent_id.replace(":", "_")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", safe)
    return safe


@dataclass
class OutputPaths:
    base: Path
    patent_dir: Path
    jurisdiction_dir: Path
    files_dir: Path
    text_dir: Path
    cache_dir: Path
    documents_json: Path
    timeline_json: Path
    timeline_md: Path


def build_output_paths(out_root: Path, patent_id: str, jurisdiction: str = "EP") -> OutputPaths:
    patent_fs = patent_id_to_fs_name(patent_id)
    patent_dir = out_root / patent_fs
    jurisdiction_dir = patent_dir / jurisdiction
    files_dir = jurisdiction_dir / "files"
    text_dir = jurisdiction_dir / "text"
    cache_dir = jurisdiction_dir / ".cache" / "http"
    paths = OutputPaths(
        base=out_root,
        patent_dir=patent_dir,
        jurisdiction_dir=jurisdiction_dir,
        files_dir=files_dir,
        text_dir=text_dir,
        cache_dir=cache_dir,
        documents_json=jurisdiction_dir / "documents.json",
        timeline_json=jurisdiction_dir / "timeline.json",
        timeline_md=jurisdiction_dir / "timeline.md",
    )
    for folder in [patent_dir, jurisdiction_dir, files_dir, text_dir, cache_dir]:
        folder.mkdir(parents=True, exist_ok=True)
    return paths


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
