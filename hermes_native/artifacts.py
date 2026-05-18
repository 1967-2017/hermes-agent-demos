"""Artifact helpers shared by Hermes-native demos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_jsonl(path: Path, record: dict[str, Any]) -> Path:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def write_markdown(path: Path, content: str) -> Path:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    return path

