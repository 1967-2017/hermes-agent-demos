"""Environment loading helpers for demo3."""

from __future__ import annotations

import os

from demo2_travel.env import load_repo_env

DASHSCOPE_BASE_URL_DEFAULT = "https://dashscope.aliyuncs.com/api/v1"


def get_dashscope_base_url() -> str:
    return (os.getenv("DASHSCOPE_BASE_URL") or DASHSCOPE_BASE_URL_DEFAULT).strip().rstrip("/")


def get_dashscope_api_key() -> str:
    return (os.getenv("DASHSCOPE_API_KEY") or "").strip()


__all__ = ["DASHSCOPE_BASE_URL_DEFAULT", "get_dashscope_api_key", "get_dashscope_base_url", "load_repo_env"]
