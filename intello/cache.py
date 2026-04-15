"""Semantic cache — stores and retrieves responses by prompt similarity."""
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("CACHE_DB", "/data/cache.db")


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
        conn.execute("""CREATE TABLE IF NOT EXISTS cache (
            prompt_hash TEXT PRIMARY KEY,
            prompt TEXT,
            task_type TEXT,
            response TEXT,
            provider TEXT,
            model TEXT,
            cost REAL DEFAULT 0,
            created_at REAL,
            hits INTEGER DEFAULT 0
        )""")


_init()


def _hash(text: str) -> str:
    """Normalize and hash a prompt for exact-match lookup."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity (Jaccard). No external deps needed."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def get_cached(prompt: str, task_type: str, threshold: float = 0.75, max_age_hours: int = 168) -> dict | None:
    """Look up cache. Returns dict with response/provider/model or None."""
    h = _hash(prompt)
    cutoff = time.time() - (max_age_hours * 3600)

    with _db() as conn:
        # Try exact match first
        row = conn.execute("SELECT * FROM cache WHERE prompt_hash=? AND created_at>?",
                           (h, cutoff)).fetchone()
        if row:
            conn.execute("UPDATE cache SET hits=hits+1 WHERE prompt_hash=?", (h,))
            return dict(row)

        # Fuzzy match: scan recent entries of same task type
        rows = conn.execute(
            "SELECT * FROM cache WHERE task_type=? AND created_at>? ORDER BY created_at DESC LIMIT 200",
            (task_type, cutoff)).fetchall()
        for row in rows:
            if _similarity(prompt, row["prompt"]) >= threshold:
                conn.execute("UPDATE cache SET hits=hits+1 WHERE prompt_hash=?", (row["prompt_hash"],))
                return dict(row)

    return None


def store(prompt: str, task_type: str, response: str, provider: str, model: str, cost: float):
    """Store a response in cache."""
    h = _hash(prompt)
    with _db() as conn:
        conn.execute("""INSERT OR REPLACE INTO cache
                        (prompt_hash, prompt, task_type, response, provider, model, cost, created_at, hits)
                        VALUES (?,?,?,?,?,?,?,?,0)""",
                     (h, prompt, task_type, response, provider, model, cost, time.time()))


def get_stats() -> dict:
    """Return cache statistics."""
    with _db() as conn:
        row = conn.execute("SELECT COUNT(*) as entries, SUM(hits) as total_hits, SUM(cost) as saved_cost FROM cache").fetchone()
    return {"entries": row["entries"] or 0, "total_hits": row["total_hits"] or 0,
            "estimated_savings": row["saved_cost"] or 0.0}
