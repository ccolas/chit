"""
Token cost tracking for Chit.
Tracks usage and costs per model, saved to costs.txt.
"""

import json
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Optional

COSTS_FILE = Path(__file__).parent / "costs.txt"

# Token prices per 1M tokens (input, output)
# Update these as pricing changes
TOKEN_PRICES = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Google via OpenRouter
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "google/gemini-2.0-flash-thinking-exp": (0.0, 0.0),  # free tier
    "google/gemini-pro": (0.125, 0.375),
    "google/gemini-1.5-pro": (1.25, 5.00),
    "google/gemini-1.5-flash": (0.075, 0.30),
    # Anthropic via OpenRouter
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3-opus": (15.00, 75.00),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    # Default fallback
    "default": (1.00, 3.00),
}


def _default_data() -> Dict:
    """Default cost data structure."""
    return {
        "total": {"input_tokens": 0, "output_tokens": 0, "cost": 0.0},
        "daily": {},
        "whisper": {"total_seconds": 0, "total_cost": 0.0, "daily": {}}
    }


def _load_costs() -> Dict:
    """Load costs from file."""
    if COSTS_FILE.exists():
        try:
            content = COSTS_FILE.read_text()
            data = json.loads(content)
            # Ensure whisper section exists (migration)
            if "whisper" not in data:
                data["whisper"] = {"total_seconds": 0, "total_cost": 0.0, "daily": {}}
            return data
        except (json.JSONDecodeError, IOError):
            pass
    return _default_data()


def _save_costs(data: Dict):
    """Save costs to file."""
    COSTS_FILE.write_text(json.dumps(data, indent=2))


def get_token_price(model: str) -> tuple:
    """Get (input_price, output_price) per 1M tokens for a model."""
    # Try exact match first
    if model in TOKEN_PRICES:
        return TOKEN_PRICES[model]

    # Try partial match (e.g., "openai/gpt-4o-mini" -> "gpt-4o-mini")
    for key, price in TOKEN_PRICES.items():
        if key in model or model.endswith(key):
            return price

    return TOKEN_PRICES["default"]


def track_usage(model: str, input_tokens: int, output_tokens: int):
    """Track token usage and cost."""
    data = _load_costs()
    today = date.today().isoformat()

    # Get prices
    input_price, output_price = get_token_price(model)
    cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000

    # Update total
    data["total"]["input_tokens"] += input_tokens
    data["total"]["output_tokens"] += output_tokens
    data["total"]["cost"] += cost

    # Update daily
    if today not in data["daily"]:
        data["daily"][today] = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}

    data["daily"][today]["input_tokens"] += input_tokens
    data["daily"][today]["output_tokens"] += output_tokens
    data["daily"][today]["cost"] += cost

    _save_costs(data)

    return cost


def track_whisper_usage(duration_seconds: float):
    """Track OpenAI Whisper API usage. $0.006 per minute."""
    data = _load_costs()
    today = date.today().isoformat()

    cost = duration_seconds * 0.006 / 60  # $0.006 per minute

    data["whisper"]["total_seconds"] += duration_seconds
    data["whisper"]["total_cost"] += cost

    if today not in data["whisper"]["daily"]:
        data["whisper"]["daily"][today] = {"seconds": 0, "cost": 0.0}

    data["whisper"]["daily"][today]["seconds"] += duration_seconds
    data["whisper"]["daily"][today]["cost"] += cost

    _save_costs(data)
    return cost


def get_costs() -> Dict:
    """Get current cost data."""
    return _load_costs()


def get_today_cost() -> float:
    """Get today's total cost."""
    data = _load_costs()
    today = date.today().isoformat()
    if today in data["daily"]:
        return data["daily"][today]["cost"]
    return 0.0


def get_total_cost() -> float:
    """Get all-time total cost."""
    data = _load_costs()
    return data["total"]["cost"]


def format_costs() -> str:
    """Format costs for display."""
    data = _load_costs()
    today = date.today().isoformat()

    # LLM costs
    total = data["total"]
    daily = data["daily"].get(today, {"input_tokens": 0, "output_tokens": 0, "cost": 0.0})

    # Whisper costs
    whisper = data.get("whisper", {"total_seconds": 0, "total_cost": 0.0, "daily": {}})
    whisper_daily = whisper.get("daily", {}).get(today, {"seconds": 0, "cost": 0.0})

    today_total = daily['cost'] + whisper_daily.get('cost', 0)
    all_time_total = total['cost'] + whisper.get('total_cost', 0)

    lines = [
        f"Today: ${today_total:.4f} (LLM: ${daily['cost']:.4f}, Whisper: ${whisper_daily.get('cost', 0):.4f})",
        f"Total: ${all_time_total:.4f} (LLM: ${total['cost']:.4f}, Whisper: ${whisper.get('total_cost', 0):.4f})",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print("Chit Cost Tracker")
    print("-" * 30)
    print(format_costs())
