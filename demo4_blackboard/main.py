"""CLI entrypoint for Demo 4."""

from __future__ import annotations

import argparse
import json
import sys

from .env import load_repo_env
from .runner import run_session
from .scenarios import SCENARIOS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Demo 4 multi-agent arXiv review over a shared blackboard.")
    parser.add_argument("--topic", help="Review topic to research.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="Run a built-in validation scenario.")
    parser.add_argument("--session-id", help="Optional stable run id for the blackboard directory.")
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_repo_env()
    args = parse_args(argv)
    if args.scenario:
        topic = SCENARIOS[args.scenario]["topic"]
        session_id = args.session_id or args.scenario
    elif args.topic:
        topic = args.topic
        session_id = args.session_id
    else:
        raise SystemExit("Use --topic or --scenario.")
    summary = run_session(topic, session_id=session_id, max_rounds=args.max_rounds, timeout_seconds=args.timeout_seconds)
    print(summary["final_review"])
    print("\nRun summary:")
    print(json.dumps({k: v for k, v in summary.items() if k != "final_review"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

