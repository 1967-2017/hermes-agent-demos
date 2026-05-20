"""CLI entrypoint for demo2 travel agent."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .runner import TravelAgentRunner, write_trace_json, write_trace_markdown
from .scenarios import SCENARIOS
from .tools import ToolContext


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Demo 2 travel planner with Hermes-native Plan-Execute.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="Run one built-in validation scenario.")
    parser.add_argument("--input", dest="manual_input", help="Run one manual user request.")
    parser.add_argument("--interactive", action="store_true", help="Start an interactive session.")
    parser.add_argument("--planner-temperature", type=float, default=0.7)
    parser.add_argument("--executor-temperature", type=float, default=0.3)
    parser.add_argument("--max-iterations", type=int, default=14)
    return parser.parse_args(argv)


def _interactive_inputs(first_input: str | None = None) -> list[str]:
    inputs: list[str] = []
    if first_input:
        inputs.append(first_input)
    while not inputs:
        value = input("Travel request: ").strip()
        if value:
            inputs.append(value)
    return inputs


def _latest_session_id(trace: dict[str, Any]) -> str | None:
    for snapshot in reversed(trace.get("state_snapshots", [])):
        session_id = snapshot.get("session_id")
        if session_id:
            return str(session_id)
    return None


def _merge_interactive_trace(base: dict[str, Any], addition: dict[str, Any], *, user_reply: str | None = None) -> dict[str, Any]:
    merged = deepcopy(base)
    if user_reply:
        merged.setdefault("events", []).append({"type": "user_reply", "content": user_reply})

    merged.setdefault("events", []).extend(deepcopy(addition.get("events", [])))
    merged.setdefault("state_snapshots", []).extend(deepcopy(addition.get("state_snapshots", [])))

    for key in (
        "timestamp",
        "planner_model",
        "executor_model",
        "planner_temperature",
        "executor_temperature",
        "final_answer",
        "awaiting_user_input",
        "latest_question",
    ):
        if key in addition:
            merged[key] = addition[key]
        elif key in merged and key in {"latest_question"}:
            merged.pop(key, None)

    merged["interactive_trace_combined"] = True
    merged["updated_at"] = datetime.now(UTC).isoformat()
    return merged


def _write_trace_outputs(trace: dict[str, Any]) -> tuple[object, object]:
    trace_path = write_trace_json(trace)
    md_path = write_trace_markdown([trace])
    return trace_path, md_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenario_id = None
    fault_injections: dict[str, int] = {}

    if args.scenario:
        scenario = SCENARIOS[args.scenario]
        user_inputs = list(scenario["inputs"])
        scenario_id = args.scenario
        fault_injections = dict(scenario.get("fault_injections", {}))
    elif args.manual_input:
        user_inputs = _interactive_inputs(args.manual_input) if args.interactive else [args.manual_input]
    elif args.interactive:
        user_inputs = _interactive_inputs()
    else:
        raise SystemExit("Use --scenario, --input, or --interactive.")

    runner = TravelAgentRunner(
        planner_temperature=args.planner_temperature,
        executor_temperature=args.executor_temperature,
        max_iterations=args.max_iterations,
        tool_context=ToolContext(fault_injections=fault_injections),
    )
    trace = runner.run(user_inputs, scenario_id=scenario_id)
    session_trace = trace
    session_id = _latest_session_id(trace)

    if args.interactive:
        _write_trace_outputs(session_trace)

    while args.interactive and trace.get("awaiting_user_input"):
        question = trace.get("latest_question", "请补充信息：")
        reply = input(f"{question}\n> ").strip()
        if not reply:
            break
        user_inputs.append(reply)
        trace = runner.run(user_inputs, scenario_id=scenario_id, prefilled_replies=True, session_id=session_id)
        session_trace = _merge_interactive_trace(session_trace, trace, user_reply=reply)
        _write_trace_outputs(session_trace)

    if args.interactive:
        trace = session_trace
        trace_path, md_path = _write_trace_outputs(trace)
    else:
        trace_path, md_path = _write_trace_outputs(trace)

    if trace.get("final_answer"):
        print(trace["final_answer"])
    elif trace.get("awaiting_user_input"):
        print(trace.get("latest_question", "Planner is waiting for user input."))
    print(f"\nTrace JSON written to: {trace_path}")
    print(f"Trace Markdown written to: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
