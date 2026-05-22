"""Read-only live viewer server for Demo 4 blackboard runs."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .blackboard import RUNS_DIR, read_blackboard

ROOT = Path(__file__).resolve().parent
VIEWER_DIR = ROOT / "viewer"
AGENTS = ("researcher", "critic", "writer")
COLLABORATION_RECORD_TYPES = {"task", "research_notes", "review_feedback", "final_review", "runtime_error"}


def _safe_session_path(session_id: str) -> Path | None:
    if not session_id or Path(session_id).name != session_id:
        return None
    path = (RUNS_DIR / session_id / "blackboard.jsonl").resolve()
    try:
        path.relative_to(RUNS_DIR.resolve())
    except ValueError:
        return None
    return path


def _latest_session_id() -> str:
    candidates = [path.parent for path in RUNS_DIR.glob("*/blackboard.jsonl") if path.is_file()]
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item / "blackboard.jsonl").stat().st_mtime, reverse=True)
    return candidates[0].name


def build_state(session_id: str) -> dict:
    path = _safe_session_path(session_id)
    if path is None:
        return _empty_state("Invalid session_id", session_id)
    if not path.exists():
        return _empty_state("Blackboard not found", session_id)

    records = read_blackboard(path)
    summary = _load_summary(path.parent / "summary.json")
    return {
        "error": None,
        "session_id": session_id,
        "topic": _topic(records, summary),
        "updated_at": records[-1].get("ts") if records else "",
        "record_count": len(records),
        "agents": _agent_states(records),
        "timeline": _tool_timeline(records),
        "collaboration": _collaboration_timeline(records),
        "final_result": _final_result(records, summary),
    }


def _empty_state(error: str, session_id: str) -> dict:
    return {
        "error": error,
        "session_id": session_id,
        "agents": _initial_agents(),
        "timeline": [],
        "collaboration": [],
        "final_result": _empty_final_result(),
    }


def _initial_agents() -> list[dict]:
    return [{"name": name, "status": "waiting", "last_action": "Waiting to start", "round": 0} for name in AGENTS]


def _agent_states(records: list[dict]) -> list[dict]:
    states = {item["name"]: item for item in _initial_agents()}
    has_explicit_status = False
    for record in records:
        record_type = record.get("type")
        content = record.get("content") or {}
        if record_type == "agent_status":
            has_explicit_status = True
            agent = str(content.get("agent") or record.get("from") or "")
            if agent in states:
                states[agent] = {
                    "name": agent,
                    "status": str(content.get("status") or "waiting"),
                    "last_action": str(content.get("action") or ""),
                    "round": record.get("round", 0),
                }
        elif record_type == "runtime_error":
            for agent in states:
                if states[agent]["status"] == "running":
                    states[agent] = {**states[agent], "status": "error", "last_action": str(content.get("error") or "Runtime error")}
    if has_explicit_status:
        return [states[name] for name in AGENTS]

    for record in records:
        record_type = str(record.get("type") or "")
        content = record.get("content") or {}
        round_number = record.get("round", 0)
        if record_type == "task":
            states["researcher"] = {
                "name": "researcher",
                "status": "done" if any(item.get("type") == "research_notes" for item in records) else "running",
                "last_action": "Collecting paper evidence",
                "round": max(round_number, states["researcher"]["round"]),
            }
        elif record_type == "research_notes":
            states["researcher"] = {
                "name": "researcher",
                "status": "done",
                "last_action": "Submitted research notes",
                "round": round_number,
            }
            if states["critic"]["status"] == "waiting":
                states["critic"] = {
                    "name": "critic",
                    "status": "running",
                    "last_action": "Reviewing research notes",
                    "round": round_number,
                }
        elif record_type == "review_feedback":
            review = content.get("review") or {}
            approved = bool(review.get("approve"))
            states["critic"] = {
                "name": "critic",
                "status": "done",
                "last_action": "Approved notes" if approved else "Requested revisions",
                "round": round_number,
            }
            target = "writer" if approved else "researcher"
            if states[target]["status"] == "waiting":
                states[target] = {
                    "name": target,
                    "status": "running",
                    "last_action": "Writing final review" if target == "writer" else "Collecting paper evidence",
                    "round": round_number,
                }
        elif record_type == "final_review":
            states["writer"] = {
                "name": "writer",
                "status": "done",
                "last_action": "Published final review",
                "round": round_number,
            }
        elif record_type == "runtime_error":
            failed_agent = _infer_failed_agent(states, records)
            if failed_agent:
                states[failed_agent] = {
                    "name": failed_agent,
                    "status": "error",
                    "last_action": str(content.get("error") or "Runtime error"),
                    "round": round_number,
                }
    return [states[name] for name in AGENTS]


def _tool_timeline(records: list[dict]) -> list[dict]:
    items = []
    for index, record in enumerate(records):
        record_type = record.get("type")
        if record_type not in {"tool_call", "tool_result"}:
            continue
        content = record.get("content") or {}
        tool = str(content.get("tool") or "")
        if not tool:
            continue
        items.append(
            {
                "id": index,
                "ts": record.get("ts", ""),
                "round": record.get("round", 0),
                "agent": str(content.get("agent") or record.get("from") or ""),
                "kind": record_type,
                "tool": tool,
                "summary": _event_summary(record_type, content),
            }
        )
    if items:
        return items
    return _tool_timeline_from_trace(records)


def _tool_timeline_from_trace(records: list[dict]) -> list[dict]:
    items = []
    next_id = 0
    for record in records:
        if record.get("type") != "research_notes":
            continue
        content = record.get("content") or {}
        tool_trace = content.get("tool_trace") or []
        if not isinstance(tool_trace, list):
            continue
        for step in tool_trace:
            if not isinstance(step, dict):
                continue
            for tool_call in step.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                call_content = {
                    "agent": record.get("from") or "researcher",
                    "tool": tool_call.get("name"),
                    "arguments": tool_call.get("arguments") or {},
                }
                tool = str(call_content.get("tool") or "")
                if not tool:
                    continue
                items.append(
                    {
                        "id": next_id,
                        "ts": record.get("ts", ""),
                        "round": record.get("round", 0),
                        "agent": str(call_content.get("agent") or ""),
                        "kind": "tool_call",
                        "tool": tool,
                        "summary": _event_summary("tool_call", call_content),
                    }
                )
                next_id += 1
            for tool_result in step.get("tool_results") or []:
                if not isinstance(tool_result, dict):
                    continue
                tool = str(tool_result.get("tool") or "")
                if not tool:
                    continue
                result_content = {
                    "agent": record.get("from") or "researcher",
                    "tool": tool,
                    "summary": _summarize_tool_result_payload(tool_result),
                }
                items.append(
                    {
                        "id": next_id,
                        "ts": record.get("ts", ""),
                        "round": record.get("round", 0),
                        "agent": str(result_content.get("agent") or ""),
                        "kind": "tool_result",
                        "tool": tool,
                        "summary": _event_summary("tool_result", result_content),
                    }
                )
                next_id += 1
    return items


def _collaboration_timeline(records: list[dict]) -> list[dict]:
    items = []
    for index, record in enumerate(records):
        record_type = str(record.get("type") or "")
        if record_type not in COLLABORATION_RECORD_TYPES:
            continue
        content = record.get("content") or {}
        summary, detail = _collaboration_text(record_type, content)
        items.append(
            {
                "id": index,
                "ts": record.get("ts", ""),
                "round": record.get("round", 0),
                "from": str(record.get("from") or ""),
                "to": str(record.get("to") or ""),
                "kind": record_type,
                "summary": summary,
                "detail": detail,
            }
        )
    return items


def _collaboration_text(record_type: str, content: dict) -> tuple[str, str]:
    if record_type == "task":
        topic = _truncate_text(content.get("topic"), 160)
        goal = _truncate_text(content.get("goal"), 200)
        summary = topic or goal or "Task assigned"
        detail = _join_lines(
            [
                f"Topic: {topic}" if topic else "",
                f"Goal: {goal}" if goal else "",
            ]
        )
        return summary, detail or "Task assigned"
    if record_type == "research_notes":
        notes = _normalize_notes_payload(content.get("notes"))
        status = _pick_value(notes, "status")
        limitations = _pick_value(notes, "limitations")
        next_actions = _pick_value(notes, "next_actions")
        summary_parts = [
            f"status={status}" if status else "",
            f"limitations={limitations}" if limitations else "",
            f"next={next_actions}" if next_actions else "",
        ]
        notes_text = _truncate_text(_render_payload(notes), 1200)
        detail = _join_lines(
            [
                f"Status: {status}" if status else "",
                f"Limitations: {limitations}" if limitations else "",
                f"Next actions: {next_actions}" if next_actions else "",
                f"Notes: {notes_text}" if notes_text else "",
            ]
        )
        return ", ".join(part for part in summary_parts if part) or "Research notes submitted", detail or "Research notes submitted"
    if record_type == "review_feedback":
        review = content.get("review")
        approve = _bool_text(review, "approve")
        feedback = _pick_value(review, "feedback")
        required_changes = _pick_value(review, "required_changes")
        summary_parts = [
            f"approve={approve}" if approve else "",
            f"feedback={feedback}" if feedback else "",
            f"required_changes={required_changes}" if required_changes else "",
        ]
        detail = _join_lines(
            [
                f"Approve: {approve}" if approve else "",
                f"Feedback: {feedback}" if feedback else "",
                f"Required changes: {required_changes}" if required_changes else "",
            ]
        )
        return ", ".join(part for part in summary_parts if part) or "Review feedback submitted", detail or "Review feedback submitted"
    if record_type == "final_review":
        consensus = "true" if bool(content.get("consensus")) else "false"
        review_text = _truncate_text(content.get("review"), 1200)
        summary = f"consensus={consensus}, review={_truncate_text(content.get('review'), 180)}"
        detail = _join_lines([f"Consensus: {consensus}", f"Review: {review_text}" if review_text else ""])
        return summary, detail
    if record_type == "runtime_error":
        error_type = _truncate_text(content.get("error_type"), 120)
        error_text = _truncate_text(content.get("error"), 500)
        summary = f"{error_type}: {error_text}" if error_type else error_text or "Runtime error"
        detail = _join_lines(
            [
                f"Error type: {error_type}" if error_type else "",
                f"Error: {error_text}" if error_text else "",
            ]
        )
        return summary, detail or "Runtime error"
    return "Record", _truncate_text(_render_payload(content), 1000)


def _event_summary(record_type: str, content: dict) -> str:
    if record_type == "tool_result":
        return str(content.get("summary") or "Tool completed")
    arguments = content.get("arguments") or {}
    if not isinstance(arguments, dict) or not arguments:
        return "Tool call started"
    pairs = [f"{key}={_short_value(value)}" for key, value in arguments.items()]
    return ", ".join(pairs)


def _short_value(value: object) -> str:
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= 120 else text[:117] + "..."


def _infer_failed_agent(states: dict[str, dict], records: list[dict]) -> str:
    for agent in AGENTS:
        if states[agent]["status"] == "running":
            return agent
    for record in reversed(records):
        record_type = str(record.get("type") or "")
        if record_type == "final_review":
            return "writer"
        if record_type == "review_feedback":
            review = record.get("content", {}).get("review") or {}
            return "writer" if bool(review.get("approve")) else "researcher"
        if record_type == "research_notes":
            return "critic"
        if record_type == "task":
            return "researcher"
    return ""


def _normalize_notes_payload(notes: object) -> object:
    if not isinstance(notes, dict):
        return notes
    if any(key in notes for key in ("status", "limitations", "next_actions")):
        return notes
    nested = notes.get("notes")
    if not isinstance(nested, str):
        return notes
    parsed = _try_parse_json_object(nested)
    return parsed if parsed is not None else notes


def _pick_value(payload: object, key: str) -> str:
    if isinstance(payload, dict):
        return _truncate_text(payload.get(key), 240)
    return ""


def _bool_text(payload: object, key: str) -> str:
    if not isinstance(payload, dict) or key not in payload:
        return ""
    value = payload.get(key)
    if isinstance(value, bool):
        return "true" if value else "false"
    return _truncate_text(value, 32)


def _render_payload(payload: object) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, (int, float, bool)) or payload is None:
        return str(payload)
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ": "))
    except TypeError:
        return str(payload)


def _try_parse_json_object(text: str) -> dict | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _truncate_text(value: object, limit: int) -> str:
    text = _render_payload(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _join_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line)


def _summarize_tool_result_payload(payload: dict) -> str:
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


def _final_result(records: list[dict], summary: dict) -> dict:
    for record in reversed(records):
        if record.get("type") == "final_review":
            content = record.get("content") or {}
            return {"ready": True, "consensus": bool(content.get("consensus")), "text": str(content.get("review") or "")}
    return {"ready": bool(summary.get("final_review")), "consensus": bool(summary.get("consensus")), "text": str(summary.get("final_review") or "")}


def _empty_final_result() -> dict:
    return {"ready": False, "consensus": False, "text": ""}


def _topic(records: list[dict], summary: dict) -> str:
    if summary.get("topic"):
        return str(summary["topic"])
    for record in records:
        if record.get("topic"):
            return str(record["topic"])
    return ""


def _load_summary(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


class ViewerHandler(SimpleHTTPRequestHandler):
    server_version = "Demo4BlackboardViewer/1.0"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"{self.address_string()} - {format % args}")

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def _send_error_json(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"error": message}, status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"", "/"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/viewer/")
            self.end_headers()
            return
        if path == "/api/state":
            self._handle_state(parsed.query)
            return
        if path == "/viewer":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/viewer/")
            self.end_headers()
            return
        if path.startswith("/viewer/"):
            self.path = path.removeprefix("/viewer") or "/"
            return super().do_GET()
        self._send_error_json("Not found", HTTPStatus.NOT_FOUND)

    def _handle_state(self, raw_query: str) -> None:
        params = parse_qs(raw_query)
        session_id = (params.get("session_id") or [""])[0].strip() or getattr(self.server, "session_id", "")
        if not session_id:
            session_id = _latest_session_id()
        if not session_id:
            self._send_json(_empty_state("No demo4 blackboard runs found", ""))
            return
        self._send_json(build_state(session_id))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the demo4 live blackboard viewer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--session-id", default="", help="Blackboard run id under demo4_blackboard/data/runs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not VIEWER_DIR.exists():
        raise SystemExit(f"Viewer assets not found: {VIEWER_DIR}")
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    server.session_id = args.session_id
    query = f"?session_id={args.session_id}" if args.session_id else ""
    print(f"Demo4 blackboard viewer: http://{args.host}:{args.port}/viewer/{query}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping demo4 blackboard viewer.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
