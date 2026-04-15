"""Semantic cache — stores and retrieves responses by embedding similarity."""
import functools
import hashlib
import json
import os
import pickle
import sqlite3
import time
from contextlib import contextmanager

import numpy as np

DB_PATH = os.environ.get("CACHE_DB", "/data/cache.db")


@functools.lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def _embed(text: str) -> bytes:
    vec = _embedder().encode(text, normalize_embeddings=True)
    return pickle.dumps(vec)


def _cosine_sim(a: bytes, b: bytes) -> float:
    va = pickle.loads(a)
    vb = pickle.loads(b)
    return float(np.dot(va, vb))


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
            embedding BLOB,
            created_at REAL,
            hits INTEGER DEFAULT 0
        )""")
        # Migrate: add embedding column if missing
        try:
            conn.execute("SELECT embedding FROM cache LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE cache ADD COLUMN embedding BLOB")


_init()


def _hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def get_cached(prompt: str, task_type: str, threshold: float = 0.82, max_age_hours: int = 168) -> dict | None:
    """Look up cache by exact hash then semantic similarity."""
    h = _hash(prompt)
    cutoff = time.time() - (max_age_hours * 3600)

    with _db() as conn:
        # Exact match
        row = conn.execute("SELECT * FROM cache WHERE prompt_hash=? AND created_at>?",
                           (h, cutoff)).fetchone()
        if row:
            conn.execute("UPDATE cache SET hits=hits+1 WHERE prompt_hash=?", (h,))
            return dict(row)

        # Semantic match
        rows = conn.execute(
            "SELECT * FROM cache WHERE task_type=? AND created_at>? AND embedding IS NOT NULL ORDER BY created_at DESC LIMIT 200",
            (task_type, cutoff)).fetchall()
        if rows:
            prompt_emb = _embed(prompt)
            best_score = 0
            best_row = None
            for row in rows:
                score = _cosine_sim(prompt_emb, row["embedding"])
                if score > best_score:
                    best_score = score
                    best_row = row
            if best_score >= threshold and best_row:
                conn.execute("UPDATE cache SET hits=hits+1 WHERE prompt_hash=?", (best_row["prompt_hash"],))
                return dict(best_row)

    return None


def store(prompt: str, task_type: str, response: str, provider: str, model: str, cost: float):
    """Store a response with its embedding."""
    h = _hash(prompt)
    emb = _embed(prompt)
    with _db() as conn:
        conn.execute("""INSERT OR REPLACE INTO cache
                        (prompt_hash, prompt, task_type, response, provider, model, cost, embedding, created_at, hits)
                        VALUES (?,?,?,?,?,?,?,?,?,0)""",
                     (h, prompt, task_type, response, provider, model, cost, emb, time.time()))


def get_stats() -> dict:
    with _db() as conn:
        row = conn.execute("SELECT COUNT(*) as entries, SUM(hits) as total_hits, SUM(cost) as saved_cost FROM cache").fetchone()
    return {"entries": row["entries"] or 0, "total_hits": row["total_hits"] or 0,
            "estimated_savings": row["saved_cost"] or 0.0}
