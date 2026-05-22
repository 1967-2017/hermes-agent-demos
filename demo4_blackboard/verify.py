"""Verification for Demo 4 scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_native.artifacts import write_markdown

from .blackboard import REQUIRED_FIELDS, read_blackboard
from .runner import run_session
from .scenarios import SCENARIOS

REPORT_PATH = Path(__file__).resolve().parent / "VALIDATION_REPORT.md"


def evaluate_blackboard(path: Path) -> tuple[bool, list[str]]:
    records = read_blackboard(path)
    issues: list[str] = []
    if not records:
        issues.append("blackboard is empty")
    for index, record in enumerate(records, start=1):
        missing = REQUIRED_FIELDS - set(record)
        if missing:
            issues.append(f"record {index} missing {sorted(missing)}")
    research_notes = [item for item in records if item.get("type") == "research_notes"]
    critic_reviews = [item for item in records if item.get("type") == "review_feedback"]
    final_reviews = [item for item in records if item.get("type") == "final_review"]
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
    if not _researcher_used_tool(records, "search_arxiv"):
        issues.append("researcher did not call search_arxiv")
    return not issues, issues


def run_and_evaluate(scenario_id: str) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_id]
    summary = run_session(scenario["topic"], session_id=scenario_id)
    passed, issues = evaluate_blackboard(Path(summary["blackboard_path"]))
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


def _researcher_used_tool(records: list[dict[str, Any]], tool_name: str) -> bool:
    for record in records:
        if record.get("type") != "research_notes":
            continue
        for step in record.get("content", {}).get("tool_trace", []):
            for call in step.get("tool_calls", []):
                if call.get("name") == tool_name:
                    return True
    return False


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

