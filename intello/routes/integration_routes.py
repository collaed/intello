"""Integration routes — scheduler, webhooks, image gen, costs, backup, jobs, templates."""
import asyncio
import json
import os
import shutil

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

from intello import scheduler
from intello import imagegen
from intello import webhooks
from intello import costs
from intello import jobs as jobsys
from intello import ratelimit
from intello import ocr
from intello import speech

router = APIRouter(tags=["integrations"])


# --- Scheduled Tasks ---

@router.get("/api/scheduler/tasks")
async def scheduler_list():
    return scheduler.list_tasks()


@router.post("/api/scheduler/tasks")
async def scheduler_create(name: str = Form(...), prompt: str = Form(...), schedule: str = Form("daily")):
    import uuid
    return scheduler.create_task(uuid.uuid4().hex[:8], name, prompt, schedule)


@router.delete("/api/scheduler/tasks/{task_id}")
async def scheduler_delete(task_id: str):
    scheduler.delete_task(task_id)
    return {"ok": True}


# --- Image Generation ---

@router.post("/api/v1/image/generate")
async def image_gen(prompt: str = Form(...), style: str = Form("")):
    from intello.web import _providers
    return await imagegen.generate_image(prompt, _providers, style)


# --- Costs ---

@router.get("/api/costs")
async def costs_summary():
    return {
        "today": costs.get_spending("global", "", "today"),
        "month": costs.get_spending("global", "", "month"),
        "all_time": costs.get_spending("global", "", "all"),
    }


@router.get("/api/costs/project/{project_id}")
async def costs_project(project_id: str):
    return costs.get_spending("project", project_id, "all")


@router.post("/api/costs/budget")
async def set_budget(scope: str = Form("global"), scope_id: str = Form(""),
                     daily: float = Form(0), monthly: float = Form(0), total: float = Form(0)):
    costs.set_budget(scope, scope_id, daily, monthly, total)
    return {"ok": True, "budget": costs.get_budget(scope, scope_id)}


@router.get("/api/costs/budget")
async def get_budget(scope: str = "global", scope_id: str = ""):
    return costs.get_budget(scope, scope_id) or {"message": "No budget set (unlimited)"}


# --- Webhooks ---

@router.get("/api/webhooks")
async def webhooks_list():
    return webhooks.list_webhooks()


@router.post("/api/webhooks")
async def webhooks_create(name: str = Form(...), action: str = Form("chat"), config: str = Form("{}")):
    import uuid
    return webhooks.create_webhook(uuid.uuid4().hex[:8], name, action, json.loads(config))


@router.post("/api/webhooks/{hook_id}/trigger")
async def webhook_trigger(hook_id: str, request: Request):
    from intello.web import _providers
    from intello.router import build_plan
    from intello.backends import execute
    hook = webhooks.get_webhook(hook_id)
    if not hook or not hook["enabled"]:
        return {"error": "Webhook not found or disabled"}
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    prompt = body.get("prompt", hook["config"].get("default_prompt", ""))
    if not prompt:
        return {"error": "No prompt"}
    plan = build_plan(prompt, _providers, interactive=False)
    if not plan.primary:
        return {"error": "No providers"}
    result = await execute(plan.primary, prompt, max_tokens=body.get("max_tokens", 2000))
    webhooks.log_trigger(hook_id, body, result.content if not result.degraded else "Failed")
    return {"content": result.content, "provider": result.provider_name, "model": result.model_id, "cost": result.cost}


@router.delete("/api/webhooks/{hook_id}")
async def webhook_delete(hook_id: str):
    webhooks.delete_webhook(hook_id)
    return {"ok": True}


# --- Jobs ---

@router.get("/api/jobs")
async def jobs_list():
    return jobsys.list_jobs()


@router.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = jobsys.get_job(job_id)
    if not job:
        return {"error": "Job not found"}
    return job


@router.get("/api/jobs/{job_id}/result")
async def job_result(job_id: str):
    result = jobsys.get_job_result(job_id)
    if result is None:
        job = jobsys.get_job(job_id)
        if not job:
            return {"error": "Job not found"}
        return {"error": f"Job status: {job['status']}"}
    if isinstance(result, dict) and result.get("audio_path"):
        path = result["audio_path"]
        if os.path.exists(path):
            with open(path, "rb") as f:
                return Response(f.read(), media_type="audio/wav",
                                headers={"Content-Disposition": "attachment; filename=speech.wav"})
    return result


# --- Backup ---

