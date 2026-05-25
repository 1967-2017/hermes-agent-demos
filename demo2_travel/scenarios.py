"""Validation scenarios for demo2."""

SCENARIOS = {
    "1": {
        "name": "tokyo-terminal-follow-up-plan",
        "inputs": ["下个月从上海去东京玩一周，预算两万人民币"],
        "fault_injections": {"search_flights": 1},
        "expectation": "Ask for missing required details, let the user continue in the terminal, then produce a complete Tokyo travel plan after the user supplies the remaining information.",
    },
    "2": {
        "name": "underspecified-terminal-follow-up-plan",
        "inputs": ["随便玩玩"],
        "fault_injections": {},
        "expectation": "Ask clarification questions, let the user continue in the terminal, then produce a complete travel plan after enough details are supplied.",
    },
    "3": {
        "name": "unrealistic-antarctica-plan",
        "inputs": ["明天从上海出发去南极玩 7 天，预算 1.5 万"],
        "fault_injections": {},
        "expectation": "Recognize that the Antarctica trip is unrealistic and automatically provide a feasible downgrade or alternative travel plan.",
    },
}
