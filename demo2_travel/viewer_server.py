"""Read-only trace viewer server for demo2."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
TRACE_DIR = ROOT / "data" / "traces"
VIEWER_DIR = ROOT / "viewer"
TRACE_MARKDOWN_PATH = ROOT / "trace.md"


def _trace_status(trace: dict) -> str:
    if trace.get("awaiting_user_input"):
        return "awaiting_user"
    if trace.get("final_answer"):
        return "final"
    events = trace.get("events") or []
    if any(str(event.get("type")) in {"planner_protocol_retry", "executor_protocol_retry"} for event in events):
        return "warning"
    return "partial"


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


def _session_summary(path: Path) -> dict:
    stat = path.stat()
    trace: dict = {}
    load_error = ""
    try:
        trace = _load_trace(path)
    except (OSError, json.JSONDecodeError) as exc:
        load_error = str(exc)
    events = trace.get("events") or []
    return {
        "name": path.name,
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "scenario_id": trace.get("scenario_id"),
        "timestamp": trace.get("timestamp"),
        "event_count": len(events),
        "status": "error" if load_error else _trace_status(trace),
        "load_error": load_error,
    }


class ViewerHandler(SimpleHTTPRequestHandler):
    server_version = "Demo2TraceViewer/1.0"

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

    def _send_text(self, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
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
        if path == "/api/sessions":
            self._handle_sessions()
            return
        if path == "/api/trace-md":
            self._handle_trace_markdown()
            return
        if path.startswith("/api/traces/"):
            self._handle_trace(path.removeprefix("/api/traces/"))
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

    def _handle_sessions(self) -> None:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
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

    def _handle_trace_markdown(self) -> None:
        if not TRACE_MARKDOWN_PATH.exists():
            self._send_error_json("trace.md not found", HTTPStatus.NOT_FOUND)
            return
        self._send_text(TRACE_MARKDOWN_PATH.read_text(encoding="utf-8"), "text/markdown; charset=utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the demo2 read-only trace viewer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not VIEWER_DIR.exists():
        raise SystemExit(f"Viewer assets not found: {VIEWER_DIR}")
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    url = f"http://{args.host}:{args.port}/viewer/"
    print(f"Demo2 trace viewer: {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping demo2 trace viewer.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
