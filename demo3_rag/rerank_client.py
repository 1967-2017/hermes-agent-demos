"""DashScope rerank client for Demo 3."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .env import get_dashscope_api_key, get_dashscope_base_url


def rerank(query: str, documents: list[dict[str, Any]], *, top_n: int = 8) -> list[dict[str, Any]]:
    """Rerank documents with the DashScope text-rerank endpoint.

    If DashScope credentials are not configured, the input order is preserved
    with existing retrieval scores.
    """

    base_url = get_dashscope_base_url()
    api_key = get_dashscope_api_key()
    model = (os.getenv("DEMO3_RERANK_MODEL") or "qwen3-vl-rerank").strip()
    if not base_url or not api_key:
        return documents[:top_n]

    url = f"{base_url}/services/rerank/text-rerank/text-rerank"
    payload = {
        "model": model,
        "input": {
            "query": query,
            "documents": [item["content"] for item in documents],
        },
        "parameters": {
            "top_n": min(top_n, len(documents)),
            "return_documents": False,
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError):
        return documents[:top_n]

    try:
        parsed = json.loads(raw)
        output = parsed.get("output") or {}
        results = output.get("results", []) or parsed.get("results", [])
        ranked: list[dict[str, Any]] = []
        for result in results:
            index = int(result.get("index"))
            item = dict(documents[index])
            item["rerank_score"] = float(result.get("relevance_score", result.get("score", 0.0)))
            ranked.append(item)
        if ranked:
            return ranked[:top_n]
    except Exception:
        return documents[:top_n]
    return documents[:top_n]
