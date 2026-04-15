# L'Intello — Migration from AI Router

## What changed

**AI Router** has been renamed to **L'Intello** (`intello`).

This is a rename only — all features, data, and API keys are preserved. The codebase, Docker container, and URL paths have been updated.

## New coordinates

| What | Old | New |
|------|-----|-----|
| GitHub repo | `github.com/collaed/airouter` | `github.com/collaed/intello` |
| Docker container | `airouter` | `intello` |
| Docker volume | `airouter_airouter-data` | `intello_intello-data` |
| Python package | `airouter/` | `intello/` |
| Web UI | `tools.ecb.pm/airouter/` | `tools.ecb.pm/intello/` |
| Internal URL | `http://airouter:8000` | `http://intello:8000` |
| Cookie name | `airouter_token` | `intello_token` |

## For API clients (Audiobookshelf, etc.)

Update your configuration:

```
# Old
AIROUTER_URL=http://airouter:8000

# New
INTELLO_URL=http://intello:8000
```

The API endpoints are unchanged:
- `POST /v1/chat/completions` — OpenAI-compatible chat
- `GET /v1/models` — list available models
- `GET /api/v1/status` — health check
- `GET /api/providers` — detailed provider list

Authentication is unchanged:
- Docker internal network (172.x.x.x): no auth required
- External: Bearer token or cookie-based login

## Migration steps (already done on ecb.pm)

1. New repo created at `github.com/collaed/intello`
2. Python package renamed `airouter/` → `intello/`
3. All internal imports updated
4. Docker container `intello` deployed alongside `airouter`
5. API keys and data copied from old volume to new
6. Caddy route `/intello/*` added
7. Old `airouter` container kept running during transition

## Decommissioning airouter

Once all clients are updated, the old container can be removed:

```bash
cd /opt/apps/airouter
docker compose down
# Optionally remove the old volume:
# docker volume rm airouter_airouter-data
```

The old GitHub repo (`collaed/airouter`) can be archived.

## Why the rename?

"AI Router" described what it did in March 2026 — route prompts to LLMs. Since then it grew into a literary analysis engine, writing toolkit, audiobookshelf backend, and general AI services platform. "L'Intello" (French slang for "the brainy one") better reflects what it actually is: a smart backend that handles any AI task you throw at it.
