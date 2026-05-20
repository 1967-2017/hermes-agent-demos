"""Verification for demo2 travel planning scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_native.artifacts import write_markdown

from .runner import TravelAgentRunner, write_trace_json, write_trace_markdown
from .scenarios import SCENARIOS
from .tools import DATA_DIR, ToolContext, ensure_data_dirs

REPORT_PATH = DATA_DIR / "verification_report.md"


def _events(trace: dict[str, Any], event_type: str) -> list[dict[str, Any]]:
    return [event for event in trace.get("events", []) if event.get("type") == event_type]


def _all_actions(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return _events(trace, "action")


def _initial_plan(trace: dict[str, Any]) -> list[dict[str, Any]]:
    for event in _events(trace, "plan"):
        plan = event.get("plan") or []
        if plan:
            return plan
    return []


def _has_replan(trace: dict[str, Any]) -> bool:
    plan_events = [event for event in _events(trace, "plan") if event.get("plan")]
    versions = {event.get("plan_version") for event in plan_events}
    return len(plan_events) >= 2 and (len(versions) >= 2 or any(event.get("change_reason") for event in plan_events[1:]))


def _duplicate_tool_args(trace: dict[str, Any]) -> bool:
    counts: dict[str, int] = {}
    for action in _all_actions(trace):
        key = f"{action.get('tool')}:{json.dumps(action.get('arguments', {}), sort_keys=True, ensure_ascii=False)}"
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > 2:
            return True
    return False


def _final_contains(final_answer: str, tokens: tuple[str, ...]) -> bool:
    return all(token in final_answer for token in tokens)


def evaluate_trace(scenario_id: str, trace: dict[str, Any]) -> tuple[bool, str]:
    actions = _all_actions(trace)
    tool_names = [str(action.get("tool")) for action in actions]
    final_answer = str(trace.get("final_answer") or "")

    if _duplicate_tool_args(trace):
        return False, "detected repeated identical tool calls"

    if scenario_id == "1":
        initial_plan = _initial_plan(trace)
        if len(initial_plan) < 5:
            return False, "initial plan must contain at least five steps"
        if "search_flights" not in tool_names:
            return False, "search_flights was not called"
        first_flight = next(action for action in actions if action.get("tool") == "search_flights")
        if "no_availability" not in str(first_flight.get("tool_result")):
            return False, "first flight search did not exercise the no-availability fault"
        if not _has_replan(trace):
            return False, "trace does not show a replan after no flights"
        if "search_hotels" not in tool_names or "get_weather" not in tool_names or "calc_budget" not in tool_names:
            return False, "missing hotel, weather, or budget tool coverage"
        if not _final_contains(final_answer, ("航班", "酒店", "天气", "预算")):
            return False, "final answer must mention flight, hotel, weather, and budget"
        return True, "replan after no flights produced a complete travel plan"

    if scenario_id == "2":
        first_user_gate = next((event for event in trace.get("events", []) if event.get("type") in {"user_input_required", "action"}), None)
        if not first_user_gate or first_user_gate.get("type") != "user_input_required":
            return False, "underspecified request should ask a question before tool use"
        if not actions:
            return False, "planner never started tool-backed planning after details were supplied"
        return True, "underspecified request asked for details before planning"

    if scenario_id == "3":
        if not any(tool in tool_names for tool in ("get_visa_info", "search_flights", "calc_budget")):
            return False, "unrealistic trip should check feasibility with tools"
        risk_tokens = ("不现实", "不可行", "降级", "替代", "南极")
        if not any(token in final_answer for token in risk_tokens):
            return False, "final answer should identify infeasibility and offer a downgrade or alternative"
        return True, "unrealistic Antarctica request produced a downgrade recommendation"

    return False, "unknown scenario"


def scan_for_hardcode() -> tuple[bool, str]:
    root = Path(__file__).resolve().parent
    banned_prompt_tokens = ["验证场景", "scenario 1", "无航班测试", "预期输出"]
    exact_inputs = ["2026年6月1日想去东京玩一周，预算1.5万", "随便玩玩", "明天就走，去南极"]
    runtime_files = [path for path in root.glob("*.py") if path.name not in {"scenarios.py", "verify.py"}]
    for path in runtime_files:
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in banned_prompt_tokens):
            return False, f"runtime file {path.name} mentions validation-only prompt tokens"
        if path.name not in {"main.py"} and any(exact_input in text for exact_input in exact_inputs):
            return False, f"runtime file {path.name} contains exact scenario input"
    return True, "no scenario-answer hardcoding pattern found in demo2 runtime files"


def write_report(results: list[dict[str, Any]]) -> Path:
    ensure_data_dirs()
    lines = ["# Demo 2 Verification Report", ""]
    for result in results:
        mark = "x" if result["passed"] else " "
        lines.append(f'- [{mark}] Scenario {result["scenario_id"]}: {result["name"]}')
        lines.append(f'  - Expectation: {result["expectation"]}')
        lines.append(f'  - Result: {result["reason"]}')
        lines.append(f'  - Trace: `{result["trace_path"]}`')
    return write_markdown(REPORT_PATH, "\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify demo2 travel planner scenarios.")
    parser.add_argument("--scenario", choices=["all", *sorted(SCENARIOS)], default="all")
    parser.add_argument("--planner-temperature", type=float, default=0.7)
    parser.add_argument("--executor-temperature", type=float, default=0.3)
    parser.add_argument("--max-iterations", type=int, default=14)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenario_ids = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    hardcode_ok, hardcode_reason = scan_for_hardcode()
    if not hardcode_ok:
        print(json.dumps([{"passed": False, "reason": hardcode_reason}], ensure_ascii=False, indent=2))
        return 1

    for scenario_id in scenario_ids:
        scenario = SCENARIOS[scenario_id]
        runner = TravelAgentRunner(
            planner_temperature=args.planner_temperature,
            executor_temperature=args.executor_temperature,
            max_iterations=args.max_iterations,
            tool_context=ToolContext(fault_injections=dict(scenario.get("fault_injections", {}))),
        )
        trace = runner.run(list(scenario["inputs"]), scenario_id=scenario_id)
        trace_path = write_trace_json(trace)
        passed, reason = evaluate_trace(scenario_id, trace)
        traces.append(trace)
        results.append(
            {
                "scenario_id": scenario_id,
                "name": scenario["name"],
                "expectation": scenario["expectation"],
                "passed": passed,
                "reason": reason,
                "trace_path": str(trace_path),
            }
        )

    trace_md = write_trace_markdown(traces)
    report_path = write_report(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Trace markdown written to: {trace_md}")
    print(f"Verification report written to: {report_path}")
    print(f"Hardcode scan: {hardcode_reason}")
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
