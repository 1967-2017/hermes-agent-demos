"""Run demo1 with Hermes native <tool_call> protocol."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, UTC
from pathlib import Path

from .client import Demo1Config, create_chat_completion
from .parser import extract_tool_calls
from .prompts import build_system_prompt
from .scenarios import SCENARIOS
from .tools import TOOL_REGISTRY, TRACE_DIR, ensure_data_dirs
from hermes_native.artifacts import write_json
from hermes_native.chatml import build_tool_result, make_message


def run_session(
    user_inputs: list[str],
    *,
    scenario_id: str | None = None,
    temperature: float = 0.3,
    max_steps: int = 6,
    interactive: bool = False,
) -> dict:
    ensure_data_dirs()
    config = Demo1Config.from_env(temperature=temperature)
    messages: list[dict] = [make_message("system", build_system_prompt())]
    trace = {
        "scenario_id": scenario_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "model": config.model,
        "base_url": config.base_url,
        "temperature": config.temperature,
        "messages": [],
        "steps": [],
        "user_inputs": list(user_inputs),
    }

    pending_inputs = list(user_inputs)
    repeated_calls: dict[str, int] = {}
    final_answer = ""
    awaiting_user_input = False
    latest_confirmation_prompt = ""

    while pending_inputs or (interactive and awaiting_user_input):
        if interactive and awaiting_user_input and not pending_inputs:
            follow_up = input("\nAssistant is waiting for your response (确认/拒绝/取消): ").strip()
            if not follow_up:
                trace["awaiting_user_input"] = True
                trace["final_answer"] = final_answer
                return trace
            pending_inputs.append(follow_up)
            awaiting_user_input = False

        current_input = pending_inputs.pop(0)
        user_message = make_message("user", current_input)
        messages.append(user_message)
        trace["messages"].append(deepcopy(user_message))

        for _ in range(max_steps):
            waiting_for_confirmation = False
            assistant_text, raw_response = create_chat_completion(config, messages)
            assistant_message = make_message("assistant", assistant_text)
            messages.append(assistant_message)
            trace["messages"].append(deepcopy(assistant_message))
            tool_calls = extract_tool_calls(assistant_text)
            lowered_text = assistant_text.lower()

            step = {
                "assistant_text": assistant_text,
                "raw_response": raw_response,
                "tool_calls": [],
                "tool_results": [],
                "awaiting_confirmation": False,
            }

            if not tool_calls:
                final_answer = assistant_text.strip()
                if awaiting_user_input and any(token in lowered_text for token in ("确认", "confirm", "继续", "reply", "回复")):
                    latest_confirmation_prompt = final_answer
                    step["awaiting_confirmation"] = True
                else:
                    awaiting_user_input = False
                if awaiting_user_input:
                    step["awaiting_confirmation"] = True
                trace["steps"].append(step)
                break

            for tool_call in tool_calls:
                if tool_call.name not in TOOL_REGISTRY:
                    raise RuntimeError(f"Unknown tool requested: {tool_call.name}")
                key = f"{tool_call.name}:{sorted(tool_call.arguments.items())}"
                repeated_calls[key] = repeated_calls.get(key, 0) + 1
                if repeated_calls[key] > 2:
                    raise RuntimeError(f"Repeated identical tool call detected: {key}")

                result = TOOL_REGISTRY[tool_call.name](tool_call.arguments)
                step["tool_calls"].append({"name": tool_call.name, "arguments": tool_call.arguments})
                step["tool_results"].append({"name": tool_call.name, "content": result})
                try:
                    parsed_result = json.loads(result)
                except json.JSONDecodeError:
                    parsed_result = {}
                if (
                    tool_call.name == "restart_service"
                    and parsed_result.get("requires_confirmation") is True
                    and parsed_result.get("executed") is False
                ):
                    waiting_for_confirmation = True
                tool_message = make_message("user", build_tool_result(tool_call.name, result))
                messages.append(tool_message)
                trace["messages"].append(deepcopy(tool_message))

            awaiting_user_input = waiting_for_confirmation
            if awaiting_user_input:
                latest_confirmation_prompt = assistant_text.strip()
            trace["steps"].append(step)
        else:
            raise RuntimeError("Exceeded maximum tool loop steps.")

    trace["final_answer"] = final_answer
    trace["awaiting_user_input"] = awaiting_user_input
    if latest_confirmation_prompt:
        trace["latest_confirmation_prompt"] = latest_confirmation_prompt
    return trace


def write_trace(trace: dict, output_path: Path | None = None) -> Path:
    ensure_data_dirs()
    scenario_id = trace.get("scenario_id") or "adhoc"
    filename = f"demo1-{scenario_id}.json"
    path = output_path or (TRACE_DIR / filename)
    return write_json(path, trace)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Demo 1 ops assistant with Hermes native tool-calling.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="1", help="Scenario id to run.")
    parser.add_argument("--input", dest="manual_input", help="Override scenario and run a single manual input.")
    parser.add_argument("--temperature", type=float, default=0.3, help="Model temperature. Demo 1 should use 0.3.")
    parser.add_argument("--max-steps", type=int, default=6, help="Maximum assistant/tool loop steps per user input.")
    parser.add_argument("--trace-file", help="Optional explicit trace output path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.manual_input:
        inputs = [args.manual_input]
        scenario_id = "manual"
        interactive = True
    else:
        scenario = SCENARIOS[args.scenario]
        interactive = bool(scenario.get("interactive_follow_up"))
        inputs = [scenario["inputs"][0]] if interactive else list(scenario["inputs"])
        scenario_id = args.scenario

    trace = run_session(
        inputs,
        scenario_id=scenario_id,
        temperature=args.temperature,
        max_steps=args.max_steps,
        interactive=interactive,
    )
    trace_path = write_trace(trace, Path(args.trace_file) if args.trace_file else None)
    print(trace["final_answer"])
    print(f"\nTrace written to: {trace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
