"""Interactive trace viewer server for Demo 3 RAG."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .runner import run_session, write_trace
from .scenarios import SCENARIOS
from .tools import TRACE_DIR, ensure_data_dirs


ROOT = Path(__file__).resolve().parent
VIEWER_DIR = ROOT / "viewer"
MANUAL_TRACE_NAME = "demo3-manual.json"
MANUAL_TRACE_PATH = TRACE_DIR / MANUAL_TRACE_NAME


def _safe_trace_path(name: str) -> Path | None:
    if not name or Path(name).name != name or not name.endswith(".json"):
        return None
    path = (TRACE_DIR / name).resolve()
    try:
        path.relative_to(TRACE_DIR.resolve())
    except ValueError:
        return None
    return path


def _load_trace(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _last_tool_result(trace: dict) -> dict:
    for step in reversed(trace.get("steps") or []):
        results = step.get("tool_results") or []
        if results:
            content = results[-1].get("content")
            return content if isinstance(content, dict) else {}
    return {}


def _trace_status(trace: dict) -> str:
    if trace.get("final_answer"):
        return "final"
    if any(step.get("tool_call_parse_error") for step in trace.get("steps") or []):
        return "warning"
    return "partial"


def _session_summary(path: Path) -> dict:
    stat = path.stat()
    trace: dict = {}
    load_error = ""
    try:
        trace = _load_trace(path)
    except (OSError, json.JSONDecodeError) as exc:
        load_error = str(exc)
    tool_result = _last_tool_result(trace)
    return {
        "name": path.name,
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "scenario_id": trace.get("scenario_id"),
        "timestamp": trace.get("timestamp"),
        "user_input": trace.get("user_input"),
        "model": trace.get("model"),
        "message_count": trace.get("message_count", 0),
        "step_count": len(trace.get("steps") or []),
        "final_answer": trace.get("final_answer", ""),
        "evidence_status": tool_result.get("evidence_status", ""),
        "returned": tool_result.get("returned", 0),
        "status": "error" if load_error else _trace_status(trace),
        "load_error": load_error,
    }


class ViewerHandler(SimpleHTTPRequestHandler):
    server_version = "Demo3RagViewer/1.0"

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

    def _send_sse(self, event: str, payload: object) -> None:
        body = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"", "/"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/viewer/")
            self.end_headers()
            return
        if path == "/api/scenarios":
            self._handle_scenarios()
            return
        if path == "/api/traces":
            self._handle_traces()
            return
        if path.startswith("/api/traces/"):
            self._handle_trace(path.removeprefix("/api/traces/"))
            return
        if path == "/api/run-stream":
            self._handle_run_stream(parsed.query)
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

    def _handle_scenarios(self) -> None:
        scenarios = [
            {
                "id": scenario_id,
                "name": scenario.get("name", scenario_id),
                "category": scenario.get("category", ""),
                "question": scenario.get("question", ""),
                "expected_behavior": scenario.get("expected_behavior", ""),
            }
            for scenario_id, scenario in sorted(SCENARIOS.items())
        ]
        self._send_json({"scenarios": scenarios})

    def _handle_traces(self) -> None:
        ensure_data_dirs()
        sessions = [_session_summary(path) for path in TRACE_DIR.glob("*.json") if path.is_file()]
        sessions.sort(key=lambda item: (item["mtime"], item["name"]), reverse=True)
        self._send_json({"sessions": sessions})

    def _handle_trace(self, raw_name: str) -> None:
        name = unquote(raw_name)
        path = _safe_trace_path(name)
        if path is None:
            self._send_error_json("Invalid trace name", HTTPStatus.BAD_REQUEST)
            return
        if not path.exists():
            self._send_error_json("Trace not found", HTTPStatus.NOT_FOUND)
            return
        try:
            trace = _load_trace(path)
        except json.JSONDecodeError as exc:
            self._send_error_json(f"Invalid JSON: {exc}", HTTPStatus.UNPROCESSABLE_ENTITY)
            return
        self._send_json({"session": _session_summary(path), "trace": trace})

    def _handle_run_stream(self, raw_query: str) -> None:
        params = parse_qs(raw_query)
        scenario_id = (params.get("scenario") or [""])[0].strip()
        manual_input = (params.get("input") or [""])[0].strip()
        if scenario_id:
            scenario = SCENARIOS.get(scenario_id)
            if not scenario:
                self._send_error_json("Unknown scenario", HTTPStatus.BAD_REQUEST)
                return
            user_input = str(scenario["question"])
        elif manual_input:
            user_input = manual_input
            scenario_id = "manual"
        else:
            self._send_error_json("Use input or scenario", HTTPStatus.BAD_REQUEST)
            return

        tool_temperature = _float_param(params, "tool_temperature", 0.3)
        answer_temperature = _float_param(params, "answer_temperature", 0.6)
        max_steps = _int_param(params, "max_steps", 4)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            trace = run_session(
                user_input,
                scenario_id=scenario_id,
                tool_temperature=tool_temperature,
                answer_temperature=answer_temperature,
                max_steps=max_steps,
                event_callback=self._send_sse,
            )
            trace_path = write_trace(trace, MANUAL_TRACE_PATH if scenario_id == "manual" else None)
            self._send_sse("trace_written", {"path": str(trace_path), "name": trace_path.name})
            self._send_sse("done", {"ok": True})
        except Exception as exc:
            self._send_sse("error", {"type": type(exc).__name__, "message": str(exc)})
            self._send_sse("done", {"ok": False})


def _float_param(params: dict[str, list[str]], name: str, default: float) -> float:
    try:
        return float((params.get(name) or [default])[0])
    except (TypeError, ValueError):
        return default


def _int_param(params: dict[str, list[str]], name: str, default: int) -> int:
    try:
        return int((params.get(name) or [default])[0])
    except (TypeError, ValueError):
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the demo3 interactive RAG viewer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not VIEWER_DIR.exists():
        raise SystemExit(f"Viewer assets not found: {VIEWER_DIR}")
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    url = f"http://{args.host}:{args.port}/viewer/"
    print(f"Demo3 RAG viewer: {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping demo3 RAG viewer.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
