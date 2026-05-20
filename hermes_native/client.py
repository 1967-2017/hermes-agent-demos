"""Minimal OpenAI-compatible chat client for Hermes-native demos."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class DemoConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int = 1200

    @classmethod
    def from_env(cls, *, temperature: float, max_tokens: int = 1200) -> "DemoConfig":
        base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = os.getenv("OPENAI_MODEL", "").strip()
        if base_url and api_key and model:
            return cls(
                base_url=base_url.rstrip("/"),
                api_key=api_key,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        try:
            from hermes_cli.config import load_config
            from hermes_cli.runtime_provider import resolve_runtime_provider

            config = load_config() or {}
            model_cfg = config.get("model") or {}
            if not isinstance(model_cfg, dict):
                model_cfg = {}
            requested_provider = str(model_cfg.get("provider") or "").strip() or None
            runtime = resolve_runtime_provider(requested=requested_provider)
            resolved_model = model or str(model_cfg.get("default") or "").strip()
            resolved_base_url = base_url or str(runtime.get("base_url") or "").strip()
            resolved_api_key = api_key or str(runtime.get("api_key") or "").strip()
            if resolved_model and resolved_base_url and resolved_api_key:
                return cls(
                    base_url=resolved_base_url.rstrip("/"),
                    api_key=resolved_api_key,
                    model=resolved_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        except Exception:
            pass

        raise RuntimeError(
            "Could not resolve runtime model credentials. Set OPENAI_BASE_URL, OPENAI_API_KEY, and OPENAI_MODEL "
            "or run inside an environment where hermes-agent runtime config dependencies are available."
        )


def create_chat_completion(config: DemoConfig, messages: list[dict]) -> tuple[str, dict]:
    url = f"{config.base_url}/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Chat completion failed: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt == 2:
                raise RuntimeError(f"Chat completion failed: {exc}") from exc
            time.sleep(1 + attempt)
    else:
        raise RuntimeError(f"Chat completion failed: {last_error}")

    parsed = json.loads(raw)
    choice = parsed["choices"][0]
    content = choice["message"].get("content") or ""
    return content, parsed
