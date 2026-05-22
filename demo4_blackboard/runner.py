"""Controller loop for Demo 4."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_native.artifacts import write_json

from .agents import approval_streak, latest_feedback, run_critic, run_researcher, run_writer
from .blackboard import Blackboard
from .env import get_mcp_command, get_mcp_timeout_seconds, load_repo_env
from .mcp_client import StdioMcpClient
from .tools import ArxivToolAdapter


def run_session(
    topic: str,
    *,
    session_id: str | None = None,
    max_rounds: int = 6,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    load_repo_env()
    blackboard = Blackboard.create(topic, session_id=session_id, reset=True)
    blackboard.append(
        "controller",
        "researcher",
        0,
        "task",
        {"topic": topic, "goal": "Produce an approximately 2000 Chinese character mini-review."},
    )
    started = time.monotonic()
    consensus = False
    final_record: dict[str, Any] | None = None

    try:
        with StdioMcpClient(get_mcp_command(), request_timeout_seconds=get_mcp_timeout_seconds()) as mcp:
            tool_adapter = ArxivToolAdapter(mcp)
            for round_number in range(1, max_rounds + 1):
                if time.monotonic() - started > timeout_seconds:
                    break
                run_researcher(blackboard, topic, round_number, tool_adapter, feedback=latest_feedback(blackboard))
                if time.monotonic() - started > timeout_seconds:
                    break
                run_critic(blackboard, topic, round_number)
                if approval_streak(blackboard) >= 2:
                    consensus = True
                    final_record = run_writer(blackboard, topic, round_number, consensus=True)
                    break
    except Exception as exc:
        blackboard.append(
            "controller",
            "user",
            0,
            "runtime_error",
            {"error_type": type(exc).__name__, "error": str(exc)},
        )
        raise

    if final_record is None:
        final_record = run_writer(blackboard, topic, max_rounds, consensus=False)

    summary = {
        "topic": topic,
        "session_id": blackboard.session_id,
        "blackboard_path": str(blackboard.path),
        "timestamp": datetime.now(UTC).isoformat(),
        "consensus": consensus,
        "approval_streak": approval_streak(blackboard),
        "final_review": final_record.get("content", {}).get("review", ""),
    }
    write_json(blackboard.path.parent / "summary.json", summary)
    return summary


def write_trace_summary(summary: dict[str, Any], output_path: Path | None = None) -> Path:
    path = output_path or (Path(summary["blackboard_path"]).parent / "summary.json")
    return write_json(path, summary)
