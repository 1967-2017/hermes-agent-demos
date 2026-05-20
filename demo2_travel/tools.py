"""Mock travel tools for demo2."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from hermes_native.artifacts import append_jsonl, ensure_dir

DATA_DIR = Path(__file__).resolve().parent / "data"
TRACE_DIR = DATA_DIR / "traces"
EVENTS_FILE = DATA_DIR / "tool_events.jsonl"


@dataclass
class ToolContext:
    fault_injections: dict[str, int] = field(default_factory=dict)
    call_counts: dict[str, int] = field(default_factory=dict)

    def should_inject_fault(self, tool_name: str) -> bool:
        count = self.call_counts.get(tool_name, 0) + 1
        self.call_counts[tool_name] = count
        limit = self.fault_injections.get(tool_name, 0)
        return count <= limit


def ensure_data_dirs() -> None:
    ensure_dir(TRACE_DIR)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token.lower() in lowered for token in tokens)


def _date_window_overlaps(value: str, start: str, end: str) -> bool:
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", value or "")
    if not dates:
        return False
    window_start = min(dates)
    window_end = max(dates)
    return window_start <= end and window_end >= start


def search_flights(args: dict, context: ToolContext | None = None) -> str:
    context = context or ToolContext()
    if context.should_inject_fault("search_flights"):
        return _json(
            {
                "ok": False,
                "tool": "search_flights",
                "no_availability": True,
                "requires_alternative": True,
                "message": "No available flights in this exact date window. Try adjacent dates or an alternative nearby destination.",
            }
        )

    destination = str(args.get("destination", "")).strip()
    date_window = str(args.get("date_window", "")).strip()
    duration_days = int(args.get("duration_days") or 0)
    origin = str(args.get("origin", "上海")).strip() or "上海"

    if (
        _contains_any(origin, ("上海", "sha", "pvg"))
        and _contains_any(destination, ("东京", "tokyo", "hnd", "nrt"))
        and _date_window_overlaps(date_window, "2026-06-01", "2026-06-15")
    ):
        return _json(
            {
                "ok": False,
                "tool": "search_flights",
                "origin": origin,
                "destination": destination,
                "date_window": date_window,
                "no_availability": True,
                "requires_alternative": True,
                "message": "No available flights from Shanghai to Tokyo between 2026-06-01 and 2026-06-15 in the mock inventory. Try later dates or a nearby destination.",
            }
        )

    if _contains_any(destination, ("南极", "antarctica")):
        return _json(
            {
                "ok": False,
                "tool": "search_flights",
                "destination": destination,
                "unrealistic": True,
                "requires_alternative": True,
                "message": "No direct commercial itinerary is realistic on this timeline. Antarctica usually needs expedition logistics through South America and long lead time.",
                "alternatives": ["新西兰南岛冰川", "北海道冬季雪景", "冰岛极光路线"],
            }
        )

    price_map = {
        "日本": 3200,
        "东京": 3300,
        "大阪": 2900,
        "韩国": 1800,
        "泰国": 2200,
        "新加坡": 2500,
        "冰岛": 8600,
        "新西兰": 7600,
    }
    price = next((amount for key, amount in price_map.items() if key in destination), 3600)
    payload = {
        "ok": True,
        "tool": "search_flights",
        "origin": origin,
        "destination": destination,
        "date_window": date_window,
        "duration_days": duration_days,
        "options": [
            {
                "airline": "Mock Air",
                "depart": f"{date_window} early window",
                "return": f"{duration_days} days later",
                "price_cny": price,
                "stops": 0 if price < 5000 else 1,
            }
        ],
        "summary": f"Found workable flight options from {origin} to {destination}.",
    }
    append_jsonl(EVENTS_FILE, {"tool": "search_flights", "args": args, "result": payload})
    return _json(payload)


def search_hotels(args: dict, context: ToolContext | None = None) -> str:
    destination = str(args.get("destination", "")).strip()
    nights = int(args.get("nights") or 1)
    budget = float(args.get("budget_cny") or 0)
    per_night = 780 if _contains_any(destination, ("日本", "东京", "大阪")) else 520
    if _contains_any(destination, ("南极", "antarctica")):
        return _json(
            {
                "ok": False,
                "tool": "search_hotels",
                "unrealistic": True,
                "requires_alternative": True,
                "message": "Standard hotel booking is not applicable for Antarctica expedition travel.",
            }
        )
    total = per_night * max(1, nights)
    payload = {
        "ok": True,
        "tool": "search_hotels",
        "destination": destination,
        "nights": nights,
        "options": [
            {"name": f"{destination} Central Stay", "price_total_cny": total, "style": "central midrange"},
            {"name": f"{destination} Budget Inn", "price_total_cny": int(total * 0.75), "style": "budget"},
        ],
        "within_budget": total <= max(1, budget),
        "summary": f"Hotel options found for {destination}; midrange estimate is CNY {total}.",
    }
    append_jsonl(EVENTS_FILE, {"tool": "search_hotels", "args": args, "result": payload})
    return _json(payload)


def get_weather(args: dict, context: ToolContext | None = None) -> str:
    destination = str(args.get("destination", "")).strip()
    date_window = str(args.get("date_window", "")).strip()
    if _contains_any(destination, ("南极", "antarctica")):
        payload = {
            "ok": True,
            "tool": "get_weather",
            "destination": destination,
            "date_window": date_window,
            "severe": True,
            "summary": "Antarctica weather and expedition windows are highly constrained; short-notice leisure travel is not realistic.",
            "packing": ["expedition-grade cold weather gear", "operator-specific equipment list"],
        }
    elif _contains_any(destination, ("日本", "东京", "大阪")):
        payload = {
            "ok": True,
            "tool": "get_weather",
            "destination": destination,
            "date_window": date_window,
            "summary": "Mild to warm seasonal weather, with possible rain depending on city and week.",
            "packing": ["light jacket", "comfortable walking shoes", "compact umbrella"],
        }
    else:
        payload = {
            "ok": True,
            "tool": "get_weather",
            "destination": destination,
            "date_window": date_window,
            "summary": "Seasonal conditions look generally manageable; check the exact forecast before departure.",
            "packing": ["layered clothing", "comfortable shoes"],
        }
    append_jsonl(EVENTS_FILE, {"tool": "get_weather", "args": args, "result": payload})
    return _json(payload)


def get_visa_info(args: dict, context: ToolContext | None = None) -> str:
    destination = str(args.get("destination", "")).strip()
    departure_date = str(args.get("departure_date", "")).strip()
    payload = {
        "ok": True,
        "tool": "get_visa_info",
        "destination": destination,
        "departure_date": departure_date,
        "passport_valid": True,
        "passport_allows_travel": True,
        "requires_replan": False,
        "requires_alternative": False,
        "summary": "Mock passport check passed. The traveler has a valid passport and can pass the basic passport requirement for this destination.",
        "lead_time_days": 0,
    }
    append_jsonl(EVENTS_FILE, {"tool": "get_visa_info", "args": args, "result": payload})
    return _json(payload)


def calc_budget(args: dict, context: ToolContext | None = None) -> str:
    budget = float(args.get("budget_cny") or 0)
    flight = float(args.get("flight_cny") or 0)
    hotel = float(args.get("hotel_cny") or 0)
    local = float(args.get("local_cny") or 0)
    food = float(args.get("food_cny") or 0)
    buffer = float(args.get("buffer_cny") or 0)
    total = flight + hotel + local + food + buffer
    payload = {
        "ok": True,
        "tool": "calc_budget",
        "budget_cny": budget,
        "breakdown": {
            "flight_cny": flight,
            "hotel_cny": hotel,
            "local_cny": local,
            "food_cny": food,
            "buffer_cny": buffer,
            "total_cny": total,
        },
        "within_budget": total <= budget if budget else None,
        "remaining_cny": budget - total if budget else None,
        "summary": f"Estimated total is CNY {int(total)} against budget CNY {int(budget)}.",
    }
    append_jsonl(EVENTS_FILE, {"tool": "calc_budget", "args": args, "result": payload})
    return _json(payload)


ToolFunc = Callable[[dict, ToolContext | None], str]

TOOL_REGISTRY: dict[str, ToolFunc] = {
    "search_flights": search_flights,
    "search_hotels": search_hotels,
    "get_weather": get_weather,
    "get_visa_info": get_visa_info,
    "calc_budget": calc_budget,
}
