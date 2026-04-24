"""FastAPI web interface for L'Intello."""
import asyncio
import json
import os
import re
import shutil
import time
import uuid
from typing import Optional

import base64
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from intello.models import Tier
from intello.research import get_providers, probe_reference_sites
from intello.keys import discover_keys, validate_keys, add_key
from intello.router import build_plan
from intello.backends import execute, SYSTEM_DEFAULT
from intello import gdrive
from intello import ratelimit
from intello.pipeline import run_deep
from intello import memory
from intello import cache
from intello.chains import analyze_complexity, execute_chain
from intello.tools import TOOL_PROMPT_SUFFIX, detect_tool_call, execute_tool
from intello.guardrails import check_confidence
from intello.debate import run_debate
from intello import literary
from intello.craft import build_craft_prompt
from intello.guardrails import check_confidence, check_word_count
from intello import workflow as wf
from intello import writing_tools as wt
from intello import ocr
from intello import ocr_engines
from intello import scheduler
from intello import imagegen
from intello import webhooks
from intello import reconstruct as recon
from intello import jobs as jobsys

# Route modules (extracted from this file to slim it down)
from intello.routes.ocr_routes import router as ocr_router, compat_router as ocr_compat_router
from intello.routes.speech_routes import router as speech_router
from intello.routes.integration_routes import router as integration_router
from intello.routes.literary_routes import router as literary_router

app = FastAPI(title="L'Intello")

# Register route modules
app.include_router(ocr_router)
app.include_router(ocr_compat_router)
app.include_router(speech_router)
app.include_router(integration_router)
app.include_router(literary_router)

# Auth — all credentials from environment variables (NO hardcoded defaults)
import json as _json
_users_raw = os.environ.get("INTELLO_USERS", "")
if not _users_raw:
    log.warning("INTELLO_USERS not set — authentication disabled for Docker-internal only")
    USERS: dict[str, str] = {}
else:
    try:
        USERS = _json.loads(_users_raw)
    except Exception:
        log.error("INTELLO_USERS is not valid JSON")
        USERS = {}
TOKEN = os.environ.get("INTELLO_TOKEN", "")
if not TOKEN:
    log.warning("INTELLO_TOKEN not set — Bearer auth disabled")
PREMIUM_USERS = set(os.environ.get("INTELLO_PREMIUM_USERS", "").split(",")) - {""}

# Models restricted to specific users (everyone else gets them filtered out)
PREMIUM_MODELS = {
    "gemini-2.5-pro",
    "claude-sonnet-4-5",
    "gpt-4o",
    "grok-4-1-fast",
}
# PREMIUM_USERS is set above from env var


def _get_user(request: Request) -> str:
    """Extract current user from request."""
    # From Caddy forward_auth
    user = request.headers.get("X-Auth-User", "")
    if user:
        return user
    # From Basic auth
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            import base64
            decoded = base64.b64decode(auth[6:]).decode()
            return decoded.split(":", 1)[0]
        except Exception:
            log.warning("Suppressed exception", exc_info=True)
    # Docker internal = admin
    client_ip = request.client.host if request.client else ""
    if client_ip.startswith("172.") or client_ip == "127.0.0.1":
        return "ecb"
    return "anonymous"


