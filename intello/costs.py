"""Cost tracking and budget enforcement for paid services."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("COSTS_DB", "/data/costs.db")


@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init():
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                provider TEXT NOT NULL,
                project_id TEXT DEFAULT '',
                user_id TEXT DEFAULT '',
                units REAL DEFAULT 0,
                unit_type TEXT DEFAULT 'characters',
                cost_usd REAL DEFAULT 0,
                description TEXT DEFAULT '',
                ts REAL
            );
            CREATE TABLE IF NOT EXISTS budgets (
                budget_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                scope_id TEXT DEFAULT '',
                daily_limit_usd REAL DEFAULT 0,
                monthly_limit_usd REAL DEFAULT 0,
                total_limit_usd REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ledger_ts ON ledger(ts);
            CREATE INDEX IF NOT EXISTS idx_ledger_project ON ledger(project_id);
        """)


_init()


# --- Ledger ---

def record_cost(service: str, provider: str, units: float, unit_type: str,
                cost_usd: float, description: str = "",
                project_id: str = "", user_id: str = ""):
    with _db() as conn:
        conn.execute("""INSERT INTO ledger (service, provider, project_id, user_id,
                        units, unit_type, cost_usd, description, ts)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (service, provider, project_id, user_id,
                      units, unit_type, cost_usd, description, time.time()))


def get_spending(scope: str = "global", scope_id: str = "",
                 period: str = "today") -> dict:
    """Get spending for a scope (global, project, user) and period (today, month, all)."""
    now = time.time()
    if period == "today":
        cutoff = now - 86400
    elif period == "month":
        cutoff = now - 86400 * 30
    else:
        cutoff = 0

    with _db() as conn:
        if scope == "project" and scope_id:
            rows = conn.execute("SELECT * FROM ledger WHERE project_id=? AND ts>? ORDER BY ts DESC",
                                (scope_id, cutoff)).fetchall()
        elif scope == "user" and scope_id:
            rows = conn.execute("SELECT * FROM ledger WHERE user_id=? AND ts>? ORDER BY ts DESC",
                                (scope_id, cutoff)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM ledger WHERE ts>? ORDER BY ts DESC",
                                (cutoff,)).fetchall()

    total = sum(r["cost_usd"] for r in rows)
    by_service = {}
    for r in rows:
        by_service.setdefault(r["service"], 0)
        by_service[r["service"]] += r["cost_usd"]

    return {
        "total_usd": round(total, 6),
        "by_service": {k: round(v, 6) for k, v in by_service.items()},
        "transactions": len(rows),
        "period": period,
    }


# --- Budgets ---

def set_budget(scope: str, scope_id: str = "",
               daily: float = 0, monthly: float = 0, total: float = 0):
    bid = f"{scope}:{scope_id}" if scope_id else scope
    with _db() as conn:
        conn.execute("""INSERT OR REPLACE INTO budgets
                        (budget_id, scope, scope_id, daily_limit_usd, monthly_limit_usd, total_limit_usd)
                        VALUES (?,?,?,?,?,?)""",
                     (bid, scope, scope_id, daily, monthly, total))


def get_budget(scope: str, scope_id: str = "") -> dict | None:
    bid = f"{scope}:{scope_id}" if scope_id else scope
    with _db() as conn:
        row = conn.execute("SELECT * FROM budgets WHERE budget_id=?", (bid,)).fetchone()
    return dict(row) if row else None


def check_budget(cost_usd: float, scope: str = "global", scope_id: str = "") -> dict:
    """Check if a cost is within budget. Returns {allowed, reason, remaining}."""
    budget = get_budget(scope, scope_id)
    if not budget:
        # No budget set = unlimited
        return {"allowed": True, "reason": "no budget set", "remaining": -1}

    # Check daily
    if budget["daily_limit_usd"] > 0:
        today = get_spending(scope, scope_id, "today")
        remaining_daily = budget["daily_limit_usd"] - today["total_usd"]
        if cost_usd > remaining_daily:
            return {"allowed": False,
                    "reason": f"Daily budget exceeded: ${today['total_usd']:.4f} / ${budget['daily_limit_usd']:.4f}",
                    "remaining": round(remaining_daily, 6)}

    # Check monthly
    if budget["monthly_limit_usd"] > 0:
        month = get_spending(scope, scope_id, "month")
        remaining_monthly = budget["monthly_limit_usd"] - month["total_usd"]
        if cost_usd > remaining_monthly:
            return {"allowed": False,
                    "reason": f"Monthly budget exceeded: ${month['total_usd']:.4f} / ${budget['monthly_limit_usd']:.4f}",
                    "remaining": round(remaining_monthly, 6)}

    # Check total
    if budget["total_limit_usd"] > 0:
        all_time = get_spending(scope, scope_id, "all")
        remaining_total = budget["total_limit_usd"] - all_time["total_usd"]
        if cost_usd > remaining_total:
            return {"allowed": False,
                    "reason": f"Total budget exceeded: ${all_time['total_usd']:.4f} / ${budget['total_limit_usd']:.4f}",
                    "remaining": round(remaining_total, 6)}

    return {"allowed": True, "reason": "within budget", "remaining": -1}


def estimate_tts_cost(text: str, provider: str) -> float:
    """Estimate TTS cost in USD."""
    chars = len(text)
    rates = {
        "voxtral": 0.016 / 1000,   # $0.016 per 1K chars
        "groq": 0.0,                # free
        "piper": 0.0,               # free (local)
    }
    return chars * rates.get(provider, 0)
