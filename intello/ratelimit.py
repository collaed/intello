"""Rate limit tracking — SQLite-backed for concurrent access safety."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import date

DB_PATH = os.environ.get("RATELIMIT_DB", "/data/ratelimit.db")


@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init():
    with _db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS usage (
            day TEXT NOT NULL,
            model_id TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (day, model_id)
        )""")


_init()


def _today() -> str:
    return date.today().isoformat()


def _load() -> dict:
    """Compat: return dict format for usage history endpoint."""
    with _db() as conn:
        rows = conn.execute("SELECT day, model_id, count FROM usage ORDER BY day DESC").fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r["day"], {})[r["model_id"]] = r["count"]
    return result


def get_usage(model_id: str) -> int:
    """Return today's request count for a model."""
    with _db() as conn:
        row = conn.execute("SELECT count FROM usage WHERE day=? AND model_id=?",
                           (_today(), model_id)).fetchone()
    return row["count"] if row else 0


def record_usage(model_id: str) -> int:
    """Increment and return today's count for a model. Atomic via UPSERT."""
    today = _today()
    with _db() as conn:
        conn.execute("""INSERT INTO usage (day, model_id, count) VALUES (?, ?, 1)
                        ON CONFLICT(day, model_id) DO UPDATE SET count = count + 1""",
                     (today, model_id))
        row = conn.execute("SELECT count FROM usage WHERE day=? AND model_id=?",
                           (today, model_id)).fetchone()
    return row["count"] if row else 1


def remaining(model_id: str, daily_limit: int) -> int:
    """Return remaining requests today. -1 = unlimited."""
    if daily_limit <= 0:
        return -1
    return max(0, daily_limit - get_usage(model_id))
