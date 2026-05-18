"""Parsers for Hermes-native <tool_call> blocks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict
    raw_json: str


def extract_tool_calls(text: str) -> list[ParsedToolCall]:
    calls: list[ParsedToolCall] = []
    for match in TOOL_CALL_RE.finditer(text or ""):
        raw_json = match.group(1).strip()
        payload = json.loads(raw_json)
        name = str(payload.get("name", "")).strip()
        arguments = payload.get("arguments") or {}
        if not name or not isinstance(arguments, dict):
            raise ValueError(f"Invalid tool call payload: {raw_json}")
        calls.append(ParsedToolCall(name=name, arguments=arguments, raw_json=raw_json))
    return calls


def strip_tool_calls(text: str) -> str:
    return TOOL_CALL_RE.sub("", text or "").strip()

