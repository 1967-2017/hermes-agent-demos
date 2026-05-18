"""Prompt and tool declarations for demo1."""

from __future__ import annotations

from hermes_native.chatml import build_tools_block

TOOL_SCHEMAS = [
    {
        "name": "query_metric",
        "description": (
            "Query fake timeseries metrics for a service. Use for latency, p99, "
            "error rate, throughput, or recent health metrics."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name, e.g. payment-api"},
                "metric": {"type": "string", "description": "Metric name, e.g. p99, error_rate, qps"},
                "window": {"type": "string", "description": "Window, e.g. 15m, 1h, 24h"},
            },
            "required": ["service", "metric", "window"],
        },
    },
    {
        "name": "tail_log",
        "description": "Read fake recent logs for a service during incident diagnosis.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "lines": {"type": "integer", "description": "How many lines to read"},
                "level": {"type": "string", "description": "Log level filter, e.g. error, warn, info"},
            },
            "required": ["service", "lines", "level"],
        },
    },
    {
        "name": "restart_service",
        "description": (
            "Restart a single service. Must only be used for one named service. "
            "Use confirm=false first unless the user has explicitly confirmed the restart."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "confirm": {"type": "boolean", "description": "True only after explicit user confirmation"},
            },
            "required": ["service", "confirm"],
        },
    },
    {
        "name": "notify_oncall",
        "description": "Notify the on-call engineer with a short incident summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["service", "summary"],
        },
    },
]


def build_system_prompt() -> str:
    tools_block = build_tools_block(TOOL_SCHEMAS)
    return (
        "You are an operations assistant for service troubleshooting only.\n"
        "Use ChatML-style conversation roles. Follow Hermes native tool-calling protocol.\n"
        "Rules:\n"
        "- Only help with operations tasks for named services.\n"
        "- Politely refuse unrelated requests.\n"
        "- If the user only asks to view or inspect one metric, call the minimum required tool once and answer with that result only.\n"
        "- Do not escalate a metric-only request into incident triage unless the user asks to investigate, handle, diagnose, recover, or fix the issue.\n"
        "- For a simple metric lookup, do not call logs, notify_oncall, or restart tools on your own.\n"
        "- For incident-like requests, inspect metrics and logs before proposing a restart.\n"
        "- If diagnostics show only mild degradation or no strong outage evidence, summarize findings and recommend monitoring instead of restart.\n"
        "- Only notify_oncall and propose restart when the diagnostics support a real outage or failed dependency state.\n"
        "- Before a restart, notify on-call with a short summary.\n"
        "- Never restart all services or perform bulk destructive actions.\n"
        "- For restart requests, require explicit user confirmation before restart_service(confirm=true).\n"
        "- If the user asks to restart a single service and has not yet confirmed, call restart_service with confirm=false first, then ask for confirmation.\n"
        "- If you decide a restart is needed during incident triage, you must call notify_oncall before restart_service(confirm=true).\n"
        "- When you need a tool, respond with exactly one or more <tool_call>{...}</tool_call> blocks.\n"
        "- You may include short natural-language text before or after tool_call blocks, but the tool_call JSON must stay valid.\n"
        "- Each tool call JSON must have keys: name and arguments.\n"
        "- If you receive a <tool_result> block, use it to continue reasoning.\n"
        "- If no tool is needed, answer normally in Chinese.\n\n"
        f"{tools_block}"
    )
