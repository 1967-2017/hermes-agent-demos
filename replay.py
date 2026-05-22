"""Replay Demo 4 blackboard messages by topic."""

from __future__ import annotations

import argparse
import json
import sys

from demo4_blackboard.blackboard import find_run_by_topic, read_blackboard


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a Demo 4 multi-agent blackboard timeline.")
    parser.add_argument("--topic", required=True, help="Topic used when running demo4.")
    parser.add_argument("--json", action="store_true", help="Print raw JSONL records as JSON array.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = find_run_by_topic(args.topic)
    records = read_blackboard(path)
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    print(f"Replay topic: {args.topic}")
    print(f"Blackboard: {path}")
    print("")
    for record in records:
        print(f"[{record.get('ts', 'no-ts')}] round={record['round']} {record['from']} -> {record['to']} type={record['type']}")
        print(_summarize_content(record.get("content") or {}))
        print("")
    return 0


def _summarize_content(content: dict) -> str:
    if "review" in content and isinstance(content["review"], str):
        text = content["review"]
        return text[:1200] + ("..." if len(text) > 1200 else "")
    if "review" in content and isinstance(content["review"], dict):
        return json.dumps(content["review"], ensure_ascii=False, indent=2)
    if "notes" in content:
        notes = content["notes"]
        return json.dumps(notes, ensure_ascii=False, indent=2)[:1600]
    return json.dumps(content, ensure_ascii=False, indent=2)[:1600]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

