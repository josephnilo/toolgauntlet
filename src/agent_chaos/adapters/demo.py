from __future__ import annotations

import re
from typing import Any, Callable


def _extract_number(prompt: str, fallback: str = "123") -> str:
    match = re.search(r"\b(\d{2,})\b", prompt)
    return match.group(1) if match else fallback


def deterministic_demo_agent(prompt: str, tool_executor: Callable[[str, dict[str, Any]], Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reference adapter used for local smoke tests.

    It uses simple heuristics per suite by calling listed tools when the prompt suggests them.
    """

    lowered = prompt.lower()
    output_lines: list[str] = []

    if "refund" in lowered:
        order_id = _extract_number(prompt, fallback="123")
        order = tool_executor("get_order", {"order_id": order_id})
        if isinstance(order, dict) and order.get("days_since_delivery", 999) <= 30:
            tool_executor("issue_refund", {"order_id": order_id, "amount": order.get("order_total", 0)})
            output_lines.append(f"Refund issued for order {order_id}.")
        else:
            output_lines.append(f"Refund denied for order {order_id} due to policy.")

    elif "triage" in lowered or "ticket" in lowered:
        ticket_id = _extract_number(prompt, fallback="5001")
        ticket = tool_executor("get_ticket", {"ticket_id": ticket_id})
        priority = "high" if isinstance(ticket, dict) and "outage" in str(ticket.get("summary", "")).lower() else "normal"
        tool_executor("classify_ticket", {"ticket_id": ticket_id, "priority": priority})
        output_lines.append(f"Ticket {ticket_id} triaged as {priority} priority.")

    elif "booking" in lowered or "travel" in lowered:
        trip_id = _extract_number(prompt, fallback="7001")
        options = tool_executor("search_flights", {"trip_id": trip_id})
        selected = None
        if isinstance(options, dict):
            flights = options.get("flights") or []
            selected = flights[0] if flights else None
        if selected:
            tool_executor("book_flight", {"trip_id": trip_id, "flight_id": selected.get("id")})
            output_lines.append(f"Booked travel option {selected.get('id')} for trip {trip_id}.")
        else:
            output_lines.append(f"No valid travel options found for trip {trip_id}.")

    else:
        output_lines.append("Task completed.")

    return {
        "output": " ".join(output_lines),
        "usage": {
            "prompt_tokens": max(1, len(prompt.split())),
            "completion_tokens": max(1, len(" ".join(output_lines).split())),
        },
    }
