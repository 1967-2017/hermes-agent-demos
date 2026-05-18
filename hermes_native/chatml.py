"""ChatML and Hermes-native tool protocol helpers."""

from __future__ import annotations

import json


def build_tools_block(tool_schemas: list[dict]) -> str:
    payload = json.dumps(tool_schemas, ensure_ascii=False, indent=2)
    return f"<tools>\n{payload}\n</tools>"


def build_tool_result(name: str, result: str) -> str:
    return f'<tool_result name="{name}">\n{result}\n</tool_result>'


def make_message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}

