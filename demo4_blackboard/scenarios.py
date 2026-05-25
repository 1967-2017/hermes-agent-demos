"""Validation scenarios for Demo 4."""

from __future__ import annotations

SCENARIOS: dict[str, dict] = {
    "long_context": {
        "name": "长上下文主流方案",
        "topic": "mainstream approaches for LLM long-context processing",
        "checks": [
            "researcher_used_search",
            "has_references",
            "references_from_tool_results",
            "has_final_review",
        ],
    },
    "multimodal_rag_2024": {
        "name": "2024 后 multimodal RAG 进展",
        "topic": "multimodal RAG advances after 2024",
        "checks": [
            "researcher_used_search",
            "references_from_tool_results",
            "no_unsupported_paper_claims",
            "has_final_review",
        ],
    },
    "fake_citation": {
        "name": "虚假引用检测",
        "topic": "fake citation detection in scientific review notes",
        "checks": [
            "critic_reviewed_citations",
            "critic_detected_fake_citation",
        ],
        "inject_fake_citation": True,
    },
    "rare_topic": {
        "name": "冷门主题优雅降级",
        "topic": "LLM processing of Uzbek morphology",
        "checks": [
            "researcher_used_search",
            "graceful_insufficient_evidence",
            "no_fake_references",
        ],
    },
}