@router.get("/api/backup")
async def backup():
    import tarfile, io
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ["api_keys.json", "usage.json", "memory.db", "cache.db",
                      "literary.db", "scheduler.db", "webhooks.db", "versions.db", "ocr_jobs.db", "costs.db"]:
            path = f"/data/{name}"
            if os.path.exists(path):
                tar.add(path, arcname=name)
    buf.seek(0)
    return Response(buf.read(), media_type="application/gzip",
                    headers={"Content-Disposition": "attachment; filename=intello_backup.tar.gz"})


# --- Usage ---

@router.get("/api/usage/history")
async def usage_history():
    from intello.web import _providers
    usage = ratelimit._load()
    current = {}
    for p in _providers:
        if p.available:
            current[p.model_id] = {"name": p.name, "used": ratelimit.get_usage(p.model_id),
                                    "limit": p.daily_limit, "remaining": ratelimit.remaining(p.model_id, p.daily_limit)}
    return {"history": usage, "today": current}


# --- Templates ---

PROMPT_TEMPLATES = {
    "analyze_pacing": {"name": "Analyze Pacing", "prompt": "Analyze the pacing of chapter {chapter}. Where is it too slow or fast?"},
    "character_check": {"name": "Character Consistency", "prompt": "Check {character} for consistency across all chapters."},
    "show_not_tell": {"name": "Show Not Tell", "prompt": "Find all instances of telling instead of showing in chapter {chapter}."},
    "tighten_prose": {"name": "Tighten Prose", "prompt": "Tighten the prose in lines {start}-{end}. Remove unnecessary words."},
    "expand_scene": {"name": "Expand Scene", "prompt": "Expand the scene at lines {start}-{end} with more sensory detail."},
    "blurb": {"name": "Generate Blurb", "prompt": "Write a compelling back-cover blurb for this book."},
    "chapter_summary": {"name": "Chapter Summary", "prompt": "Summarize each chapter in one sentence."},
}


@router.get("/api/templates")
async def templates():
    return PROMPT_TEMPLATES


# --- Status ---

@router.get("/api/v1/status")
async def status():
    from intello.web import _providers
    from intello.models import Tier
    avail = [p for p in _providers if p.available]
    free = [p for p in avail if p.tier == Tier.FREE]
    return {
        "available": len(avail) > 0,
        "providers": [{"name": p.name, "model": p.model_id, "tier": p.tier.value,
                       "available": p.available, "provider": p.provider} for p in _providers],
        "total_available": len(avail),
        "free_available": len(free),
        "ocr": {
            "available": shutil.which("tesseract") is not None,
            "engines": [
                {"name": "tesseract", "type": "local", "available": shutil.which("tesseract") is not None},
                {"name": "ocr.space", "type": "cloud_free", "available": True},
                {"name": "gemini_vision", "type": "llm", "available": any(
                    p.available and p.provider == "google" for p in _providers)},
            ],
            "languages": ocr.get_languages(),
            "quality_modes": ["fast", "auto", "best"],
        },
        "speech": {
            "tts_available": speech.tts_available(),
            "tts_engine": "piper",
            "tts_voices": [v["id"] for v in speech.get_available_voices()],
            "stt_provider": "groq",
            "stt_model": "whisper-large-v3-turbo",
            "stt_daily_limit_seconds": 28800,
        },
    }


@router.get("/api/health")
async def health():
    """Health check — verifies all critical subsystems."""
    checks = {}

    # Tesseract
    checks["tesseract"] = shutil.which("tesseract") is not None

    # SQLite databases
    for name, path in [("cache", "/data/cache.db"), ("memory", "/data/memory.db"),
                        ("ocr_jobs", "/data/ocr_jobs.db"), ("costs", "/data/costs.db")]:
        try:
            import sqlite3
            conn = sqlite3.connect(path, timeout=2)
            conn.execute("SELECT 1")
            conn.close()
            checks[f"db_{name}"] = True
        except Exception as e:
            checks[f"db_{name}"] = f"FAIL: {e}"

    # Disk space
    try:
        stat = os.statvfs("/data")
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        checks["disk_free_gb"] = round(free_gb, 1)
        checks["disk_ok"] = free_gb > 1.0
    except Exception:
        checks["disk_ok"] = False

    # API keys
    from intello.web import _providers
    keys_ok = sum(1 for p in _providers if p.available)
    checks["api_keys_valid"] = keys_ok
    checks["api_keys_total"] = len(_providers)

    # Piper TTS
    checks["piper_tts"] = speech.tts_available()

    # Overall
    critical = [checks.get("tesseract"), checks.get("disk_ok"),
                checks.get("db_cache"), checks.get("db_memory")]
    checks["healthy"] = all(c is True for c in critical) and keys_ok > 0

    return checks
