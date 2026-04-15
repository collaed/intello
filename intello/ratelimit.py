"""Rate limit tracking — persists daily usage counts per provider."""
import json
import os
from datetime import date

USAGE_FILE = os.environ.get("USAGE_FILE", "/data/usage.json")


def _load() -> dict:
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)


def _today() -> str:
    return date.today().isoformat()


def get_usage(model_id: str) -> int:
    """Return today's request count for a model."""
    data = _load()
    day = data.get(_today(), {})
    return day.get(model_id, 0)


def record_usage(model_id: str) -> int:
    """Increment and return today's count for a model."""
    data = _load()
    today = _today()
    # Prune old days (keep only today)
    data = {today: data.get(today, {})}
    data[today][model_id] = data[today].get(model_id, 0) + 1
    _save(data)
    return data[today][model_id]


def remaining(model_id: str, daily_limit: int) -> int:
    """Return remaining requests today. -1 = unlimited."""
    if daily_limit <= 0:
        return -1
    return max(0, daily_limit - get_usage(model_id))
