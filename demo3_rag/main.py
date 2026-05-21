"""CLI entrypoint for Demo 3 RAG agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .env import load_repo_env
from .runner import run_session, write_trace
from .scenarios import SCENARIOS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Demo 3 Hermes-native RAG document QA.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="Run one built-in eval scenario.")
    parser.add_argument("--input", dest="manual_input", help="Ask one manual question.")
    parser.add_argument("--tool-temperature", type=float, default=0.3)
    parser.add_argument("--answer-temperature", type=float, default=0.6)
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--trace-file", help="Optional explicit trace output path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_repo_env()
    args = parse_args(argv)
    if args.manual_input:
        question = args.manual_input
        scenario_id = "manual"
    elif args.scenario:
        scenario = SCENARIOS[args.scenario]
        question = scenario["question"]
        scenario_id = args.scenario
    else:
        raise SystemExit("Use --scenario or --input.")

    trace = run_session(
        question,
        scenario_id=scenario_id,
        tool_temperature=args.tool_temperature,
        answer_temperature=args.answer_temperature,
        max_steps=args.max_steps,
    )
    trace_path = write_trace(trace, Path(args.trace_file) if args.trace_file else None)
    print(trace.get("final_answer", ""))
    print(f"\nTrace written to: {trace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
