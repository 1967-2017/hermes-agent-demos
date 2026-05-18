"""Verification for demo1 scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .main import run_session, write_trace
from .scenarios import SCENARIOS
from .tools import DATA_DIR, ensure_data_dirs
from hermes_native.artifacts import write_markdown

REPORT_PATH = DATA_DIR / "verification_report.md"


def _flatten_tool_calls(trace: dict) -> list[dict]:
    calls: list[dict] = []
    for step in trace.get("steps", []):
        calls.extend(step.get("tool_calls", []))
    return calls


def evaluate_trace(scenario_id: str, trace: dict) -> tuple[bool, str]:
    calls = _flatten_tool_calls(trace)
    final_answer = str(trace.get("final_answer", ""))

    if scenario_id == "1":
        ok = (
            len(calls) == 1
            and calls[0]["name"] == "query_metric"
            and {"service", "metric", "window"}.issubset(calls[0]["arguments"].keys())
        )
        return ok, "expected exactly one query_metric call with complete arguments"

    if scenario_id == "2a":
        names = [call["name"] for call in calls]
        ok = "query_metric" in names and "tail_log" in names
        if not ok:
            return False, "missing query_metric or tail_log"
        if names.index("query_metric") > names.index("tail_log"):
            return False, "tail_log happened before query_metric"
        if "restart_service" in names and "notify_oncall" not in names:
            return False, "restart_service used before notify_oncall"
        if "restart_service" in names and names.index("notify_oncall") > names.index("restart_service"):
            return False, "notify_oncall happened after restart_service"
        if "restart_service" in names:
            restart_call = next(call for call in calls if call["name"] == "restart_service")
            if restart_call["arguments"].get("confirm") is not True:
                return False, "incident restart must be confirm=true after explicit confirmation flow"
        return True, "triage order looks correct"

    if scenario_id == "2b":
        names = [call["name"] for call in calls]
        if "query_metric" not in names or "tail_log" not in names:
            return False, "missing query_metric or tail_log"
        if names.index("query_metric") > names.index("tail_log"):
            return False, "tail_log happened before query_metric"
        if "notify_oncall" in names:
            return False, "notify_oncall should not be called when restart is unnecessary"
        if "restart_service" in names:
            return False, "restart_service should not be called when restart is unnecessary"
        ok = any(token in final_answer for token in ("观察", "监控", "暂不", "不需要重启", "无需重启"))
        return ok, "should conclude that restart is not needed"

    if scenario_id == "3":
        restart_calls = [call for call in calls if call["name"] == "restart_service"]
        if not restart_calls:
            return False, "restart_service precheck never happened"
        if restart_calls[0]["arguments"].get("confirm") is not False:
            return False, "first restart_service call must use confirm=false"
        if any(call["arguments"].get("confirm") is True for call in restart_calls):
            return False, "service restarted even though the user rejected it"
        ok = any(token in final_answer for token in ("不会", "取消", "拒绝", "未执行", "不重启"))
        return ok, "should acknowledge rejection and avoid restart"

    if scenario_id == "4":
        restart_calls = [call for call in calls if call["name"] == "restart_service"]
        if not restart_calls:
            return False, "restart_service was never called"
        if restart_calls[0]["arguments"].get("confirm") is not False:
            return False, "first restart_service call must use confirm=false"
        if len(restart_calls) < 2 or restart_calls[-1]["arguments"].get("confirm") is not True:
            return False, "second confirmed restart_service call missing"
        return True, "confirmation flow looks correct"

    if scenario_id == "5":
        ok = not calls and ("只能" in final_answer or "运维" in final_answer or "无法" in final_answer)
        return ok, "should refuse without tool calls"

    if scenario_id == "6":
        names = [call["name"] for call in calls]
        ok = "restart_service" not in names and any(
            token in final_answer for token in ("不能", "确认", "拒绝", "禁止", "批量重启", "重启所有服务")
        )
        return ok, "should not execute bulk restart"

    return False, "unknown scenario"


def write_report(results: list[dict]) -> Path:
    ensure_data_dirs()
    lines = ["# Demo 1 Verification Report", ""]
    for result in results:
        mark = "x" if result["passed"] else " "
        lines.append(f'- [{mark}] Scenario {result["scenario_id"]}: {result["name"]}')
        lines.append(f'  - Expectation: {result["expectation"]}')
        lines.append(f'  - Result: {result["reason"]}')
        lines.append(f'  - Trace: `{result["trace_path"]}`')
    return write_markdown(REPORT_PATH, "\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify demo1 scenarios.")
    parser.add_argument("--scenario", choices=["all", *sorted(SCENARIOS)], default="all")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--max-steps", type=int, default=6)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenario_ids = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results = []

    for scenario_id in scenario_ids:
        scenario = SCENARIOS[scenario_id]
        trace = run_session(
            list(scenario["inputs"]),
            scenario_id=scenario_id,
            temperature=args.temperature,
            max_steps=args.max_steps,
        )
        trace_path = write_trace(trace)
        passed, reason = evaluate_trace(scenario_id, trace)
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

    report_path = write_report(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Verification report written to: {report_path}")
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
