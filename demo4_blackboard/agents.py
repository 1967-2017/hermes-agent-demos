"""Agent execution helpers for Demo 4."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from hermes_native.chatml import build_tool_result, make_message
from hermes_native.client import DemoConfig, create_chat_completion
from hermes_native.parser import extract_tool_calls

from .blackboard import Blackboard
from .env import get_viewer_logs_enabled
from .prompts import critic_system_prompt, researcher_system_prompt, writer_system_prompt
from .tools import ArxivToolAdapter


@dataclass
class _SyntheticToolCall:
    name: str
    arguments: dict[str, Any]


def _has_tool_results(trace_steps: list[dict[str, Any]]) -> bool:
    return any(step.get("tool_results") for step in trace_steps)


def _has_tool_call(trace_steps: list[dict[str, Any]], tool_name: str) -> bool:
    return any(
        call.get("name") == tool_name
        for step in trace_steps
        for call in step.get("tool_calls", [])
    )


def _mandatory_search_message(topic: str) -> str:
    return (
        "You cannot submit research_notes before using tools. "
        "You must call search_arxiv first and must output exactly one valid <tool_call> block with no notes. "
        f"Use a focused query for this topic: {topic}."
    )


def _append_viewer(blackboard: Blackboard, sender: str, round_number: int, message_type: str, content: dict[str, Any]) -> None:
    if not get_viewer_logs_enabled():
        return
    blackboard.append(sender, "viewer", round_number, message_type, content)


def run_researcher(
    blackboard: Blackboard,
    topic: str,
    round_number: int,
    tools: ArxivToolAdapter,
    *,
    feedback: dict[str, Any] | None = None,
    max_steps: int = 8,
) -> dict[str, Any]:
    _append_viewer(
        blackboard,
        "researcher",
        round_number,
        "agent_status",
        {"agent": "researcher", "status": "running", "action": "Collecting paper evidence"},
    )
    config = DemoConfig.from_env(temperature=0.3, max_tokens=1800)
    messages = [
        make_message("system", researcher_system_prompt()),
        make_message("user", _researcher_task(topic, blackboard.read(), feedback)),
    ]
    trace_steps: list[dict[str, Any]] = []
    repeated: dict[str, int] = {}
    final_text = ""
    missing_tool_retries = 0
    for step_index in range(max_steps):
        text, raw = create_chat_completion(config, messages)
        messages.append(make_message("assistant", text))
        step: dict[str, Any] = {"assistant_text": text, "tool_calls": [], "tool_results": [], "raw_response": raw}
        tool_calls = extract_tool_calls(text)
        if not tool_calls:
            if not _has_tool_call(trace_steps, "search_arxiv"):
                missing_tool_retries += 1
                if missing_tool_retries <= 1:
                    step["missing_required_search"] = True
                    messages.append(make_message("user", _mandatory_search_message(topic)))
                    trace_steps.append(step)
                    continue
                tool_calls = [
                    _SyntheticToolCall(
                        "search_arxiv",
                        {"query": topic, "max_results": 6},
                    )
                ]
                step["synthetic_tool_call"] = True
                step["synthetic_reason"] = "model skipped mandatory first search_arxiv call"
            elif not _has_tool_results(trace_steps):
                step["missing_required_tool_result"] = True
                messages.append(make_message("user", _mandatory_search_message(topic)))
                trace_steps.append(step)
                continue
            else:
                final_text = text.strip()
                trace_steps.append(step)
                break
        for tool_call in tool_calls:
            repeat_key = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)}"
            repeated[repeat_key] = repeated.get(repeat_key, 0) + 1
            if repeated[repeat_key] > 2:
                raise RuntimeError(f"Repeated identical researcher tool call: {repeat_key}")
            call_content = {
                "agent": "researcher",
                "tool": tool_call.name,
                "arguments": tool_call.arguments,
                "step": step_index + 1,
            }
            if step.get("synthetic_tool_call"):
                call_content["synthetic"] = True
                call_content["reason"] = step.get("synthetic_reason", "")
            _append_viewer(blackboard, "researcher", round_number, "tool_call", call_content)
            try:
                result = tools.call(tool_call.name, tool_call.arguments)
                result_payload = json.loads(result)
            except Exception as exc:
                result_payload = {
                    "ok": False,
                    "tool": tool_call.name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                result = json.dumps(result_payload, ensure_ascii=False)
            _append_viewer(
                blackboard,
                "researcher",
                round_number,
                "tool_result",
                {
                    "agent": "researcher",
                    "tool": tool_call.name,
                    "summary": _summarize_tool_result(result_payload),
                    "ok": result_payload.get("ok"),
                    "step": step_index + 1,
                },
            )
            step["tool_calls"].append({"name": tool_call.name, "arguments": tool_call.arguments})
            step["tool_results"].append(result_payload)
            messages.append(make_message("user", build_tool_result(tool_call.name, result)))
        trace_steps.append(step)
    else:
        raise RuntimeError("Researcher exceeded maximum tool loop steps")

    notes = _parse_json_object(final_text, fallback_key="notes")
    evidence_count = sum(
        1
        for step in trace_steps
        for result in step.get("tool_results", [])
        if result.get("ok") is not False
    )
    record = blackboard.append(
        "researcher",
        "critic",
        round_number,
        "research_notes",
        {"notes": notes, "tool_trace": trace_steps, "evidence_count": evidence_count},
    )
    _append_viewer(
        blackboard,
        "researcher",
        round_number,
        "agent_status",
        {"agent": "researcher", "status": "done", "action": f"Submitted research notes with {evidence_count} evidence items"},
    )
    return record


def run_critic(blackboard: Blackboard, topic: str, round_number: int) -> dict[str, Any]:
    _append_viewer(
        blackboard,
        "critic",
        round_number,
        "agent_status",
        {"agent": "critic", "status": "running", "action": "Reviewing research notes"},
    )
    config = DemoConfig.from_env(temperature=0.3, max_tokens=1400)
    messages = [
        make_message("system", critic_system_prompt()),
        make_message("user", json.dumps({"topic": topic, "blackboard": blackboard.read()}, ensure_ascii=False, indent=2)),
    ]
    text, raw = create_chat_completion(config, messages)
    feedback = _parse_json_object(text, fallback_key="feedback")
    if "approve" not in feedback:
        feedback["approve"] = False
        feedback.setdefault("required_changes", []).append("Critic output omitted approve; treating as not approved.")
    feedback["approve"] = bool(feedback.get("approve"))
    record = blackboard.append(
        "critic",
        "researcher" if not feedback["approve"] else "writer",
        round_number,
        "review_feedback",
        {"review": feedback, "raw_response": raw},
    )
    _append_viewer(
        blackboard,
        "critic",
        round_number,
        "agent_status",
        {"agent": "critic", "status": "done", "action": "Approved notes" if feedback["approve"] else "Requested revisions"},
    )
    return record


def run_writer(blackboard: Blackboard, topic: str, round_number: int, *, consensus: bool) -> dict[str, Any]:
    _append_viewer(
        blackboard,
        "writer",
        round_number,
        "agent_status",
        {"agent": "writer", "status": "running", "action": "Writing final review"},
    )
    config = DemoConfig.from_env(temperature=0.7, max_tokens=3200)
    messages = [
        make_message("system", writer_system_prompt()),
        make_message(
            "user",
            json.dumps(
                {
                    "topic": topic,
                    "consensus": consensus,
                    "length_target": "1800-2200 Chinese characters",
                    "blackboard": blackboard.read(),
                },
                ensure_ascii=False,
                indent=2,
            ),
        ),
    ]
    text, raw = create_chat_completion(config, messages)
    final_review = text.strip()
    if not consensus and not final_review.startswith("未达共识"):
        final_review = "未达共识\n\n" + final_review
    record = blackboard.append(
        "writer",
        "user",
        round_number,
        "final_review",
        {"review": final_review, "consensus": consensus, "raw_response": raw},
    )
    _append_viewer(
        blackboard,
        "writer",
        round_number,
        "agent_status",
        {"agent": "writer", "status": "done", "action": "Published final review"},
    )
    return record


def latest_feedback(blackboard: Blackboard) -> dict[str, Any] | None:
    for record in reversed(blackboard.read()):
        if record.get("type") == "review_feedback":
            return deepcopy(record.get("content", {}).get("review") or {})
    return None


def approval_streak(blackboard: Blackboard) -> int:
    streak = 0
    for record in reversed(blackboard.read()):
        if record.get("type") != "review_feedback":
            continue
        review = record.get("content", {}).get("review") or {}
        if review.get("approve") is True:
            streak += 1
        else:
            break
    return streak


def _summarize_tool_result(payload: dict[str, Any]) -> str:
    tool = str(payload.get("tool") or "")
    if tool == "search_arxiv":
        query = str(payload.get("query") or "").strip()
        return f"Search results for {query}" if query else "Search completed"
    if tool == "fetch_pdf":
        paper_id = str(payload.get("paper_id") or "").strip()
        return f"Cached paper {paper_id}" if paper_id else "Paper cached"
    if tool == "extract_sections":
        paper_id = str(payload.get("paper_id") or "").strip()
        sections = payload.get("sections") or {}
        title_hint = str(sections.get("title_hint") or "").strip()
        prefix = f"Read paper {paper_id}" if paper_id else "Paper read"
        return f"{prefix}: {title_hint[:120]}" if title_hint else prefix
    text = str(payload.get("text") or "").strip()
    return text[:160] if text else "Tool completed"

def _researcher_task(topic: str, history: list[dict[str, Any]], feedback: dict[str, Any] | None) -> str:
    return json.dumps(
        {
            "topic": topic,
            "instruction": "Collect or revise structured research notes. Use tools for all paper evidence.",
            "critic_feedback": feedback,
            "blackboard_history": history,
        },
        ensure_ascii=False,
        indent=2,
    )


def _parse_json_object(text: str, *, fallback_key: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {fallback_key: stripped}

