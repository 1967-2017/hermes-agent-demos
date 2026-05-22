"""Tiny stdio MCP client used by Demo 4."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class McpToolResult:
    content: list[dict[str, Any]]
    raw: dict[str, Any]

    def as_text(self) -> str:
        parts: list[str] = []
        for item in self.content:
            if item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(part for part in parts if part)


class StdioMcpClient:
    def __init__(self, argv: list[str], *, request_timeout_seconds: int = 60) -> None:
        self.argv = argv
        self.request_timeout_seconds = request_timeout_seconds
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None
        self._responses: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def __enter__(self) -> "StdioMcpClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            return
        self.process = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert self.process.stderr is not None
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._stdout_thread = threading.Thread(target=self._drain_stdout, daemon=True)
        self._stdout_thread.start()
        self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "hermes-demo4", "version": "0.1"}})
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def call_tool(self, name: str, arguments: dict[str, Any]) -> McpToolResult:
        response = self._request("tools/call", {"name": name, "arguments": arguments})
        result = response.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(f"MCP tool {name} returned error: {result}")
        content = result.get("content") or []
        if not isinstance(content, list):
            content = [{"type": "text", "text": json.dumps(content, ensure_ascii=False)}]
        return McpToolResult(content=content, raw=result)

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._request("tools/list", {})
        result = response.get("result") or {}
        tools = result.get("tools") or []
        if not isinstance(tools, list):
            raise RuntimeError(f"Invalid MCP tools/list response: {result}")
        return tools

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = self._require_process()
        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self._write_message(payload)
        deadline = time.monotonic() + self.request_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                stderr = "\n".join(self._stderr_lines[-20:])
                raise TimeoutError(f"Timed out waiting for MCP response to {method}. stderr:\n{stderr}")
            try:
                response = self._responses.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if response is None:
                stderr = "\n".join(self._stderr_lines[-20:])
                raise RuntimeError(f"MCP server exited before responding to {method}. stderr:\n{stderr}")
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"MCP request {method} failed: {response['error']}")
            return response

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        process = self._require_process()
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._write_message(payload)

    def _require_process(self) -> subprocess.Popen[str]:
        if self.process is None or self.process.poll() is not None:
            stderr = "\n".join(self._stderr_lines[-20:])
            raise RuntimeError(f"MCP server is not running. stderr:\n{stderr}")
        return self.process

    def _drain_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            self._stderr_lines.append(str(line).rstrip())

    def _drain_stdout(self) -> None:
        while True:
            try:
                self._responses.put(self._read_message())
            except Exception as exc:
                self._responses.put({"jsonrpc": "2.0", "id": -1, "error": {"message": str(exc)}})
                return

    def _write_message(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _read_message(self) -> dict[str, Any] | None:
        process = self._require_process()
        assert process.stdout is not None
        line = process.stdout.readline()
        if not line:
            return None
        return json.loads(line)
