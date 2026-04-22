"""Async task runner — wraps any long-running operation into a pollable job."""
import asyncio
import json
import os
import time
import uuid
import traceback
from typing import Any, Callable

# In-memory job store (survives within container lifetime)
_jobs: dict[str, dict] = {}


def create_job(task_type: str, description: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "job_id": job_id,
        "type": task_type,
        "description": description,
        "status": "queued",
        "progress": 0,
        "result": None,
        "error": None,
        "created_at": time.time(),
        "completed_at": None,
    }
    return job_id


def get_job(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    if not job:
        return None
    # Strip large result from status check (fetch via /result endpoint)
    return {k: v for k, v in job.items() if k != "result" or v is None}


def get_job_result(job_id: str) -> Any:
    job = _jobs.get(job_id)
    if not job or job["status"] != "complete":
        return None
    return job["result"]


def update_job(job_id: str, **kwargs):
    if job_id in _jobs:
        _jobs[job_id].update(kwargs)


async def run_async(job_id: str, coro):
    """Run a coroutine as a background job."""
    try:
        _jobs[job_id]["status"] = "processing"
        result = await coro
        _jobs[job_id]["status"] = "complete"
        _jobs[job_id]["result"] = result
        _jobs[job_id]["progress"] = 100
        _jobs[job_id]["completed_at"] = time.time()
    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
        _jobs[job_id]["completed_at"] = time.time()


def list_jobs(limit: int = 20) -> list[dict]:
    jobs = sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)[:limit]
    return [{k: v for k, v in j.items() if k != "result"} for j in jobs]
