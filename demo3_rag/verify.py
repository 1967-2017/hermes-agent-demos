"""Verification for Demo 3 RAG scenarios."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from hermes_native.artifacts import write_markdown

from .runner import run_session, write_trace
from .scenarios import SCENARIOS
from .tools import REPORT_PATH, ensure_data_dirs

CITATION_RE = re.compile(r"\[([^:\[\]]+):((?:c)\d{3})\]")
QUESTION_BRANCH_RE = re.compile(r"\b(?:if|elif)\s+.*(?:user_input|question)\s*(?:==|in)", re.IGNORECASE)


def _flatten_tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for step in trace.get("steps", []):
        calls.extend(step.get("tool_calls", []))
    return calls


def _retrieved_keys(trace: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for step in trace.get("steps", []):
        for result in step.get("tool_results", []):
            content = result.get("content") or {}
            for chunk in content.get("chunks", []):
                keys.add(f"{chunk.get('doc_id')}:{chunk.get('chunk_id')}")
    return keys


def _retrieved_doc_ids(trace: dict[str, Any]) -> set[str]:
    doc_ids: set[str] = set()
    for step in trace.get("steps", []):
        for result in step.get("tool_results", []):
            content = result.get("content") or {}
            for chunk in content.get("chunks", []):
                if chunk.get("doc_id"):
                    doc_ids.add(str(chunk["doc_id"]))
    return doc_ids


def _citations(answer: str) -> list[str]:
    return [f"{doc_id}:{chunk_id}" for doc_id, chunk_id in CITATION_RE.findall(answer)]


def _max_two_citations_per_sentence(answer: str) -> bool:
    sentences = re.split(r"[。！？!?]\s*", answer)
    return all(len(CITATION_RE.findall(sentence)) <= 2 for sentence in sentences if sentence.strip())


def evaluate_trace(scenario: dict[str, Any], trace: dict[str, Any]) -> tuple[bool, str]:
    answer = str(trace.get("final_answer", ""))
    calls = _flatten_tool_calls(trace)
    citations = _citations(answer)
    retrieved_keys = _retrieved_keys(trace)
    retrieved_doc_ids = _retrieved_doc_ids(trace)
    expected_behavior = scenario["expected_behavior"]

    if not calls:
        if citations:
            return False, "model fabricated citations without retrieve_docs"
        if "未找到" in answer:
            return False, "model claimed 未找到 without retrieve_docs"
        return False, "model answered directly without retrieve_docs"
    if any(call.get("name") != "retrieve_docs" for call in calls):
        return False, "unexpected tool call"
    if not _max_two_citations_per_sentence(answer):
        return False, "a sentence has more than two citations"
    if any(citation not in retrieved_keys for citation in citations):
        return False, "answer cited chunks that were not retrieved"

    if expected_behavior == "not_found":
        if "未找到" not in answer:
            return False, "not_found scenario must say 未找到"
        return True, "correctly refused unsupported answer"

    if expected_behavior == "clarify":
        if "？" not in answer and "?" not in answer:
            return False, "ambiguous scenario should ask a clarifying question"
        return True, "asked for clarification"

    if not citations:
        return False, "answer scenario must include citations"
    for token in scenario.get("must_contain", []):
        if token not in answer:
            return False, f"answer missing expected token: {token}"
    expected_doc_ids = set(scenario.get("expected_doc_ids", []))
    if scenario["category"] == "single_doc":
        if expected_doc_ids and not (expected_doc_ids & retrieved_doc_ids):
            return False, "retrieval missed expected source document"
    if scenario["category"] == "multi_doc":
        cited_doc_ids = {citation.rsplit(":", 1)[0] for citation in citations}
        if len(cited_doc_ids) < 2:
            return False, "multi-doc answer must cite at least two documents"
        if expected_doc_ids and len(expected_doc_ids & retrieved_doc_ids) < 2:
            return False, "retrieval did not include at least two expected source documents"
    return True, "passed"


def scan_for_hardcoding() -> tuple[bool, str]:
    runtime_files = [
        Path(__file__).resolve().parent / name
        for name in ("main.py", "runner.py", "tools.py", "retrieval.py", "prompts.py")
    ]
    for path in runtime_files:
        text = path.read_text(encoding="utf-8")
        if QUESTION_BRANCH_RE.search(text):
            return False, f"suspicious question-specific branch in {path.name}"
        for scenario in SCENARIOS.values():
            question = str(scenario.get("question") or "")
            if question and question in text:
                return False, f"scenario question text leaked into runtime file {path.name}"
    return True, "no question-specific hardcoding pattern found in runtime files"


def write_report(results: list[dict[str, Any]], hardcoding: tuple[bool, str]) -> Path:
    ensure_data_dirs()
    lines = ["# Demo 3 Verification Report", ""]
    mark = "x" if hardcoding[0] else " "
    lines.append(f"- [{mark}] Hardcoding scan: {hardcoding[1]}")
    lines.append("")
    for result in results:
        mark = "x" if result["passed"] else " "
        lines.append(f"- [{mark}] {result['scenario_id']}: {result['name']}")
        lines.append(f"  - Category: {result['category']}")
        lines.append(f"  - Result: {result['reason']}")
        lines.append(f"  - Trace: `{result['trace_path']}`")
    return write_markdown(REPORT_PATH, "\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Demo 3 RAG scenarios.")
    parser.add_argument("--scenario", choices=["all", *sorted(SCENARIOS)], default="all")
    parser.add_argument("--tool-temperature", type=float, default=0.3)
    parser.add_argument("--answer-temperature", type=float, default=0.6)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--hardcoding-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    hardcoding = scan_for_hardcoding()
    if args.hardcoding_only:
        print(json.dumps({"passed": hardcoding[0], "reason": hardcoding[1]}, ensure_ascii=False, indent=2))
        return 0 if hardcoding[0] else 1

    scenario_ids = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results: list[dict[str, Any]] = []
    for scenario_id in scenario_ids:
        scenario = SCENARIOS[scenario_id]
        trace = run_session(
            scenario["question"],
            scenario_id=scenario_id,
            tool_temperature=args.tool_temperature,
            answer_temperature=args.answer_temperature,
            max_steps=args.max_steps,
        )
        trace_path = write_trace(trace)
        passed, reason = evaluate_trace(scenario, trace)
        results.append(
            {
                "scenario_id": scenario_id,
                "name": scenario["name"],
                "category": scenario["category"],
                "passed": passed,
                "reason": reason,
                "trace_path": str(trace_path),
            }
        )

    report_path = write_report(results, hardcoding)
    summary = {
        "passed": all(item["passed"] for item in results) and hardcoding[0],
        "total": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "hardcoding": {"passed": hardcoding[0], "reason": hardcoding[1]},
        "report_path": str(report_path),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
