"""Mock ops tools for demo1."""

from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path

from hermes_native.artifacts import append_jsonl, ensure_dir

DATA_DIR = Path(__file__).resolve().parent / "data"
TRACE_DIR = DATA_DIR / "traces"
NOTIFICATION_FILE = DATA_DIR / "notifications.jsonl"

SERVICE_PROFILES = {
    "payment-api": {
        "metrics": {
            "p99": {
                "points": [
                    {"ts": "2026-05-18T10:00:00Z", "value": 320},
                    {"ts": "2026-05-18T10:05:00Z", "value": 870},
                    {"ts": "2026-05-18T10:10:00Z", "value": 910},
                ],
                "summary": "payment-api p99 is elevated in the last 15m",
                "incident_hint": "suspected_outage",
            },
            "error_rate": {
                "points": [
                    {"ts": "2026-05-18T10:00:00Z", "value": 2},
                    {"ts": "2026-05-18T10:05:00Z", "value": 18},
                    {"ts": "2026-05-18T10:10:00Z", "value": 24},
                ],
                "summary": "payment-api error_rate is sharply elevated in the last 15m",
                "incident_hint": "suspected_outage",
            },
        },
        "logs": {
            "lines": [
                "ERROR db timeout after 3000ms",
                "ERROR upstream dependency unavailable",
                "WARN retry budget exhausted",
                "INFO healthcheck still failing",
            ],
            "summary": "Logs show repeated upstream and database failures.",
        },
    },
    "catalog-api": {
        "metrics": {
            "p99": {
                "points": [
                    {"ts": "2026-05-18T10:00:00Z", "value": 180},
                    {"ts": "2026-05-18T10:05:00Z", "value": 240},
                    {"ts": "2026-05-18T10:10:00Z", "value": 260},
                ],
                "summary": "catalog-api p99 is mildly elevated in the last 15m",
                "incident_hint": "investigate_only",
            },
            "error_rate": {
                "points": [
                    {"ts": "2026-05-18T10:00:00Z", "value": 0.3},
                    {"ts": "2026-05-18T10:05:00Z", "value": 0.4},
                    {"ts": "2026-05-18T10:10:00Z", "value": 0.5},
                ],
                "summary": "catalog-api error_rate is stable in the last 15m",
                "incident_hint": "stable",
            },
        },
        "logs": {
            "lines": [
                "WARN cache miss ratio elevated",
                "INFO dependency latency increased but within SLO budget",
                "INFO no fatal exceptions observed",
            ],
            "summary": "Logs show latency pressure but no fatal errors or dependency outages.",
        },
    },
}


def ensure_data_dirs() -> None:
    ensure_dir(TRACE_DIR)


def query_metric(args: dict, **_: object) -> str:
    service = str(args.get("service", "")).strip()
    metric = str(args.get("metric", "")).strip()
    window = str(args.get("window", "")).strip()
    if not service or not metric or not window:
        return json.dumps({"ok": False, "error": "Missing service, metric, or window"}, ensure_ascii=False)
    profile = SERVICE_PROFILES.get(service, {})
    metric_payload = profile.get("metrics", {}).get(metric.lower())
    if metric_payload is None:
        metric_payload = {
            "points": [
                {"ts": "2026-05-18T10:00:00Z", "value": 120},
                {"ts": "2026-05-18T10:05:00Z", "value": 125},
                {"ts": "2026-05-18T10:10:00Z", "value": 118},
            ],
            "summary": f"{service} {metric} is stable in the last {window}",
            "incident_hint": "stable",
        }
    payload = {
        "ok": True,
        "service": service,
        "metric": metric,
        "window": window,
        "points": metric_payload["points"],
        "summary": metric_payload["summary"],
        "incident_hint": metric_payload["incident_hint"],
    }
    return json.dumps(payload, ensure_ascii=False)


def tail_log(args: dict, **_: object) -> str:
    service = str(args.get("service", "")).strip()
    level = str(args.get("level", "")).strip() or "error"
    try:
        lines = int(args.get("lines", 3))
    except (TypeError, ValueError):
        lines = 3
    if not service:
        return json.dumps({"ok": False, "error": "Missing service"}, ensure_ascii=False)
    profile = SERVICE_PROFILES.get(service, {})
    log_payload = profile.get("logs", {})
    entries = log_payload.get(
        "lines",
        [
            "INFO no critical errors observed",
            "WARN latency slightly elevated",
            "INFO service remains available",
        ],
    )
    payload = {
        "ok": True,
        "service": service,
        "level": level,
        "lines": entries[: max(1, lines)],
        "summary": log_payload.get("summary", "Logs show no restart-worthy failures."),
    }
    return json.dumps(payload, ensure_ascii=False)


def restart_service(args: dict, **_: object) -> str:
    service = str(args.get("service", "")).strip()
    confirm = bool(args.get("confirm", False))
    if not service:
        return json.dumps({"ok": False, "error": "Missing service"}, ensure_ascii=False)
    if not confirm:
        return json.dumps(
            {
                "ok": True,
                "service": service,
                "executed": False,
                "requires_confirmation": True,
                "message": f"Restart of {service} requires explicit confirmation.",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"ok": True, "service": service, "executed": True, "message": f"{service} restarted successfully (mock)."},
        ensure_ascii=False,
    )


def notify_oncall(args: dict, **_: object) -> str:
    ensure_data_dirs()
    service = str(args.get("service", "")).strip()
    summary = str(args.get("summary", "")).strip()
    if not service or not summary:
        return json.dumps({"ok": False, "error": "Missing service or summary"}, ensure_ascii=False)
    record = {"ts": datetime.now(UTC).isoformat(), "service": service, "summary": summary}
    append_jsonl(NOTIFICATION_FILE, record)
    return json.dumps({"ok": True, "written": True, "file": str(NOTIFICATION_FILE), "service": service}, ensure_ascii=False)


TOOL_REGISTRY = {
    "query_metric": query_metric,
    "tail_log": tail_log,
    "restart_service": restart_service,
    "notify_oncall": notify_oncall,
}
