"""Environment helpers for Demo 4."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_native.artifacts import ensure_dir

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_repo_env() -> None:
    """Load simple KEY=VALUE entries from the repo-local .env."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            os.environ[name] = value


def get_mcp_command() -> list[str]:
    command = os.getenv("DEMO4_MCP_COMMAND", "uvx").strip()
    args = os.getenv("DEMO4_MCP_ARGS", "arxiv-mcp-server").strip()
    storage_path = os.getenv("DEMO4_ARXIV_STORAGE_PATH", "").strip()
    uv_cache_dir = os.getenv("DEMO4_UV_CACHE_DIR", "").strip() or str(DATA_DIR / "uv-cache")
    uv_tool_dir = os.getenv("DEMO4_UV_TOOL_DIR", "").strip() or str(DATA_DIR / "uv-tools")
    ensure_dir(Path(uv_cache_dir))
    ensure_dir(Path(uv_tool_dir))
    os.environ.setdefault("UV_CACHE_DIR", uv_cache_dir)
    os.environ.setdefault("UV_TOOL_DIR", uv_tool_dir)
    argv = [command]
    if args:
        argv.extend(args.split())
    if storage_path:
        ensure_dir(Path(storage_path))
        os.environ["ARXIV_STORAGE_PATH"] = storage_path
    return argv


def get_mcp_timeout_seconds() -> int:
    raw = os.getenv("DEMO4_MCP_TIMEOUT_SECONDS", "300").strip()
    try:
        return max(10, int(raw))
    except ValueError:
        return 300


def get_viewer_logs_enabled() -> bool:
    raw = os.getenv("DEMO4_ENABLE_VIEWER_LOGS", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}
