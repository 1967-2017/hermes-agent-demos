"""Verification for Demo 4 scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_native.artifacts import write_markdown

from .blackboard import REQUIRED_FIELDS, read_blackboard
from .runner import run_fake_citation_session, run_session
from .scenarios import SCENARIOS

REPORT_PATH = Path(__file__).resolve().parent / "VALIDATION_REPORT.md"


def evaluate_blackboard(path: Path, scenario: dict[str, Any]) -> tuple[bool, list[str]]:
    records = read_blackboard(path)
    issues = _generic_blackboard_issues(records)
    for check_name in scenario.get("checks", []):
        checker = CHECKS.get(check_name)
        if checker is None:
            issues.append(f"unknown check: {check_name}")
            continue
        issue = checker(records)
        if issue:
            issues.append(issue)
    return not issues, issues


def _generic_blackboard_issues(records: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if not records:
        issues.append("blackboard is empty")
    for index, record in enumerate(records, start=1):
        missing = REQUIRED_FIELDS - set(record)
        if missing:
            issues.append(f"record {index} missing {sorted(missing)}")
    research_notes = _records_of_type(records, "research_notes")
    critic_reviews = _records_of_type(records, "review_feedback")
    final_reviews = _records_of_type(records, "final_review")
    if not research_notes:
        issues.append("missing research_notes")
    if not critic_reviews:
        issues.append("missing review_feedback")
    if not final_reviews:
        issues.append("missing final_review")
    for item in critic_reviews:
        review = item.get("content", {}).get("review") or {}
        if "approve" not in review:
            issues.append("critic review missing approve")
    if final_reviews:
        review_text = str(final_reviews[-1].get("content", {}).get("review") or "")
        consensus = bool(final_reviews[-1].get("content", {}).get("consensus"))
        if consensus and not (1500 <= len(review_text) <= 2600):
            issues.append("consensus final review is not close to 2000 Chinese characters")
        if not consensus and "未达共识" not in review_text:
            issues.append("non-consensus final review did not mark 未达共识")
    return issues


def run_and_evaluate(scenario_id: str) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_id]
    if scenario.get("inject_fake_citation"):
        summary = run_fake_citation_session(scenario["topic"], session_id=scenario_id)
    else:
        summary = run_session(scenario["topic"], session_id=scenario_id)
    passed, issues = evaluate_blackboard(Path(summary["blackboard_path"]), scenario)
    return {
        "scenario_id": scenario_id,
        "name": scenario["name"],
        "topic": scenario["topic"],
        "passed": passed,
        "issues": issues,
        "blackboard_path": summary["blackboard_path"],
        "consensus": summary["consensus"],
    }


def write_report(results: list[dict[str, Any]]) -> Path:
    lines = ["# Demo 4 Validation Report", ""]
    lines.append("Demo 4 verifies the multi-agent blackboard protocol, real tool-use trail, final review production, and graceful non-consensus handling.")
    lines.append("")
    for result in results:
        mark = "x" if result["passed"] else " "
        lines.append(f"- [{mark}] {result['scenario_id']}: {result['name']}")
        lines.append(f"  - Topic: {result['topic']}")
        lines.append(f"  - Consensus: {result['consensus']}")
        lines.append(f"  - Blackboard: `{result['blackboard_path']}`")
        if result["issues"]:
            lines.append(f"  - Issues: {'; '.join(result['issues'])}")
        else:
            lines.append("  - Issues: none")
    return write_markdown(REPORT_PATH, "\n".join(lines) + "\n")


def _records_of_type(records: list[dict[str, Any]], record_type: str) -> list[dict[str, Any]]:
    return [record for record in records if record.get("type") == record_type]


def _latest_research_notes(records: list[dict[str, Any]]) -> dict[str, Any]:
    notes_records = _records_of_type(records, "research_notes")
    if not notes_records:
        return {}
    notes = notes_records[-1].get("content", {}).get("notes") or {}
    return notes if isinstance(notes, dict) else {}


def _all_references(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for record in _records_of_type(records, "research_notes"):
        notes = record.get("content", {}).get("notes") or {}
        if not isinstance(notes, dict):
            continue
        for reference in notes.get("references") or []:
            if isinstance(reference, dict):
                references.append(reference)
    return references


def _tool_results(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for record in records:
        content = record.get("content", {})
        if record.get("type") == "tool_result" and isinstance(content, dict):
            results.append(content)
        if record.get("type") != "research_notes":
            continue
        for step in content.get("tool_trace", []):
            for result in step.get("tool_results", []):
                if isinstance(result, dict):
                    results.append(result)
    return results


def _tool_evidence_blob(records: list[dict[str, Any]]) -> str:
    return json.dumps(_tool_results(records), ensure_ascii=False, sort_keys=True)


def _reference_identity(reference: dict[str, Any]) -> str:
    return " ".join(
        str(reference.get(key) or "")
        for key in ("paper_id", "title", "authors", "year")
    ).strip()


def _researcher_used_tool(records: list[dict[str, Any]], tool_name: str) -> bool:
    for record in _records_of_type(records, "research_notes"):
        for step in record.get("content", {}).get("tool_trace", []):
            for call in step.get("tool_calls", []):
                if call.get("name") == tool_name:
                    return True
    return False


def _references_supported_by_tool_results(records: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    evidence_blob = _tool_evidence_blob(records)
    missing: list[str] = []
    for reference in _all_references(records):
        paper_id = str(reference.get("paper_id") or "").strip()
        title = str(reference.get("title") or "").strip()
        has_identity = bool(paper_id or title)
        id_supported = bool(paper_id and paper_id in evidence_blob)
        title_supported = bool(title and title in evidence_blob)
        if not has_identity or not (id_supported or title_supported):
            missing.append(_reference_identity(reference) or repr(reference))
    return not missing, missing


def _critic_feedback_blob(records: list[dict[str, Any]]) -> str:
    reviews = [record.get("content", {}).get("review") or {} for record in _records_of_type(records, "review_feedback")]
    return json.dumps(reviews, ensure_ascii=False).lower()


def _final_review_text(records: list[dict[str, Any]]) -> str:
    final_reviews = _records_of_type(records, "final_review")
    if not final_reviews:
        return ""
    return str(final_reviews[-1].get("content", {}).get("review") or "")


def _check_researcher_used_search(records: list[dict[str, Any]]) -> str | None:
    if not _researcher_used_tool(records, "search_arxiv"):
        return "researcher did not call search_arxiv"
    return None


def _check_has_references(records: list[dict[str, Any]]) -> str | None:
    if not _all_references(records):
        return "research notes did not include references"
    return None


def _check_references_from_tool_results(records: list[dict[str, Any]]) -> str | None:
    ok, missing = _references_supported_by_tool_results(records)
    if not ok:
        return "references not found in tool results: " + "; ".join(missing[:5])
    return None


def _check_has_final_review(records: list[dict[str, Any]]) -> str | None:
    if not _final_review_text(records).strip():
        return "missing final review text"
    return None


def _check_no_unsupported_paper_claims(records: list[dict[str, Any]]) -> str | None:
    ok, missing = _references_supported_by_tool_results(records)
    if not ok:
        return "unsupported paper claims or references: " + "; ".join(missing[:5])
    return None


def _check_critic_reviewed_citations(records: list[dict[str, Any]]) -> str | None:
    feedback = _critic_feedback_blob(records)
    if not any(token in feedback for token in ("citation", "引用", "paper", "论文", "unsupported", "fake", "不支持", "虚假")):
        return "critic feedback did not discuss citations"
    return None


def _check_critic_detected_fake_citation(records: list[dict[str, Any]]) -> str | None:
    feedback = _critic_feedback_blob(records)
    detected = any(
        token in feedback
        for token in ("unsupported", "fake", "not in evidence", "absent from", "citation not", "不支持", "虚假", "假引用", "未在证据")
    )
    if not detected:
        return "critic did not detect the injected fake citation"
    if '"approve": true' in feedback:
        return "critic approved notes containing an injected fake citation"
    return None


def _check_graceful_insufficient_evidence(records: list[dict[str, Any]]) -> str | None:
    notes = _latest_research_notes(records)
    combined = "\n".join(
        [
            str(notes.get("status") or ""),
            str(notes.get("notes") or ""),
            _final_review_text(records),
        ]
    )
    if not any(token in combined for token in ("insufficient_evidence", "资料不足", "证据不足", "insufficient evidence")):
        return "rare-topic scenario did not gracefully state insufficient evidence"
    return None


def _check_no_fake_references(records: list[dict[str, Any]]) -> str | None:
    references = _all_references(records)
    if not references:
        return None
    ok, missing = _references_supported_by_tool_results(records)
    if not ok:
        return "rare-topic scenario included references not found in tool evidence: " + "; ".join(missing[:5])
    return None


CHECKS = {
    "researcher_used_search": _check_researcher_used_search,
    "has_references": _check_has_references,
    "references_from_tool_results": _check_references_from_tool_results,
    "has_final_review": _check_has_final_review,
    "no_unsupported_paper_claims": _check_no_unsupported_paper_claims,
    "critic_reviewed_citations": _check_critic_reviewed_citations,
    "critic_detected_fake_citation": _check_critic_detected_fake_citation,
    "graceful_insufficient_evidence": _check_graceful_insufficient_evidence,
    "no_fake_references": _check_no_fake_references,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Demo 4 multi-agent blackboard scenarios.")
    parser.add_argument("--scenario", choices=["all", *sorted(SCENARIOS)], default="all")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenario_ids = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results = [run_and_evaluate(scenario_id) for scenario_id in scenario_ids]
    report_path = write_report(results)
    summary = {
        "passed": all(item["passed"] for item in results),
        "total": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "report_path": str(report_path),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

