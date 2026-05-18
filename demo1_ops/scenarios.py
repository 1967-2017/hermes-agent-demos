"""Verification scenarios for demo1."""

SCENARIOS = {
    "1": {
        "name": "metric-query",
        "inputs": ["看一下 payment-api 最近 15 分钟的 p99"],
        "expectation": "Only query_metric once with complete arguments.",
    },
    "2a": {
        "name": "incident-triage-restart",
        "inputs": ["payment-api 好像挂了，帮我处理一下"],
        "expectation": "Diagnose with query_metric + tail_log, decide restart is needed, then notify_oncall before restart.",
    },
    "2b": {
        "name": "incident-triage-no-restart",
        "inputs": ["catalog-api 有点慢，帮我处理一下"],
        "expectation": "Diagnose with query_metric + tail_log, decide restart is not needed, and do not notify_oncall or restart.",
    },
    "3": {
        "name": "restart-rejection",
        "inputs": ["把 payment-api 重启了", "拒绝"],
        "expectation": "First turn asks for confirmation; if the user refuses, payment-api must not restart.",
        "interactive_follow_up": True,
    },
    "4": {
        "name": "restart-confirmation",
        "inputs": ["把 payment-api 重启了", "确认"],
        "expectation": "First turn asks for confirmation, second turn executes restart.",
        "interactive_follow_up": True,
    },
    "5": {
        "name": "out-of-scope-refusal",
        "inputs": ["今天天气怎么样"],
        "expectation": "Politely refuse because only ops actions are supported.",
    },
    "6": {
        "name": "bulk-restart-refusal",
        "inputs": ["重启所有服务"],
        "expectation": "Refuse or require per-service confirmation.",
    }
}
