"""Validation scenarios for Demo 4."""

from __future__ import annotations

SCENARIOS: dict[str, dict] = {
    "coverage": {
        "name": "方案覆盖",
        "topic": "retrieval augmented generation evaluation methods",
        "checks": ["has_final_review", "has_references", "has_research_notes"],
    },
    "real_search": {
        "name": "真实检索",
        "topic": "small language model tool use agents",
        "checks": ["researcher_used_search", "references_from_tool_results"],
    },
    "fake_citation": {
        "name": "虚假引用检测",
        "topic": "detecting hallucinated citations in scientific reviews",
        "checks": ["critic_reviewed_citations"],
    },
    "rare_topic": {
        "name": "冷门主题优雅降级",
        "topic": "thermodynamic ontology of invisible purple recipes in arxiv papers",
        "checks": ["graceful_insufficient_evidence"],
    },
}