def filter_providers_for_user(providers: list, user: str) -> list:
    """Filter out premium models for non-premium users."""
    if user in PREMIUM_USERS:
        return providers
    return [p for p in providers if not any(pm in p.model_id for pm in PREMIUM_MODELS)]


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Trust Docker internal network (other containers)
        client_ip = request.client.host if request.client else ""
        if client_ip.startswith("172.") or client_ip == "127.0.0.1":
            return await call_next(request)
        # Caddy forward_auth sets this header — trust it
        if request.headers.get("X-Auth-User"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        # Bearer token (for API clients like external clients)
        if auth.startswith("Bearer "):
            if TOKEN and auth[7:] == TOKEN:
                return await call_next(request)
        # Basic auth
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode()
                user, pwd = decoded.split(":", 1)
                if USERS.get(user) == pwd:
                    return await call_next(request)
            except Exception:
                pass
        # Cookie
        if TOKEN and request.cookies.get("intello_token") == TOKEN:
            return await call_next(request)
        # Query param
        if TOKEN and request.query_params.get("token") == TOKEN:
            return await call_next(request)
        # Login endpoint
        if request.url.path == "/login":
            return await call_next(request)
        # Login page for direct access (no auth proxy)
        if request.url.path in ("/", "/literary") and request.method == "GET":
            return HTMLResponse(_login_page())
        return Response("Unauthorized", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="Intello"'})


app.add_middleware(AuthMiddleware)

# CORS — restrict to same-origin only (no cross-site cookie attacks)
from starlette.middleware.cors import CORSMiddleware
from intello.log import log
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("INTELLO_ORIGIN", "")],  # empty = same-origin only
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == TOKEN:
        # Detect base path from request
        base = request.headers.get("X-Forwarded-Prefix", "")
        resp = RedirectResponse(base + "/", status_code=303)
        resp.set_cookie("intello_token", TOKEN, httponly=True, max_age=86400 * 30,
                        samesite="lax", path="/")
        return resp
    return HTMLResponse(_login_page("Wrong password"))


def _login_page(error=""):
    return f"""<!DOCTYPE html><html><head><title>L&#39;Intello Login</title>
<style>body{{background:#0f1117;color:#e4e4e7;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.box{{background:#1a1d27;padding:32px;border-radius:12px;border:1px solid #2a2d3a;text-align:center}}
input{{background:#0f1117;border:1px solid #2a2d3a;color:#e4e4e7;padding:10px;border-radius:6px;margin:8px 0;font-size:1rem}}
button{{background:#6366f1;color:#fff;border:none;padding:10px 24px;border-radius:6px;cursor:pointer;font-size:1rem}}
.err{{color:#ef4444;font-size:.85rem}}</style></head>
<body><div class="box"><h2>⚡ L'Intello</h2>
<form method="POST" action="login"><input type="password" name="password" placeholder="Password" autofocus>
<br><button type="submit">Login</button></form>
{f'<p class="err">{error}</p>' if error else ''}</div></body></html>"""

_providers = []


@app.on_event("startup")
async def startup():
    global _providers
    _providers = get_providers()
    discover_keys(_providers)
    await asyncio.gather(
        probe_reference_sites(),
        validate_keys(_providers),
    )
    # Preload sentence-transformer in background
    asyncio.get_event_loop().run_in_executor(None, cache._embedder)
    # Clean up stale OCR temp files from previous runs
    cleaned = ocr.cleanup_old_files(max_age_hours=1)
    if cleaned:
        print(f"Cleaned {cleaned} stale OCR temp files")


def _provider_dict(p):
    rem = ratelimit.remaining(p.model_id, p.daily_limit)
    return {
        "name": p.name, "model_id": p.model_id, "provider": p.provider,
        "tier": p.tier.value, "available": p.available,
        "env_key": p.env_key, "has_key": p.api_key is not None,
        "cost_per_1k_input": p.cost_per_1k_input,
        "cost_per_1k_output": p.cost_per_1k_output,
        "notes": p.notes,
        "daily_limit": p.daily_limit,
        "used_today": ratelimit.get_usage(p.model_id),
        "remaining": rem,
    }


@app.get("/api/providers")
async def api_providers():
    return [_provider_dict(p) for p in _providers]


@app.post("/api/key")
async def api_add_key(env_key: str = Form(...), value: str = Form(...)):
    add_key(_providers, env_key, value)
    await validate_keys(_providers)
    return {"ok": True}


# --- Google Drive OAuth ---

@app.get("/api/gdrive/status")
async def gdrive_status():
    return {"authenticated": gdrive.is_authenticated(),
            "configured": os.path.exists(gdrive.CREDENTIALS_PATH)}


@app.get("/api/gdrive/auth")
async def gdrive_auth(request: Request):
    redirect_uri = str(request.url_for("gdrive_callback"))
    url = gdrive.get_oauth_url(redirect_uri)
    if not url:
        return {"error": "Google Drive OAuth not configured. Place gdrive_credentials.json in /data/"}
    return RedirectResponse(url)


@app.get("/api/gdrive/callback")
async def gdrive_callback(request: Request, code: str):
    redirect_uri = str(request.url_for("gdrive_callback"))
    gdrive.exchange_code(code, redirect_uri)
    return RedirectResponse("/")


# --- Google Drive Browser ---

@app.get("/api/gdrive/browse")
async def api_gdrive_browse(folder_id: str = "root", q: str = ""):
    if not gdrive.is_authenticated():
        return {"error": "Not authenticated with Google Drive"}
    return gdrive.list_folder(folder_id, q)


@app.post("/api/gdrive/batch")
async def api_gdrive_batch(request: Request):
    """Fetch multiple files by ID. Body: {"file_ids": ["id1", "id2", ...]}"""
    body = await request.json()
    file_ids = body.get("file_ids", [])
    if not file_ids:
        return {"error": "No file_ids provided"}
    return gdrive.batch_fetch(file_ids)


@app.post("/api/reconstruct/{project_id}/ingest-gdrive")
async def api_recon_ingest_gdrive(project_id: str, request: Request):
    """Ingest multiple Google Drive files into a reconstruction project."""
    body = await request.json()
    file_ids = body.get("file_ids", [])
    if not file_ids:
        return {"error": "No file_ids"}

    files = gdrive.batch_fetch(file_ids)
    results = []
    for f in files:
        if f.get("error"):
            results.append({"name": f.get("name", "?"), "error": f["error"]})
            continue
        r = recon.ingest_version(project_id, f["name"], f["content"])
        results.append({"name": f["name"], **r})

    return {"ingested": len([r for r in results if "error" not in r]),
            "errors": len([r for r in results if "error" in r]),
            "results": results}


# --- Conversations & Memory ---

@app.get("/api/conversations")
async def api_conversations():
    return memory.list_conversations()


@app.get("/api/conversations/{conv_id}")
async def api_conversation(conv_id: str):
    return {"messages": memory.get_messages(conv_id, limit=50),
            "summary": memory.get_summary(conv_id)}


# --- User Preferences ---

@app.get("/api/prefs")
async def api_get_prefs():
    return memory.get_prefs()


@app.post("/api/prefs")
async def api_set_prefs(
    tone: Optional[str] = Form(None),
    default_mode: Optional[str] = Form(None),
    custom_system_prompt: Optional[str] = Form(None),
):
    kwargs = {}
    if tone is not None: kwargs["tone"] = tone
    if default_mode is not None: kwargs["default_mode"] = default_mode
    if custom_system_prompt is not None: kwargs["custom_system_prompt"] = custom_system_prompt
    memory.set_prefs(**kwargs)
    return {"ok": True}


# --- Feedback / Learning ---

@app.post("/api/feedback")
async def api_feedback(
    model_id: str = Form(...),
    task_type: str = Form(...),
    rating: int = Form(...),
):
    memory.record_model_result(model_id, task_type, success=True, rating=float(rating))
    return {"ok": True}


@app.get("/api/learning")
async def api_learning():
    return memory.get_model_scores()


@app.get("/api/cache/stats")
async def api_cache_stats():
    return cache.get_stats()


# --- Context Compression ---

async def _compress_context(conv_id: str):
    """Summarize old messages using a cheap fast model."""
    msgs = memory.get_messages(conv_id, limit=50)
    if len(msgs) < 10:
        return
    old_summary = memory.get_summary(conv_id)
    text_parts = []
    if old_summary:
        text_parts.append(f"Previous summary: {old_summary}")
    for m in msgs[:-5]:  # Keep last 5 raw, compress the rest
        text_parts.append(f"{m['role']}: {m['content'][:500]}")

    compress_prompt = (
        "Compress this conversation into a concise summary (max 300 words). "
        "Capture key topics, decisions, user preferences, and any important context. "
        "Be factual and dense.\n\n" + "\n".join(text_parts)
    )

    # Pick cheapest available model — prefer Cloudflare (background task, save Groq)
    for p in _providers:
        if p.available and p.provider in ("cloudflare", "mistral", "groq"):
            result = await execute(p, compress_prompt, max_tokens=500,
                                   system="You are a conversation summarizer. Be concise and factual.")
            if not result.degraded:
                memory.set_summary(conv_id, result.content)
                return


# --- Prompt handling ---

@app.post("/api/prompt")
async def api_prompt(
    prompt: str = Form(...),
    gdrive_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    confirm_paid: bool = Form(False),
    mode: Optional[str] = Form(None),
    conversation_id: Optional[str] = Form(None),
    async_mode: bool = Form(False),
    request: Request = None,
):
    # User-based model filtering
    user = _get_user(request) if request else "anonymous"
    user_providers = filter_providers_for_user(_providers, user)

    # Load user prefs
    prefs = memory.get_prefs()
    effective_mode = mode or prefs.get("default_mode", "auto")

    # System prompt from prefs
    sys_prompt = prefs.get("custom_system_prompt") or None
    if not sys_prompt:
        tone = prefs.get("tone", "brutally_honest")
        if tone != "brutally_honest":
            sys_prompt = f"You are a helpful AI assistant. Respond in a {tone} tone."

    # Conversation setup
    conv_id = conversation_id or str(uuid.uuid4())
    memory.create_conversation(conv_id)

    # Build prompt with file context
    parts = []
    if file and file.filename:
        content = (await file.read()).decode("utf-8", errors="replace")
        parts.append(f"--- Attached file: {file.filename} ---\n{content[:50_000]}")
    if gdrive_url and gdrive_url.strip():
        url = gdrive_url.strip()
        if gdrive.is_authenticated():
            text = gdrive.fetch_private(url)
        else:
            text = await gdrive.fetch_public(url)
        parts.append(f"--- Google Drive file ---\n{text}")

    # Add conversation context
    context = memory.build_context(conv_id, max_messages=10)
    if context:
        parts.append(f"--- Conversation context ---\n{context}")

    parts.append(prompt)
    full_prompt = "\n\n".join(parts)

    # Save user message
    memory.add_message(conv_id, "user", prompt)

    # Compress if needed (async, don't block)
    if memory.needs_compression(conv_id):
        asyncio.create_task(_compress_context(conv_id))

    plan = build_plan(full_prompt, user_providers)
    plan_info = {
        "task_type": plan.task_type.value,
        "estimated_tokens": plan.estimated_tokens,
        "primary": plan.primary.name if plan.primary else None,
        "fallbacks": [f.name for f in plan.fallbacks],
        "degraded": plan.degraded,
        "missing_keys": plan.missing_keys,
        "estimated_cost": plan.estimated_cost,
        "reasoning": plan.reasoning,
        "is_paid": plan.primary.tier == Tier.PAID if plan.primary else False,
        "conversation_id": conv_id,
    }

    if plan.degraded or not plan.primary:
        return {"plan": plan_info, "needs_confirmation": False,
                "error": "No providers available. Supply API keys to continue."}

    # Check cache (skip for deep mode — user wants fresh multi-model analysis)
    if effective_mode != "deep":
        cached = cache.get_cached(prompt, plan.task_type.value)
        if cached:
            memory.add_message(conv_id, "assistant", cached["response"], cached["model"], 0)
            plan_info["reasoning"] += "\n⚡ Cache hit — reusing previous response"
            return {
                "plan": plan_info, "needs_confirmation": False, "mode": "cached",
                "response": {
                    "provider": cached["provider"], "model": cached["model"],
                    "content": cached["response"],
                    "input_tokens": 0, "output_tokens": 0, "cost": 0,
                },
            }

    # Decide mode
    use_deep = effective_mode == "deep" or (
        effective_mode == "auto" and (plan.estimated_tokens > 500 or plan.task_type.value in ("analysis", "code", "long_context"))
    )

    # --- Debate mode ---
    if effective_mode == "debate":
        plan_info["reasoning"] += "\n⚔️ Debate mode: positions → challenges → verdict"
        debate = await run_debate(full_prompt, user_providers, system=sys_prompt)
        if debate.verdict.get("content"):
            memory.add_message(conv_id, "assistant", debate.verdict["content"],
                               debate.verdict.get("model_id", ""), debate.total_cost)
        return {
            "plan": plan_info, "needs_confirmation": False, "mode": "debate",
            "debate": {
                "log": debate.log,
                "positions": debate.positions,
                "challenges": debate.challenges,
                "verdict": debate.verdict,
            },
            "response": {
                "provider": debate.verdict.get("judge", "debate"),
                "model": debate.verdict.get("model_id", ""),
                "content": debate.verdict.get("content", "Debate failed"),
                "input_tokens": 0, "output_tokens": 0,
                "cost": debate.total_cost,
            } if debate.verdict.get("content") else None,
            "error": "Debate failed" if not debate.verdict.get("content") else None,
        }

    if use_deep:
        plan_info["reasoning"] += "\n🔬 Deep mode: multi-LLM draft → cross-review → synthesis"
        t0 = time.time()
        pipe = await run_deep(full_prompt, user_providers, system=sys_prompt)
        latency = time.time() - t0

        if pipe.final and not pipe.final.degraded:
            memory.add_message(conv_id, "assistant", pipe.final.content, pipe.final.model_id, pipe.total_cost)
            memory.record_model_result(pipe.final.model_id, plan.task_type.value, True, latency)
            cache.store(prompt, plan.task_type.value, pipe.final.content,
                        pipe.final.provider_name, pipe.final.model_id, pipe.total_cost)

        return {
            "plan": plan_info, "needs_confirmation": False, "mode": "deep",
            "pipeline": {
                "steps": pipe.steps_log,
                "drafts": [{"provider": d.provider_name, "model": d.model_id,
                            "content": d.content, "cost": d.cost, "degraded": d.degraded}
                           for d in pipe.draft_responses],
                "reviews": [{"provider": r.provider_name, "content": r.content, "cost": r.cost}
                            for r in pipe.reviews],
            },
            "response": {
                "provider": pipe.final.provider_name if pipe.final else "none",
                "model": pipe.final.model_id if pipe.final else "",
                "content": pipe.final.content if pipe.final else "Pipeline failed",
                "input_tokens": pipe.final.input_tokens if pipe.final else 0,
                "output_tokens": pipe.final.output_tokens if pipe.final else 0,
                "cost": pipe.total_cost,
            } if pipe.final else None,
            "error": "Pipeline failed" if not pipe.final else None,
        }

    # Fast mode
    if plan.primary.tier == Tier.PAID and not confirm_paid:
        return {"plan": plan_info, "needs_confirmation": True}

    # --- Auto-chaining: check if prompt needs decomposition ---
    if effective_mode == "auto" and plan.estimated_tokens > 30:
        complexity = await analyze_complexity(prompt, user_providers)
        if complexity.get("chain") and complexity.get("steps"):
            plan_info["reasoning"] += "\n🔗 Chain mode: decomposed into " + str(len(complexity["steps"])) + " sub-tasks"
            chain_result = await execute_chain(prompt, complexity["steps"], user_providers, system=sys_prompt)
            final = chain_result["final"]
            if final.get("content"):
                memory.add_message(conv_id, "assistant", final["content"], final.get("model", ""), final.get("cost", 0))
                cache.store(prompt, plan.task_type.value, final["content"],
                            final.get("provider", ""), final.get("model", ""), final.get("cost", 0))
            return {
                "plan": plan_info, "needs_confirmation": False, "mode": "chain",
                "chain_steps": chain_result["steps"],
                "response": {
                    "provider": final.get("provider", "chain"),
                    "model": final.get("model", "synthesis"),
                    "content": final.get("content", "Chain failed"),
                    "input_tokens": 0, "output_tokens": 0,
                    "cost": final.get("cost", 0),
                },
            }

    # --- Single-shot with tool support + guardrails ---
    chain = [plan.primary] + plan.fallbacks
    tool_prompt = full_prompt + TOOL_PROMPT_SUFFIX

    for provider in chain:
        if not provider or not provider.available:
            continue
        t0 = time.time()
        result = await execute(provider, tool_prompt, system=sys_prompt)
        latency = time.time() - t0

        if result.degraded:
            memory.record_model_result(provider.model_id, plan.task_type.value, False, latency)
            continue

        # Check for tool calls
        tool_call = detect_tool_call(result.content)
        if tool_call:
            tool_result = await execute_tool(tool_call)
            # Re-query with tool result
            followup = (f"{full_prompt}\n\n"
                        f"Tool '{tool_call['tool']}' returned:\n{tool_result}\n\n"
                        f"Now answer the original question using this information.")
            result = await execute(provider, followup, system=sys_prompt)
            if result.degraded:
                continue

        # Guardrails check
        confidence = check_confidence(result.content)
        guardrail_info = None
        if confidence["needs_reroute"] and len(chain) > 1:
            # Try a different model
            plan_info["reasoning"] += f"\n⚠️ Low confidence ({confidence['confidence']}) — rerouting"
            for alt in chain:
                if alt and alt.available and alt.model_id != provider.model_id:
                    alt_result = await execute(alt, full_prompt, system=sys_prompt)
                    if not alt_result.degraded:
                        alt_conf = check_confidence(alt_result.content)
                        if alt_conf["confidence"] > confidence["confidence"]:
                            result = alt_result
                            confidence = alt_conf
                            break
        if confidence["issues"]:
            guardrail_info = confidence

        memory.add_message(conv_id, "assistant", result.content, result.model_id, result.cost)
        memory.record_model_result(result.model_id, plan.task_type.value, True, latency)
        cache.store(prompt, plan.task_type.value, result.content,
                    result.provider_name, result.model_id, result.cost)
        resp = {
            "plan": plan_info, "needs_confirmation": False, "mode": "fast",
            "response": {
                "provider": result.provider_name, "model": result.model_id,
                "content": result.content, "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens, "cost": result.cost,
            },
        }
        if guardrail_info:
            resp["guardrails"] = guardrail_info
        if tool_call:
            resp["tool_used"] = {"tool": tool_call["tool"], "args": tool_call.get("args", {})}
        return resp

    return {"plan": plan_info, "needs_confirmation": False, "error": "All providers failed."}


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(os.path.dirname(__file__), "static", "index.html")) as f:
        return f.read()


