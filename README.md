# L'Intello

Smart AI backend — multi-LLM routing, literary analysis, writing tools, and more.

Formerly "AI Router." Renamed to reflect its evolution from a simple prompt dispatcher into a full AI services platform.

## What it does

- **Multi-LLM Routing** — 27 models across 12 providers, free-first, rate-limit-aware
- **Processing Modes** — Fast, Deep (cross-review), Debate, Chain, Auto
- **Literary Engine** — Document analysis, pacing curves, character tracking, narrative threads
- **Writing Tools** — Show-not-tell, 5-sense describe, tone shift, brainstorm, beta readers
- **Workflow Engine** — Adaptive next-step, horizontal/vertical modes, resumable projects
- **OpenAI-compatible API** — Drop-in replacement at `/v1/chat/completions`
- **Integrations** — Audiobookshelf, Ollama, Google Drive, file upload

## Quick Start

```bash
docker compose up -d
```

## API

```bash
# OpenAI-compatible
curl -X POST http://intello:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}]}'

# Status
curl http://intello:8000/api/v1/status
```

## Architecture

```
intello/
  web.py           — FastAPI app (REST API + UI)
  backends.py      — LLM execution (OpenAI, Anthropic, Google, Groq, etc.)
  router.py        — Task classification + scoring
  pipeline.py      — Deep mode (draft → review → synthesis)
  debate.py        — Multi-model adversarial debate
  chains.py        — Prompt chaining / task decomposition
  literary.py      — Document ingestion, structure, pacing, edits
  workflow.py      — Writing workflow engine
  writing_tools.py — Sudowrite-style transformations
  craft.py         — Dynamic literary reference engine
  memory.py        — Conversation memory + learning
  cache.py         — Semantic response cache
  guardrails.py    — Anti-hallucination + word count
  tools.py         — Web search, calculator, Python eval
  gdrive.py        — Google Drive OAuth
  keys.py          — API key management
  ratelimit.py     — Daily quota tracking
  models.py        — Data models
  research.py      — Provider catalog
  static/          — Web UI
```
