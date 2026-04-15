# L'Intello — Admin Setup Guide

## Prerequisites

- Docker + Docker Compose
- A server with 8GB+ RAM, 30GB+ disk
- A reverse proxy (Caddy, Nginx, Traefik) — optional but recommended
- At least one LLM API key (Groq is free and fast — get one at https://console.groq.com)

## Quick Start (5 minutes)

```bash
git clone https://github.com/collaed/intello.git
cd intello
cp .env.example .env
# Edit .env — add at least one API key
docker compose up -d
# → Running at http://localhost:8000
```

## Environment Variables

### LLM API Keys (add whichever you have)
```bash
GOOGLE_API_KEY=           # Gemini (free tier, 1500 req/day)
GOOGLE_API_KEY_2=         # Second Gemini key (doubles quota)
GROQ_API_KEY=             # Groq (free, fast — Llama, Mixtral, Qwen, Kimi)
MISTRAL_API_KEY=          # Mistral (free tier)
DEEPSEEK_API_KEY=         # DeepSeek (near-free)
OPENAI_API_KEY=           # OpenAI (GPT-4o Mini free-ish, GPT-4o paid)
ANTHROPIC_API_KEY=        # Anthropic Claude (paid only)
XAI_API_KEY=              # x.ai Grok (credit-based)
COHERE_API_KEY=           # Cohere Command (free tier)
OPENROUTER_API_KEY=       # OpenRouter (free models available)
CLOUDFLARE_API_KEY=       # Cloudflare Workers AI (10K free/day)
CLOUDFLARE_ACCOUNT_ID=    # Required for Cloudflare
NANOGPT_API_KEY=          # NanoGPT meta-provider
OLLAMA_URL=               # Local Ollama (http://ollama:11434/v1)
```

### App Configuration
```bash
INTELLO_TOKEN=your_secret  # Bearer token for API access
```

### Google Drive OAuth (optional)
1. Create OAuth credentials at https://console.cloud.google.com/apis/credentials
2. Download JSON → place at `/data/gdrive_credentials.json` in the container
3. Visit `/api/gdrive/auth` to authorize

## Reverse Proxy (Caddy example)

```
your-domain.com {
    handle /intello/* {
        uri strip_prefix /intello
        reverse_proxy intello:8000
    }
}
```

## Docker Compose with Ollama

```yaml
services:
  intello:
    build: .
    container_name: intello
    restart: unless-stopped
    networks: [web]
    expose: ["8000"]
    env_file: [.env]
    volumes: [intello-data:/data]

  ollama:  # Optional: free local LLM
    image: ollama/ollama
    volumes: [ollama-data:/root/.ollama]
    networks: [web]

volumes:
  intello-data:
  ollama-data:

networks:
  web:
    external: true
```

## User Management

Edit `USERS` and `PREMIUM_USERS` in `intello/web.py`:

```python
USERS = {"admin": "password123", "writer": "writerpass"}
PREMIUM_USERS = {"admin"}  # Only admin can use paid models
```

## Backup & Restore

```bash
# Backup
curl http://intello:8000/api/backup > intello_backup.tar.gz

# Restore
docker cp intello_backup.tar.gz intello:/tmp/
docker exec intello tar xzf /tmp/intello_backup.tar.gz -C /data/
```

## Health Check

```bash
curl http://intello:8000/api/v1/status
# Returns: providers count, OCR status, languages
```

## Running Tests

```bash
docker exec intello python3 tests/run_all.py
# 36 tests: 12 whitebox + 6 greybox + 18 blackbox
```
