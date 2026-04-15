"""Scheduled tasks — recurring AI jobs."""
import asyncio
import json
import os
import time
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("SCHEDULER_DB", "/data/scheduler.db")


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
        conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            name TEXT,
            prompt TEXT,
            schedule TEXT,
            last_run REAL DEFAULT 0,
            next_run REAL DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            results JSON DEFAULT '[]',
            created_at REAL
        )""")


_init()

INTERVALS = {"hourly": 3600, "daily": 86400, "weekly": 604800}


def create_task(task_id: str, name: str, prompt: str, schedule: str = "daily") -> dict:
    now = time.time()
    interval = INTERVALS.get(schedule, 86400)
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO tasks (task_id, name, prompt, schedule, next_run, created_at) VALUES (?,?,?,?,?,?)",
                     (task_id, name, prompt, schedule, now + interval, now))
    return get_task(task_id)


def get_task(task_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row: return None
    d = dict(row)
    d["results"] = json.loads(d["results"])
    return d


def list_tasks() -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY next_run").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["results"] = json.loads(d["results"])
        result.append(d)
    return result


def record_result(task_id: str, result: str):
    with _db() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not task: return
        results = json.loads(task["results"])
        results.append({"time": time.time(), "result": result[:2000]})
        results = results[-10:]  # keep last 10
        interval = INTERVALS.get(task["schedule"], 86400)
        conn.execute("UPDATE tasks SET last_run=?, next_run=?, results=? WHERE task_id=?",
                     (time.time(), time.time() + interval, json.dumps(results), task_id))


def get_due_tasks() -> list[dict]:
    now = time.time()
    with _db() as conn:
        rows = conn.execute("SELECT * FROM tasks WHERE enabled=1 AND next_run<=?", (now,)).fetchall()
    return [dict(r) for r in rows]


def delete_task(task_id: str):
    with _db() as conn:
        conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
