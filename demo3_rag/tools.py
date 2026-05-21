"""Runtime tools for Demo 3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ingest import DATA_DIR
from .retrieval import retrieve

TRACE_DIR = DATA_DIR / "traces"
REPORT_PATH = DATA_DIR / "verification_report.md"


def ensure_data_dirs() -> None:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)


def retrieve_docs(arguments: dict[str, Any]) -> str:
    query = str(arguments.get("query") or "").strip()
    if not query:
        result = {"query": query, "evidence_status": "none", "chunks": [], "error": "query is required"}
    else:
        result = retrieve(query, top_k_vector=8, top_k_bm25=8, top_n=8)
        result["intent"] = str(arguments.get("intent") or "answer")
    return json.dumps(result, ensure_ascii=False, indent=2)


TOOL_REGISTRY = {"retrieve_docs": retrieve_docs}
