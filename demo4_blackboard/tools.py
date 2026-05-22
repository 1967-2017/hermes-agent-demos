"""Hermes-visible arXiv tools backed by the arxiv MCP server."""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from .mcp_client import StdioMcpClient
from .env import get_arxiv_user_agent, get_http_min_interval_seconds

TOOL_SCHEMAS = [
    {
        "name": "search_arxiv",
        "description": "Search arXiv for papers relevant to a review topic.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Focused arXiv search query."},
                "max_results": {"type": "integer", "description": "Maximum papers to return, usually 3-6."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_pdf",
        "description": "Download or cache a specific arXiv paper before reading it.",
        "parameters": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "arXiv paper id returned by search_arxiv."},
            },
            "required": ["paper_id"],
        },
    },
    {
        "name": "extract_sections",
        "description": "Read a downloaded paper and extract title, abstract, conclusion-like findings, and method notes.",
        "parameters": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "arXiv paper id to read."},
            },
            "required": ["paper_id"],
        },
    },
]


class ArxivToolAdapter:
    def __init__(self, mcp: StdioMcpClient) -> None:
        self.mcp = mcp
        self.evidence: list[dict[str, Any]] = []
        self.policy_interval_seconds = get_http_min_interval_seconds()
        self.user_agent = get_arxiv_user_agent()
        self._rate_lock = threading.Lock()
        self._last_http_request_at: float | None = None

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "search_arxiv":
            return self.search_arxiv(arguments)
        if name == "fetch_pdf":
            return self.fetch_pdf(arguments)
        if name == "extract_sections":
            return self.extract_sections(arguments)
        raise RuntimeError(f"Unknown demo4 tool requested: {name}")

    def search_arxiv(self, args: dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        wait_seconds = self._throttle_http_request()
        max_results = int(args.get("max_results") or 5)
        result = self.mcp.call_tool("search_papers", {"query": query, "max_results": max(1, min(max_results, 10))})
        payload = {
            "ok": True,
            "tool": "search_arxiv",
            "query": query,
            "mcp_tool": "search_papers",
            "throttled_wait_seconds": wait_seconds,
            "policy_interval_seconds": self.policy_interval_seconds,
            "user_agent": self.user_agent,
            "text": result.as_text(),
            "raw": result.raw,
        }
        self.evidence.append(payload)
        return json.dumps(payload, ensure_ascii=False)

    def fetch_pdf(self, args: dict[str, Any]) -> str:
        paper_id = str(args.get("paper_id") or "").strip()
        wait_seconds = self._throttle_http_request()
        result = self.mcp.call_tool("download_paper", {"paper_id": paper_id})
        payload = {
            "ok": True,
            "tool": "fetch_pdf",
            "paper_id": paper_id,
            "mcp_tool": "download_paper",
            "throttled_wait_seconds": wait_seconds,
            "policy_interval_seconds": self.policy_interval_seconds,
            "user_agent": self.user_agent,
            "text": result.as_text(),
            "raw": result.raw,
        }
        self.evidence.append(payload)
        return json.dumps(payload, ensure_ascii=False)

    def extract_sections(self, args: dict[str, Any]) -> str:
        paper_id = str(args.get("paper_id") or "").strip()
        result = self.mcp.call_tool("read_paper", {"paper_id": paper_id})
        text = result.as_text()
        payload = {
            "ok": True,
            "tool": "extract_sections",
            "paper_id": paper_id,
            "mcp_tool": "read_paper",
            "sections": extract_section_summary(text),
            "text": text[:12000],
            "raw": result.raw,
        }
        self.evidence.append(payload)
        return json.dumps(payload, ensure_ascii=False)

    def _throttle_http_request(self) -> float:
        with self._rate_lock:
            if self.policy_interval_seconds <= 0:
                self._last_http_request_at = time.monotonic()
                return 0.0
            wait_seconds = 0.0
            if self._last_http_request_at is not None:
                elapsed = time.monotonic() - self._last_http_request_at
                wait_seconds = max(0.0, self.policy_interval_seconds - elapsed)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_http_request_at = time.monotonic()
            return round(wait_seconds, 3)


def extract_section_summary(text: str) -> dict[str, str]:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return {
        "title_hint": compact[:300],
        "abstract_hint": _slice_after_heading(compact, "abstract", 1800),
        "method_hint": _slice_after_heading(compact, "method", 1800),
        "conclusion_hint": _slice_after_heading(compact, "conclusion", 1800),
    }


def _slice_after_heading(text: str, heading: str, limit: int) -> str:
    match = re.search(rf"\b{re.escape(heading)}\b", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return text[match.start() : match.start() + limit]

