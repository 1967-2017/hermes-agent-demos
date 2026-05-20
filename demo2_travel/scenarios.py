"""Validation scenarios for demo2."""

SCENARIOS = {
    "1": {
        "name": "tokyo-replan-after-no-flights",
        "inputs": ["2026年6月1日从上海去东京玩一周，预算1.5万", "延后一周继续去东京"],
        "fault_injections": {"search_flights": 1},
        "expectation": "Plan at least five steps, force the first flight search to return no availability, replan, and finish with flight, hotel, weather, and budget details.",
    },
    "2": {
        "name": "underspecified-trip",
        "inputs": ["随便玩玩", "我从上海出发，下个月去泰国 5 天，预算 8000 元"],
        "fault_injections": {},
        "expectation": "Ask only for missing required constraints (origin, destination, date window/duration, budget) before using tools, then plan once those details are supplied.",
    },
    "3": {
        "name": "unrealistic-antarctica",
        "inputs": ["明天就走，去南极"],
        "fault_injections": {},
        "expectation": "Recognize flight, visa, logistics, or budget infeasibility and provide a downgrade plan.",
    },
}
