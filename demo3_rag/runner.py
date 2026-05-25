"""Hermes-native RAG runner for Demo 3."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from hermes_native.artifacts import write_json
from hermes_native.chatml import build_tool_result, make_message
from hermes_native.client import DemoConfig, create_chat_completion
from hermes_native.parser import extract_tool_calls

from .env import load_repo_env
from .prompts import build_system_prompt
from .tools import TOOL_REGISTRY, TRACE_DIR, ensure_data_dirs

CITATION_RE = re.compile(r"\[[^:\[\]]+:c\d{3}\]")
EventCallback = Callable[[str, dict[str, Any]], None]


def _emit(event_callback: EventCallback | None, event: str, payload: dict[str, Any]) -> None:
    if not event_callback:
        return
    try:
        event_callback(event, payload)
    except Exception:
        pass


def _parse_tool_result(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def _citation_limit_ok(text: str) -> bool:
    sentences = re.split(r"[。！？!?]\s*", text)
    return all(len(CITATION_RE.findall(sentence)) <= 2 for sentence in sentences if sentence.strip())


def _has_retrieved(trace: dict[str, Any]) -> bool:
    return any(
        call.get("name") == "retrieve_docs"
        for step in trace.get("steps", [])
        for call in step.get("tool_calls", [])
    )


def _missing_retrieve_message() -> str:
    return (
        "你还没有调用 retrieve_docs，不能直接回答。"
        "Demo 3 是 RAG 问答，任何菜谱事实、原料、用量、步骤、时间、工具、对比、缺失或歧义问题都必须先调用 retrieve_docs。"
        "即使你认为答案不存在，也必须先检索，不能先说未找到。"
        "请只输出一个合法的 <tool_call>{\"name\":\"retrieve_docs\",\"arguments\":{\"query\":\"...\",\"intent\":\"answer|compare|clarify|verify_absence\"}}</tool_call>，不要输出自然语言答案。"
    )


def _rewrite_citation_format(config: DemoConfig, messages: list[dict[str, str]], answer: str) -> tuple[str, dict]:
    rewrite_messages = deepcopy(messages)
    rewrite_messages.append(
        make_message(
            "user",
            "请只重写上一条答案以满足引用格式：每个句子最多包含两个 [doc_id:chunk_id] 引用；"
            "如果一个句子需要三个来源，请拆成多个短句；不得新增事实，不得新增未检索到的引用。"
            f"\n\n待重写答案：\n{answer}",
        )
    )
    return create_chat_completion(config, rewrite_messages)


def _tool_call_format_error_message(error: Exception) -> str:
    return (
        "上一条 <tool_call> 无法解析。请重新输出，并且只输出一个合法工具调用块；"
        "不要解释，不要使用 Markdown，不要输出占位符。\n"
        "严格格式：\n"
        '<tool_call>{"name":"retrieve_docs","arguments":{"query":"...","intent":"answer"}}</tool_call>\n'
        "JSON 要求：key 和字符串值必须使用英文双引号；不能使用单引号；不能有尾随逗号；"
        "顶层只能有 name 和 arguments；arguments 必须包含 query 和 intent。\n"
        f"解析错误：{type(error).__name__}: {error}"
    )


def run_session(
    user_input: str,
    *,
    scenario_id: str | None = None,
    tool_temperature: float = 0.3,
    answer_temperature: float = 0.6,
    max_steps: int = 6,
    event_callback: EventCallback | None = None,
) -> dict[str, Any]:
    load_repo_env()
    ensure_data_dirs()
    tool_config = DemoConfig.from_env(temperature=tool_temperature, max_tokens=1200)
    answer_config = DemoConfig.from_env(temperature=answer_temperature, max_tokens=1600)
    messages: list[dict[str, str]] = [
        make_message("system", build_system_prompt()),
        make_message("user", user_input),
    ]
    trace: dict[str, Any] = {
        "scenario_id": scenario_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "model": tool_config.model,
        "base_url": tool_config.base_url,
        "tool_temperature": tool_temperature,
        "answer_temperature": answer_temperature,
        "user_input": user_input,
        "messages": deepcopy(messages),
        "steps": [],
        "final_answer": "",
    }
    _emit(
        event_callback,
        "session_start",
        {
            "scenario_id": scenario_id,
            "timestamp": trace["timestamp"],
            "model": trace["model"],
            "base_url": trace["base_url"],
            "user_input": user_input,
        },
    )
    repeated_calls: dict[str, int] = {}

    for step_index in range(max_steps):
        config = tool_config if step_index == 0 else answer_config
        assistant_text, raw_response = create_chat_completion(config, messages)
        _emit(
            event_callback,
            "assistant_text",
            {
                "step_index": step_index,
                "text": assistant_text,
                "has_tool_call": "<tool_call>" in assistant_text,
                "usage": raw_response.get("usage", {}),
            },
        )
        assistant_message = make_message("assistant", assistant_text)
        messages.append(assistant_message)
        trace["messages"].append(deepcopy(assistant_message))
        step: dict[str, Any] = {
            "assistant_text": assistant_text,
            "tool_calls": [],
            "tool_results": [],
            "raw_response": raw_response,
        }
        try:
            tool_calls = extract_tool_calls(assistant_text)
        except (json.JSONDecodeError, ValueError) as exc:
            step["tool_call_parse_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            _emit(
                event_callback,
                "tool_call_error",
                {
                    "step_index": step_index,
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "assistant_text": assistant_text,
                },
            )
            correction_message = make_message("user", _tool_call_format_error_message(exc))
            messages.append(correction_message)
            trace["messages"].append(deepcopy(correction_message))
            trace["steps"].append(step)
            continue

        if not tool_calls:
            if "<tool_call>" in assistant_text:
                exc = ValueError("tool_call block is incomplete or malformed")
                step["tool_call_parse_error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                _emit(
                    event_callback,
                    "tool_call_error",
                    {
                        "step_index": step_index,
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "assistant_text": assistant_text,
                    },
                )
                correction_message = make_message("user", _tool_call_format_error_message(exc))
                messages.append(correction_message)
                trace["messages"].append(deepcopy(correction_message))
                trace["steps"].append(step)
                continue
            if not _has_retrieved(trace):
                step["missing_required_retrieve"] = True
                _emit(
                    event_callback,
                    "missing_required_retrieve",
                    {"step_index": step_index, "assistant_text": assistant_text},
                )
                correction_message = make_message("user", _missing_retrieve_message())
                messages.append(correction_message)
                trace["messages"].append(deepcopy(correction_message))
                trace["steps"].append(step)
                continue
            final_answer = assistant_text.strip()
            if not _citation_limit_ok(final_answer):
                rewritten, rewrite_raw = _rewrite_citation_format(answer_config, messages, final_answer)
                step["citation_rewrite"] = {"raw_response": rewrite_raw, "text": rewritten}
                if _citation_limit_ok(rewritten):
                    final_answer = rewritten.strip()
                    _emit(
                        event_callback,
                        "citation_rewrite",
                        {"step_index": step_index, "text": final_answer},
                    )
            trace["final_answer"] = final_answer
            _emit(
                event_callback,
                "final_answer",
                {"step_index": step_index, "answer": final_answer},
            )
            trace["steps"].append(step)
            break

        for tool_call in tool_calls:
            if tool_call.name not in TOOL_REGISTRY:
                raise RuntimeError(f"Unknown tool requested: {tool_call.name}")
            repeat_key = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)}"
            repeated_calls[repeat_key] = repeated_calls.get(repeat_key, 0) + 1
            if repeated_calls[repeat_key] > 2:
                raise RuntimeError(f"Repeated identical tool call detected: {repeat_key}")

            _emit(
                event_callback,
                "tool_call",
                {"step_index": step_index, "name": tool_call.name, "arguments": tool_call.arguments},
            )
            result = TOOL_REGISTRY[tool_call.name](tool_call.arguments)
            parsed_result = _parse_tool_result(result)
            step["tool_calls"].append({"name": tool_call.name, "arguments": tool_call.arguments})
            step["tool_results"].append({"name": tool_call.name, "content": parsed_result})
            _emit(
                event_callback,
                "tool_result",
                {"step_index": step_index, "name": tool_call.name, "content": parsed_result},
            )
            tool_message = make_message("user", build_tool_result(tool_call.name, result))
            messages.append(tool_message)
            trace["messages"].append(deepcopy(tool_message))

        trace["steps"].append(step)
    else:
        raise RuntimeError("Exceeded maximum RAG tool loop steps.")

    trace["message_count"] = len(messages)
    return trace


def write_trace(trace: dict[str, Any], output_path: Path | None = None) -> Path:
    ensure_data_dirs()
    scenario_id = trace.get("scenario_id") or "adhoc"
    path = output_path or (TRACE_DIR / f"demo3-{scenario_id}.json")
    return write_json(path, trace)
