"""Shared JSONL blackboard for Demo 4 agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_native.artifacts import append_jsonl, ensure_dir

DATA_DIR = Path(__file__).resolve().parent / "data"
RUNS_DIR = DATA_DIR / "runs"

REQUIRED_FIELDS = {"from", "to", "round", "type", "content"}


@dataclass(frozen=True)
class Blackboard:
    topic: str
    session_id: str
    path: Path

    @classmethod
    def create(cls, topic: str, session_id: str | None = None, *, reset: bool = False) -> "Blackboard":
        safe_session = session_id or slugify_topic(topic)
        path = RUNS_DIR / safe_session / "blackboard.jsonl"
        ensure_dir(path.parent)
        if reset or not path.exists():
            path.write_text("", encoding="utf-8")
        return cls(topic=topic, session_id=safe_session, path=path)

    def append(self, sender: str, recipient: str, round_number: int, message_type: str, content: dict[str, Any]) -> dict[str, Any]:
        record = {
            "from": sender,
            "to": recipient,
            "round": round_number,
            "type": message_type,
            "content": content,
            "ts": datetime.now(UTC).isoformat(),
            "session_id": self.session_id,
            "topic": self.topic,
        }
        validate_record(record)
        append_jsonl(self.path, record)
        return record

    def read(self) -> list[dict[str, Any]]:
        return read_blackboard(self.path)


def slugify_topic(topic: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in topic.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:80] or "adhoc"


def validate_record(record: dict[str, Any]) -> None:
    missing = REQUIRED_FIELDS - set(record)
    if missing:
        raise ValueError(f"Blackboard record missing fields: {sorted(missing)}")
    if not isinstance(record["from"], str) or not isinstance(record["to"], str):
        raise ValueError("Blackboard from/to must be strings")
    if not isinstance(record["round"], int) or record["round"] < 0:
        raise ValueError("Blackboard round must be a non-negative integer")
    if not isinstance(record["type"], str) or not record["type"]:
        raise ValueError("Blackboard type must be a non-empty string")
    if not isinstance(record["content"], dict):
        raise ValueError("Blackboard content must be an object")


def read_blackboard(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        validate_record(record)
        records.append(record)
    return records


def find_run_by_topic(topic: str) -> Path:
    preferred = RUNS_DIR / slugify_topic(topic) / "blackboard.jsonl"
    if preferred.exists():
        return preferred
    for path in sorted(RUNS_DIR.glob("*/blackboard.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            records = read_blackboard(path)
        except ValueError:
            continue
        if records and records[0].get("topic") == topic:
            return path
    raise FileNotFoundError(f"No demo4 blackboard found for topic: {topic}")
