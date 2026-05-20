"""Plan-execute runner for demo2 travel agent."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_native.artifacts import write_json, write_markdown
from hermes_native.chatml import build_tool_result, make_message
from hermes_native.client import DemoConfig, create_chat_completion
from hermes_native.parser import ParsedToolCall, extract_tool_calls

from .env import load_repo_env
from .prompts import TOOL_SCHEMAS, build_executor_prompt, build_observer_prompt, build_planner_prompt
from .tools import TOOL_REGISTRY, TRACE_DIR, ToolContext, ensure_data_dirs

JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
REACT_RE = re.compile(r"<react>\s*(\{.*?\})\s*</react>", re.DOTALL)
TRAILING_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*\})\s*(?:</tool_call>)?\s*$", re.DOTALL)
TOOL_SCHEMA_BY_NAME = {schema["name"]: schema for schema in TOOL_SCHEMAS}


@dataclass
class SessionState:
    session_id: str
    user_request: str
    user_inputs: list[str]
    plan_version: int = 0
    current_plan: list[dict[str, Any]] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    pending_user_decision: str | None = None
    user_replies: list[str] = field(default_factory=list)
    confirmed_constraints: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_request": self.user_request,
            "user_inputs": self.user_inputs,
            "plan_version": self.plan_version,
            "current_plan": self.current_plan,
            "completed_steps": self.completed_steps,
            "observations": self.observations,
            "pending_user_decision": self.pending_user_decision,
            "user_replies": self.user_replies,
            "confirmed_constraints": self.confirmed_constraints,
        }


def _infer_confirmed_constraints(user_inputs: list[str]) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    joined = "\n".join(user_inputs)
    origin_map = {
        "\u4e0a\u6d77": "\u4e0a\u6d77",
        "\u5317\u4eac": "\u5317\u4eac",
        "\u5e7f\u5dde": "\u5e7f\u5dde",
        "\u6df1\u5733": "\u6df1\u5733",
        "\u676d\u5dde": "\u676d\u5dde",
        "\u6210\u90fd": "\u6210\u90fd",
    }
    for token, value in origin_map.items():
        if token in joined:
            constraints["origin"] = value
            break
    return constraints


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = JSON_OBJECT_RE.search(text or "")
        if not match:
            raise
        return json.loads(match.group(0))


def _extract_react_summary(text: str) -> str:
    match = REACT_RE.search(text or "")
    if not match:
        return ""
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ""
    return str(payload.get("thought_summary", "")).strip()


def _extract_tool_calls_lenient(text: str) -> list[ParsedToolCall]:
    calls = extract_tool_calls(text)
    if calls:
        return calls
    match = TRAILING_TOOL_CALL_RE.search(text or "")
    if not match:
        return []
    raw_json = match.group(1).strip()
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    name = str(payload.get("name", "")).strip()
    arguments = payload.get("arguments") or {}
    if not name or not isinstance(arguments, dict):
        return []
    return [ParsedToolCall(name=name, arguments=arguments, raw_json=raw_json)]


def _json_equivalent(left: Any, right: Any) -> bool:
    return json.dumps(left or {}, sort_keys=True, ensure_ascii=False) == json.dumps(right or {}, sort_keys=True, ensure_ascii=False)


def _plan_schema_errors(plan_payload: dict[str, Any]) -> list[str]:
    if plan_payload.get("status") != "ready":
        return []
    errors: list[str] = []
    for step in plan_payload.get("plan", []):
        step_id = str(step.get("id", ""))
        tool = str(step.get("tool", "")).strip()
        args = step.get("arguments") or {}
        schema = TOOL_SCHEMA_BY_NAME.get(tool)
        if not schema:
            errors.append(f"{step_id}: unknown tool {tool}")
            continue
        if not isinstance(args, dict):
            errors.append(f"{step_id}: arguments must be an object")
            continue
        parameters = schema.get("parameters", {})
        properties = parameters.get("properties", {})
        allowed = set(properties.keys())
        required = set(parameters.get("required", []))
        actual = set(args.keys())
        missing = sorted(required - actual)
        extra = sorted(actual - allowed)
        if missing:
            errors.append(f"{step_id}: missing required keys for {tool}: {missing}")
        if extra:
            errors.append(f"{step_id}: unsupported keys for {tool}: {extra}")
        for key, spec in properties.items():
            if key not in args:
                continue
            expected_type = spec.get("type")
            value = args[key]
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"{step_id}: {tool}.{key} must be a string")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"{step_id}: {tool}.{key} must be an integer")
            elif expected_type == "number" and not isinstance(value, (int, float)):
                errors.append(f"{step_id}: {tool}.{key} must be a number")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"{step_id}: {tool}.{key} must be a boolean")
    return errors


def _normalize_plan(planner_payload: dict[str, Any], fallback_version: int) -> dict[str, Any]:
    status = str(planner_payload.get("status", "")).strip()
    if status not in {"need_user_input", "ready", "final"}:
        raise ValueError(f"Planner returned invalid status: {status}")
    plan = planner_payload.get("plan") or []
    if not isinstance(plan, list):
        raise ValueError("Planner plan must be a list")
    try:
        plan_version = int(planner_payload.get("plan_version") or fallback_version)
    except (TypeError, ValueError):
        plan_version = fallback_version
    planner_payload["status"] = status
    planner_payload["plan"] = plan
    planner_payload["plan_version"] = max(1, plan_version)
    planner_payload.setdefault("question", "")
    planner_payload.setdefault("change_reason", "")
    planner_payload.setdefault("final_answer", "")
    return planner_payload


class TravelAgentRunner:
    def __init__(
        self,
        *,
        planner_temperature: float = 0.7,
        executor_temperature: float = 0.3,
        max_iterations: int = 14,
        max_tokens: int = 1800,
        tool_context: ToolContext | None = None,
    ) -> None:
        load_repo_env()
        self.planner_config = DemoConfig.from_env(temperature=planner_temperature, max_tokens=max_tokens)
        self.executor_config = DemoConfig.from_env(temperature=executor_temperature, max_tokens=max_tokens)
        self.max_iterations = max_iterations
        self.tool_context = tool_context or ToolContext()
        self._tool_call_repetitions: dict[str, int] = {}

    def run(
        self,
        user_inputs: list[str],
        *,
        scenario_id: str | None = None,
        prefilled_replies: bool = False,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        ensure_data_dirs()
        self._tool_call_repetitions = {}
        if not user_inputs:
            raise ValueError("At least one user input is required")
        session_id = scenario_id or session_id or datetime.now(UTC).strftime("manual-%Y%m%d%H%M%S")
        if prefilled_replies:
            state = SessionState(
                session_id=session_id,
                user_request=user_inputs[0],
                user_inputs=list(user_inputs),
                user_replies=list(user_inputs[1:]),
                confirmed_constraints=_infer_confirmed_constraints(user_inputs),
            )
            pending_inputs: list[str] = []
        else:
            state = SessionState(
                session_id=session_id,
                user_request=user_inputs[0],
                user_inputs=[user_inputs[0]],
                confirmed_constraints=_infer_confirmed_constraints([user_inputs[0]]),
            )
            pending_inputs = list(user_inputs[1:])
        trace: dict[str, Any] = {
            "scenario_id": scenario_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "planner_model": self.planner_config.model,
            "executor_model": self.executor_config.model,
            "planner_temperature": self.planner_config.temperature,
            "executor_temperature": self.executor_config.temperature,
            "state_snapshots": [],
            "events": [],
            "final_answer": "",
            "awaiting_user_input": False,
        }

        planner_payload = self._call_planner(state, trace)
        for _ in range(self.max_iterations):
            status = planner_payload["status"]
            state.plan_version = int(planner_payload["plan_version"])
            state.current_plan = deepcopy(planner_payload.get("plan") or [])
            trace["state_snapshots"].append(state.snapshot())

            if status == "final":
                trace["final_answer"] = str(planner_payload.get("final_answer") or "").strip()
                trace["events"].append({"type": "final", "plan_version": state.plan_version, "answer": trace["final_answer"]})
                return trace

            if status == "need_user_input":
                question = str(planner_payload.get("question") or "").strip()
                state.pending_user_decision = question
                trace["events"].append(
                    {
                        "type": "user_input_required",
                        "plan_version": state.plan_version,
                        "question": question,
                        "change_reason": planner_payload.get("change_reason", ""),
                    }
                )
                if not pending_inputs:
                    trace["awaiting_user_input"] = True
                    trace["latest_question"] = question
                    trace["state_snapshots"].append(state.snapshot())
                    return trace
                reply = pending_inputs.pop(0)
                state.user_replies.append(reply)
                state.user_inputs.append(reply)
                state.confirmed_constraints.update(_infer_confirmed_constraints(state.user_inputs))
                state.pending_user_decision = None
                trace["events"].append({"type": "user_reply", "content": reply})
                planner_payload = self._call_planner(state, trace)
                continue

            next_step = self._select_next_step(state.current_plan, state.completed_steps)
            if next_step is None:
                planner_payload = self._call_planner(state, trace, force_finalize=True)
                continue
            observation = self._execute_step(next_step, trace)
            state.completed_steps.append(str(next_step.get("id", "")))
            state.observations.append(observation)
            trace["state_snapshots"].append(state.snapshot())
            planner_payload = self._call_planner(state, trace)

        raise RuntimeError("Exceeded maximum plan-execute iterations")

    def _call_planner(self, state: SessionState, trace: dict[str, Any], *, force_finalize: bool = False) -> dict[str, Any]:
        payload = {
            "user_request": state.user_request,
            "user_replies": state.user_replies,
            "confirmed_constraints": state.confirmed_constraints,
            "session_state": state.snapshot(),
            "force_finalize": force_finalize,
        }
        messages = [
            make_message("system", build_planner_prompt()),
            make_message("user", json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
        content = ""
        raw: dict[str, Any] = {}
        parsed: dict[str, Any] | None = None
        errors: list[str] = []
        for attempt in range(3):
            content, raw = create_chat_completion(self.planner_config, messages)
            try:
                parsed = _normalize_plan(_extract_json_object(content), state.plan_version + 1)
                errors = _plan_schema_errors(parsed)
            except (json.JSONDecodeError, ValueError) as exc:
                parsed = None
                errors = [f"invalid planner JSON: {exc}"]
            if not errors:
                break
            trace["events"].append(
                {
                    "type": "planner_protocol_retry",
                    "attempt": attempt + 1,
                    "errors": errors,
                    "raw_text": content,
                }
            )
            messages.extend(
                [
                    make_message("assistant", content),
                    make_message(
                        "user",
                        "Protocol violation. Retry the plan JSON. Output exactly one valid JSON object, "
                        "with no markdown, no comments, no trailing commas, and no text outside JSON. "
                        "Every ready step must use only the exact tool schema keys and value types from the <tools> block. "
                        f"Fix these errors: {json.dumps(errors, ensure_ascii=False)}",
                    ),
                ]
            )
        if parsed is None or errors:
            raise RuntimeError(f"Planner returned invalid tool arguments after retries: {errors}. Last output: {content}")
        trace["events"].append(
            {
                "type": "plan",
                "plan_version": parsed["plan_version"],
                "status": parsed["status"],
                "change_reason": parsed.get("change_reason", ""),
                "question": parsed.get("question", ""),
                "plan": parsed.get("plan", []),
                "raw_response": raw,
            }
        )
        return parsed

    def _execute_step(self, step: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
        messages = [
            make_message("system", build_executor_prompt()),
            make_message("user", json.dumps({"planner_step": step}, ensure_ascii=False, indent=2)),
        ]
        expected_tool = str(step.get("tool", "")).strip()
        action_text = ""
        action_raw: dict[str, Any] = {}
        tool_calls = []
        for attempt in range(3):
            action_text, action_raw = create_chat_completion(self.executor_config, messages)
            tool_calls = _extract_tool_calls_lenient(action_text)
            expected_arguments = step.get("arguments") or {}
            arguments_match = len(tool_calls) == 1 and _json_equivalent(tool_calls[0].arguments, expected_arguments)
            if len(tool_calls) == 1 and tool_calls[0].name == expected_tool and arguments_match:
                break
            trace["events"].append(
                {
                    "type": "executor_protocol_retry",
                    "step_id": step.get("id"),
                    "attempt": attempt + 1,
                    "expected_tool": expected_tool,
                    "expected_arguments": expected_arguments,
                    "tool_call_count": len(tool_calls),
                    "actual_tool": tool_calls[0].name if len(tool_calls) == 1 else "",
                    "actual_arguments": tool_calls[0].arguments if len(tool_calls) == 1 else {},
                    "raw_text": action_text,
                }
            )
            messages.extend(
                [
                    make_message("assistant", action_text),
                    make_message(
                        "user",
                        "Protocol violation. Retry the same planner_step. "
                        "Return exactly one <react>{...}</react> block and exactly one "
                        f'<tool_call>{{"name":"{expected_tool}","arguments":...}}</tool_call> block. '
                        f"Use exactly these arguments without changing dates, cities, or values: "
                        f"{json.dumps(expected_arguments, ensure_ascii=False)}. "
                        "Do not answer in natural language.",
                    ),
                ]
            )
        if len(tool_calls) != 1:
            raise RuntimeError(f"Executor must emit exactly one tool call, got {len(tool_calls)}. Last output: {action_text}")
        tool_call = tool_calls[0]
        if tool_call.name != expected_tool:
            raise RuntimeError(f"Executor called {tool_call.name}, expected {expected_tool}. Last output: {action_text}")
        if not _json_equivalent(tool_call.arguments, step.get("arguments") or {}):
            raise RuntimeError(
                "Executor changed planner arguments. "
                f"Expected {json.dumps(step.get('arguments') or {}, ensure_ascii=False)}, "
                f"got {json.dumps(tool_call.arguments, ensure_ascii=False)}. Last output: {action_text}"
            )
        if tool_call.name not in TOOL_REGISTRY:
            raise RuntimeError(f"Unknown tool requested: {tool_call.name}")
        repeat_key = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)}"
        self._tool_call_repetitions[repeat_key] = self._tool_call_repetitions.get(repeat_key, 0) + 1
        if self._tool_call_repetitions[repeat_key] > 2:
            raise RuntimeError(f"Repeated identical tool call detected: {repeat_key}")

        result = TOOL_REGISTRY[tool_call.name](tool_call.arguments, self.tool_context)
        trace["events"].append(
            {
                "type": "action",
                "step_id": step.get("id"),
                "goal": step.get("goal"),
                "thought_summary": _extract_react_summary(action_text),
                "tool": tool_call.name,
                "arguments": tool_call.arguments,
                "tool_result": result,
                "raw_response": action_raw,
            }
        )

        observation_messages = [
            make_message("system", build_observer_prompt()),
            make_message(
                "user",
                json.dumps({"planner_step": step, "tool_result": result}, ensure_ascii=False, indent=2)
                + "\n"
                + build_tool_result(tool_call.name, result),
            ),
        ]
        observation_text, observation_raw = create_chat_completion(self.executor_config, observation_messages)
        observation = _extract_json_object(observation_text)
        observation.setdefault("step_id", step.get("id"))
        observation.setdefault("tool", tool_call.name)
        observation.setdefault("ok", True)
        observation.setdefault("requires_replan", False)
        observation.setdefault("changes_core_constraints", False)
        trace["events"].append({"type": "observation", "observation": observation, "raw_response": observation_raw})
        return observation

    @staticmethod
    def _select_next_step(plan: list[dict[str, Any]], completed_steps: list[str]) -> dict[str, Any] | None:
        completed = set(completed_steps)
        for step in plan:
            step_id = str(step.get("id", ""))
            if step_id in completed:
                continue
            dependencies = [str(dep) for dep in step.get("depends_on", [])]
            if all(dep in completed for dep in dependencies):
                return step
        return None


def write_trace_json(trace: dict[str, Any], output_path: Path | None = None) -> Path:
    ensure_data_dirs()
    scenario_id = trace.get("scenario_id") or "manual"
    path = output_path or (TRACE_DIR / f"demo2-{scenario_id}.json")
    return write_json(path, trace)


def render_trace_markdown(traces: list[dict[str, Any]]) -> str:
    lines = ["# Demo 2 Trace", ""]
    for trace in traces:
        scenario = trace.get("scenario_id") or "manual"
        lines.append(f"## Scenario {scenario}")
        lines.append("")
        for event in trace.get("events", []):
            event_type = event.get("type")
            if event_type == "plan":
                lines.append(f"### Plan v{event.get('plan_version')} ({event.get('status')})")
                reason = str(event.get("change_reason") or "").strip()
                if reason:
                    lines.append(f"- change_reason: {reason}")
                question = str(event.get("question") or "").strip()
                if question:
                    lines.append(f"- question: {question}")
                for step in event.get("plan", []):
                    lines.append(
                        f"- {step.get('id')}: {step.get('goal')} -> `{step.get('tool')}` "
                        f"{json.dumps(step.get('arguments', {}), ensure_ascii=False)}"
                    )
                lines.append("")
            elif event_type == "action":
                lines.append(f"### Action {event.get('step_id')}")
                summary = str(event.get("thought_summary") or "").strip()
                if summary:
                    lines.append(f"- thought_summary: {summary}")
                lines.append(f"- tool: `{event.get('tool')}`")
                lines.append(f"- arguments: `{json.dumps(event.get('arguments', {}), ensure_ascii=False)}`")
                lines.append(f"- observation_source: `{event.get('tool_result')}`")
                lines.append("")
            elif event_type == "observation":
                observation = event.get("observation", {})
                lines.append("### Observation")
                lines.append(f"- summary: {observation.get('summary', '')}")
                lines.append(f"- requires_replan: {observation.get('requires_replan', False)}")
                lines.append(f"- changes_core_constraints: {observation.get('changes_core_constraints', False)}")
                lines.append("")
            elif event_type == "user_input_required":
                lines.append("### User Decision Required")
                reason = str(event.get("change_reason") or "").strip()
                if reason:
                    lines.append(f"- change_reason: {reason}")
                lines.append(f"- question: {event.get('question', '')}")
                lines.append("")
            elif event_type == "user_reply":
                lines.append("### User Reply")
                lines.append(f"- content: {event.get('content', '')}")
                lines.append("")
            elif event_type == "final":
                lines.append("### Final")
                lines.append(str(event.get("answer") or ""))
                lines.append("")
        if trace.get("awaiting_user_input"):
            lines.append(f"Awaiting user input: {trace.get('latest_question', '')}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_trace_markdown(traces: list[dict[str, Any]], output_path: Path | None = None) -> Path:
    path = output_path or (Path(__file__).resolve().parent / "trace.md")
    return write_markdown(path, render_trace_markdown(traces))
