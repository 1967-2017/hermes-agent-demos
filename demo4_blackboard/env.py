"""Environment helpers for Demo 4."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_native.artifacts import ensure_dir

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_ARXIV_USER_AGENT = "hermes-agent-demos/0.1 (contact: 1654104930@qq.com)"


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
    user_agent = get_arxiv_user_agent()
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
    os.environ["ARXIV_USER_AGENT"] = user_agent
    return argv


def get_mcp_timeout_seconds() -> int:
    raw = os.getenv("DEMO4_MCP_TIMEOUT_SECONDS", "300").strip()
    try:
        return max(10, int(raw))
    except ValueError:
        return 300


def get_viewer_logs_enabled() -> bool:
    raw = os.getenv("DEMO4_ENABLE_VIEWER_LOGS", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_arxiv_user_agent() -> str:
    value = os.getenv("DEMO4_ARXIV_USER_AGENT", DEFAULT_ARXIV_USER_AGENT).strip()
    if not value:
        raise RuntimeError("DEMO4_ARXIV_USER_AGENT must not be empty.")
    return value


def get_enforce_arxiv_policy() -> bool:
    raw = os.getenv("DEMO4_ENFORCE_ARXIV_POLICY", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_http_min_interval_seconds() -> float:
    raw = os.getenv("DEMO4_HTTP_MIN_INTERVAL_SECONDS", "3.5").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 3.5
    if get_enforce_arxiv_policy():
        return max(3.0, value)
    return max(0.0, value)
