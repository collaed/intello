"""Conversation memory, user preferences, and cross-session learning."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass

DB_PATH = os.environ.get("MEMORY_DB", "/data/memory.db")


@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT DEFAULT 'default',
                created_at REAL,
                updated_at REAL,
                summary TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT DEFAULT '',
                cost REAL DEFAULT 0,
                ts REAL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id TEXT PRIMARY KEY,
                preferred_models TEXT DEFAULT '[]',
                tone TEXT DEFAULT 'brutally_honest',
                default_mode TEXT DEFAULT 'auto',
                custom_system_prompt TEXT DEFAULT '',
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS model_scores (
                model_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                rating REAL DEFAULT 0,
                uses INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                avg_latency REAL DEFAULT 0,
                updated_at REAL,
                PRIMARY KEY (model_id, task_type)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
        """)


init_db()


# --- Conversation Memory ---

def create_conversation(conv_id: str, user_id: str = "default") -> str:
    now = time.time()
    with _db() as conn:
        conn.execute("INSERT OR IGNORE INTO conversations (id, user_id, created_at, updated_at) VALUES (?,?,?,?)",
                     (conv_id, user_id, now, now))
    return conv_id


def add_message(conv_id: str, role: str, content: str, model: str = "", cost: float = 0) -> None:
    with _db() as conn:
        conn.execute("INSERT INTO messages (conversation_id, role, content, model, cost, ts) VALUES (?,?,?,?,?,?)",
                     (conv_id, role, content, model, cost, time.time()))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), conv_id))


def get_messages(conv_id: str, limit: int = 20) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT role, content, model, ts FROM messages WHERE conversation_id=? ORDER BY ts DESC LIMIT ?",
            (conv_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_summary(conv_id: str) -> str:
    with _db() as conn:
        row = conn.execute("SELECT summary FROM conversations WHERE id=?", (conv_id,)).fetchone()
    return row["summary"] if row else ""


def set_summary(conv_id: str, summary: str) -> None:
    with _db() as conn:
        conn.execute("UPDATE conversations SET summary=?, updated_at=? WHERE id=?",
                     (summary, time.time(), conv_id))


def list_conversations(user_id: str = "default", limit: int = 20) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, created_at, updated_at, summary FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


# --- Context Compression ---

def build_context(conv_id: str, max_messages: int = 10) -> str:
    """Build context string from summary + recent messages."""
    summary = get_summary(conv_id)
    messages = get_messages(conv_id, limit=max_messages)
    parts = []
    if summary:
        parts.append(f"[Previous conversation summary: {summary}]")
    for m in messages:
        prefix = "User" if m["role"] == "user" else f"Assistant ({m.get('model', '')})"
        parts.append(f"{prefix}: {m['content']}")
    return "\n\n".join(parts)


def needs_compression(conv_id: str, threshold: int = 15) -> bool:
    """Check if conversation has enough messages to warrant compression."""
    with _db() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM messages WHERE conversation_id=?", (conv_id,)).fetchone()
    return row["cnt"] > threshold


# --- User Preferences ---

def get_prefs(user_id: str = "default") -> dict:
    with _db() as conn:
        row = conn.execute("SELECT * FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return {"user_id": user_id, "preferred_models": [], "tone": "brutally_honest",
                "default_mode": "auto", "custom_system_prompt": ""}
    d = dict(row)
    d["preferred_models"] = json.loads(d["preferred_models"])
    return d


def set_prefs(user_id: str = "default", **kwargs) -> None:
    current = get_prefs(user_id)
    current.update(kwargs)
    if isinstance(current.get("preferred_models"), list):
        current["preferred_models"] = json.dumps(current["preferred_models"])
    with _db() as conn:
        conn.execute("""INSERT OR REPLACE INTO user_prefs
                        (user_id, preferred_models, tone, default_mode, custom_system_prompt, updated_at)
                        VALUES (?,?,?,?,?,?)""",
                     (user_id, current["preferred_models"], current.get("tone", "brutally_honest"),
                      current.get("default_mode", "auto"), current.get("custom_system_prompt", ""),
                      time.time()))


# --- Cross-Session Learning ---

def record_model_result(model_id: str, task_type: str, success: bool, latency: float = 0, rating: float = 0) -> None:
    """Record a model's performance for learning."""
    with _db() as conn:
        row = conn.execute("SELECT * FROM model_scores WHERE model_id=? AND task_type=?",
                           (model_id, task_type)).fetchone()
        if row:
            uses = row["uses"] + 1
            failures = row["failures"] + (0 if success else 1)
            # Running average
            avg_lat = (row["avg_latency"] * row["uses"] + latency) / uses
            avg_rating = (row["rating"] * row["uses"] + rating) / uses if rating else row["rating"]
            conn.execute("""UPDATE model_scores SET uses=?, failures=?, avg_latency=?, rating=?, updated_at=?
                           WHERE model_id=? AND task_type=?""",
                         (uses, failures, avg_lat, avg_rating, time.time(), model_id, task_type))
        else:
            conn.execute("""INSERT INTO model_scores (model_id, task_type, rating, uses, failures, avg_latency, updated_at)
                           VALUES (?,?,?,1,?,?,?)""",
                         (model_id, task_type, rating, 0 if success else 1, latency, time.time()))


def get_model_scores() -> dict[str, dict]:
    """Get learned model performance scores. Returns {model_id: {task_type: {rating, uses, failures}}}."""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM model_scores").fetchall()
    scores = {}
    for r in rows:
        scores.setdefault(r["model_id"], {})[r["task_type"]] = {
            "rating": r["rating"], "uses": r["uses"],
            "failures": r["failures"], "avg_latency": r["avg_latency"],
        }
    return scores


def get_score_bonus(model_id: str, task_type: str) -> float:
    """Return a score adjustment based on learned performance. Positive = boost, negative = penalize."""
    with _db() as conn:
        row = conn.execute("SELECT * FROM model_scores WHERE model_id=? AND task_type=?",
                           (model_id, task_type)).fetchone()
    if not row or row["uses"] < 3:
        return 0.0  # Not enough data
    # Failure rate penalty
    fail_rate = row["failures"] / row["uses"] if row["uses"] > 0 else 0
    bonus = -20 * fail_rate  # Up to -20 for 100% failure
    # Rating bonus (if user has rated)
    if row["rating"] > 0:
        bonus += (row["rating"] - 3) * 5  # +/-10 for 1-5 scale centered on 3
    return bonus
