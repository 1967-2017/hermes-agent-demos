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
        return {"error": "Invalid session_id", "session_id": session_id, "agents": _initial_agents(), "timeline": [], "final_result": _empty_final_result()}
    if not path.exists():
        return {"error": "Blackboard not found", "session_id": session_id, "agents": _initial_agents(), "timeline": [], "final_result": _empty_final_result()}

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
        "final_result": _final_result(records, summary),
    }


def _initial_agents() -> list[dict]:
    return [{"name": name, "status": "waiting", "last_action": "Waiting to start", "round": 0} for name in AGENTS]


def _agent_states(records: list[dict]) -> list[dict]:
    states = {item["name"]: item for item in _initial_agents()}
    for record in records:
        record_type = record.get("type")
        content = record.get("content") or {}
        if record_type == "agent_status":
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
    return items


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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            self._send_json({"error": "No demo4 blackboard runs found", "session_id": "", "agents": _initial_agents(), "timeline": [], "final_result": _empty_final_result()})
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
