"""Environment loading helpers for demo2."""

from __future__ import annotations

import os
from pathlib import Path


def load_repo_env() -> None:
    """Load simple KEY=VALUE entries from the repo-local .env with repo values taking precedence."""
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

