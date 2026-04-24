"""Webhook system — lets external services trigger L'Intello actions."""
import json
import os
import sqlite3
import time
import hashlib
import hmac
from contextlib import contextmanager

DB_PATH = os.environ.get("WEBHOOK_DB", "/data/webhooks.db")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


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
        conn.execute("""CREATE TABLE IF NOT EXISTS webhooks (
            hook_id TEXT PRIMARY KEY,
            name TEXT,
            action TEXT,
            config JSON DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            last_triggered REAL DEFAULT 0,
            trigger_count INTEGER DEFAULT 0,
            created_at REAL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS webhook_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hook_id TEXT,
            payload JSON,
            result TEXT,
            ts REAL
        )""")


_init()


def create_webhook(hook_id: str, name: str, action: str, config: dict = None) -> dict:
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO webhooks (hook_id, name, action, config, created_at) VALUES (?,?,?,?,?)",
                     (hook_id, name, action, json.dumps(config or {}), time.time()))
    return get_webhook(hook_id)


def get_webhook(hook_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM webhooks WHERE hook_id=?", (hook_id,)).fetchone()
    if not row: return None
    d = dict(row)
    d["config"] = json.loads(d["config"])
    return d


def list_webhooks() -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM webhooks ORDER BY created_at DESC").fetchall()
    return [{**dict(r), "config": json.loads(r["config"])} for r in rows]


def log_trigger(hook_id: str, payload: dict, result: str):
    with _db() as conn:
        conn.execute("INSERT INTO webhook_log (hook_id, payload, result, ts) VALUES (?,?,?,?)",
                     (hook_id, json.dumps(payload), result[:2000], time.time()))
        conn.execute("UPDATE webhooks SET last_triggered=?, trigger_count=trigger_count+1 WHERE hook_id=?",
                     (time.time(), hook_id))


def verify_signature(payload: bytes, signature: str) -> bool:
    expected = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def delete_webhook(hook_id: str):
    with _db() as conn:
        conn.execute("DELETE FROM webhooks WHERE hook_id=?", (hook_id,))