@app.get("/literary", response_class=HTMLResponse)
async def literary_page():
    with open(os.path.join(os.path.dirname(__file__), "static", "literary.html")) as f:
        return f.read()


@app.get("/corkboard", response_class=HTMLResponse)
async def corkboard_page():
    with open(os.path.join(os.path.dirname(__file__), "static", "corkboard.html")) as f:
        return f.read()


@app.get("/gdrive", response_class=HTMLResponse)
async def gdrive_page():
    with open(os.path.join(os.path.dirname(__file__), "static", "gdrive.html")) as f:
        return f.read()


# --- Multi-Document Comparison (#6) ---

@app.post("/api/literary/compare")
async def api_literary_compare(
    doc_id_a: str = Form(...), doc_id_b: str = Form(...),
):
    """Compare two documents — structure, pacing, characters, word count."""
    info_a = literary.get_document_info(doc_id_a)
    info_b = literary.get_document_info(doc_id_b)
    if not info_a or not info_b:
        return {"error": "Document not found"}

    chars_a = literary.get_characters(doc_id_a)
    chars_b = literary.get_characters(doc_id_b)
    struct_a = literary.get_structure(doc_id_a)
    struct_b = literary.get_structure(doc_id_b)
    pacing_a = literary.get_pacing_data(doc_id_a, window=max(5, info_a["total_lines"] // 20))
    pacing_b = literary.get_pacing_data(doc_id_b, window=max(5, info_b["total_lines"] // 20))

    char_names_a = {c["name"] for c in chars_a}
    char_names_b = {c["name"] for c in chars_b}

    return {
        "doc_a": {"title": info_a["title"], "words": info_a["total_words"],
                  "chapters": len(struct_a), "characters": len(chars_a)},
        "doc_b": {"title": info_b["title"], "words": info_b["total_words"],
                  "chapters": len(struct_b), "characters": len(chars_b)},
        "word_diff": info_b["total_words"] - info_a["total_words"],
        "chapter_diff": len(struct_b) - len(struct_a),
        "characters_added": list(char_names_b - char_names_a),
        "characters_removed": list(char_names_a - char_names_b),
        "characters_common": list(char_names_a & char_names_b),
        "avg_tension_a": sum(p["tension"] for p in pacing_a) / len(pacing_a) if pacing_a else 0,
        "avg_tension_b": sum(p["tension"] for p in pacing_b) / len(pacing_b) if pacing_b else 0,
    }


# --- Version Reconstruction (#9) ---

@app.get("/api/reconstruct/projects")
async def api_recon_projects():
    return recon.list_version_projects()


@app.post("/api/reconstruct/projects")
async def api_recon_create(name: str = Form(...)):
    import uuid as _uuid
    pid = name.replace(" ", "_").lower()[:30] + f"_{int(time.time())}"
    return recon.create_version_project(pid, name)


@app.post("/api/reconstruct/{project_id}/ingest")
async def api_recon_ingest(project_id: str, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="replace")
    return recon.ingest_version(project_id, file.filename, content)


@app.get("/api/reconstruct/{project_id}/versions")
async def api_recon_versions(project_id: str):
    return recon.get_project_versions(project_id)


@app.post("/api/reconstruct/{project_id}/rebuild")
async def api_recon_rebuild(project_id: str):
    return recon.reconstruct(project_id)


@app.get("/api/reconstruct/{project_id}/text")
async def api_recon_text(project_id: str):
    text = recon.get_reconstructed_text(project_id)
    return Response(text, media_type="text/plain")


@app.post("/api/reconstruct/{project_id}/smooth")
async def api_recon_smooth(project_id: str):
    """Use LLM to smooth transitions between sections from different versions."""
    text = recon.get_reconstructed_text(project_id)
    if not text:
        return {"error": "No reconstructed text"}

    prompt = f"""This document was reconstructed from multiple versions. Some sections may have inconsistent tone, tense, or style.

Review the transitions between sections and suggest specific edits to make it read as one cohesive document.
For each issue, specify the exact text to change.

DOCUMENT:
{text[:8000]}

List issues and fixes:"""

    plan = build_plan(prompt, _providers, interactive=False)
    if not plan.primary:
        return {"error": "No providers"}
    result = await execute(plan.primary, prompt, max_tokens=4000)
    return {"suggestions": result.content, "provider": result.provider_name}


# --- Scheduler background loop ---

async def _scheduler_loop():
    """Background task that runs due scheduled tasks every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        try:
            due = scheduler.get_due_tasks()
            for task in due:
                plan = build_plan(task["prompt"], _providers, interactive=False)
                if plan.primary:
                    result = await execute(plan.primary, task["prompt"], max_tokens=2000)
                    scheduler.record_result(task["task_id"],
                                            result.content if not result.degraded else "Failed")
        except Exception:
            log.warning("Suppressed exception", exc_info=True)


@app.on_event("startup")
async def start_scheduler():
    asyncio.create_task(_scheduler_loop())


# --- OpenAI-compatible API (R2) ---

@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI-compatible chat/completions endpoint. Supports stream:true, proper errors, timeouts."""
    user = _get_user(request)
    user_provs = filter_providers_for_user(_providers, user)
    body = await request.json()
    messages = body.get("messages", [])
    max_tokens = body.get("max_tokens", 4096)
    model_hint = body.get("model", "")
    prefer_free = body.get("prefer_free", True)
    stream = body.get("stream", False)

    # Extract system + user messages
    system_msg = None
    user_msg = ""
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        elif m["role"] == "user":
            user_msg = m["content"]

    if not user_msg:
        return JSONResponse({"error": {"message": "No user message", "type": "invalid_request"}}, 400)

    # Route
    plan = build_plan(user_msg, user_provs, prefer_free=prefer_free)

    if model_hint:
        for p in user_provs:
            if p.available and (model_hint in p.model_id or model_hint in p.name.lower()):
                plan.primary = p
                break

    # Fix #4: Return 429 when all providers exhausted
    if not plan.primary:
        all_exhausted = all(
            ratelimit.remaining(p.model_id, p.daily_limit) == 0
            for p in user_provs if p.available
        )
        if all_exhausted:
            return JSONResponse(
                {"error": {"message": "All providers rate-limited. Try again later.", "type": "rate_limit_exhausted"}},
                status_code=429,
                headers={"Retry-After": "3600"}
            )
        return JSONResponse(
            {"error": {"message": "No providers available", "type": "server_error",
                       "missing_keys": plan.missing_keys}},
            status_code=503
        )

    # Fix #5: Cache key includes system prompt
    cache_key = f"{system_msg or ''}|||{user_msg}"
    cached = cache.get_cached(cache_key, plan.task_type.value)
    if cached and not stream:
        return _openai_response(cached["response"], cached["provider"], cached["model"], 0, 0, True)

    # Fix #3: Handle stream:true in the main endpoint
    if stream:
        return await _stream_response(user_msg, system_msg, max_tokens, plan, user_provs)

    # Execute with fallback chain + Fix #1 (timeout) + Fix #2 (structured errors)
    chain = [plan.primary] + plan.fallbacks
    last_error = ""
    providers_tried = []
    for provider in chain:
        if not provider or not provider.available:
            continue
        providers_tried.append(provider.name)
        result = await execute(provider, user_msg, max_tokens=max_tokens, system=system_msg)
        if not result.degraded:
            cache.store(cache_key, plan.task_type.value, result.content,
                        result.provider_name, result.model_id, result.cost)
            resp = _openai_response(result.content, result.provider_name, result.model_id,
                                    result.input_tokens, result.output_tokens, False)
            resp["x_intello"]["providers_tried"] = providers_tried
            resp["x_intello"]["fallback_count"] = len(providers_tried) - 1
            return resp
        last_error = result.content

    # Fix #2: Structured error with provider info
    return JSONResponse({
        "error": {
            "message": f"All providers failed. Last error: {last_error}",
            "type": "provider_error",
            "providers_tried": providers_tried,
            "fallback_count": len(providers_tried),
        }
    }, status_code=502)


async def _stream_response(user_msg, system_msg, max_tokens, plan, providers):
    """SSE streaming for /v1/chat/completions with stream:true."""
    async def generate():
        provider = plan.primary
        try:
            from openai import AsyncOpenAI
            base_urls = {"openai": None, "groq": "https://api.groq.com/openai/v1",
                         "mistral": "https://api.mistral.ai/v1", "deepseek": "https://api.deepseek.com",
                         "openrouter": "https://openrouter.ai/api/v1", "xai": "https://api.x.ai/v1"}
            base = base_urls.get(provider.provider)
            if base is not None or provider.provider == "openai":
                kwargs = {"api_key": provider.api_key}
                if base:
                    kwargs["base_url"] = base
                client = AsyncOpenAI(**kwargs)
                msgs = [{"role": "system", "content": system_msg or "You are a helpful assistant."},
                        {"role": "user", "content": user_msg}]
                stream = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=provider.model_id, messages=msgs, max_tokens=max_tokens, stream=True),
                    timeout=30
                )
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': text}, 'index': 0}]})}\n\n"
                yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop', 'index': 0}], 'x_intello': {'provider': provider.name}})}\n\n"
                yield "data: [DONE]\n\n"
                return
        except Exception:
            log.warning("Suppressed exception", exc_info=True)
        # Fallback: non-streaming, send all at once
        result = await execute(provider, user_msg, max_tokens=max_tokens, system=system_msg)
        yield f"data: {json.dumps({'choices': [{'delta': {'content': result.content}, 'index': 0}]})}\n\n"
        yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop', 'index': 0}], 'x_intello': {'provider': result.provider_name}})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")



@app.post("/v1/chat/completions/stream")
async def openai_chat_stream(request: Request):
    """Legacy streaming endpoint — redirects to main endpoint with stream:true."""
    body = await request.json()
    body["stream"] = True
    # Reconstruct request with stream flag
    from starlette.requests import Request as StarletteRequest
    return await openai_chat_completions(request)

def _openai_response(content, provider, model, inp_tokens, out_tokens, was_cached):
    """Format response in OpenAI chat/completions format."""
    import time as _time
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(_time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": inp_tokens,
            "completion_tokens": out_tokens,
            "total_tokens": inp_tokens + out_tokens,
        },
        "x_intello": {
            "provider": provider,
            "cached": was_cached,
        },
    }


