# Intello/Airouter — Issues Found During SizeMy Integration

## Context
SizeMy calls intello's `/v1/chat/completions` endpoint for:
1. **Query parsing** — NL query → structured JSON constraints
2. **Result ranking** — rank products with justifications
3. **Dimension extraction** — extract dimensions from product descriptions (during scraping)

## Issues Found

### 1. Indefinite Hangs (Critical)
**Symptom:** `POST /v1/chat/completions` sometimes never returns — no response, no error, no timeout. The connection stays open indefinitely.

**Impact:** SizeMy's search would hang forever. Had to add `asyncio.wait_for()` timeouts at every call site.

**Reproduction:** Intermittent. More likely after a period of inactivity (cold provider?) or when multiple calls are made in quick succession.

**Suggestion:** Add a server-side timeout to the `/v1/chat/completions` endpoint. If the upstream LLM provider doesn't respond within N seconds, return a 504 Gateway Timeout instead of hanging. The client shouldn't have to implement its own timeout for what should be a bounded operation.

### 2. 500 Internal Server Errors Under Load (High)
**Symptom:** During scraping (many concurrent extraction calls), intello returned HTTP 500 repeatedly. No useful error message in the response body.

**Impact:** ~50% of products failed LLM-based dimension extraction during the initial scrape.

**Suggestion:**
- Return structured error JSON with the provider name and error type (rate limit, auth failure, provider down)
- When the primary provider fails, the fallback chain should be transparent to the caller
- Consider a `/v1/chat/completions` response header like `X-Provider-Used` and `X-Fallback-Count`

### 3. No Streaming / Progress Indication
**Symptom:** For complex prompts (ranking 20 products), the response takes 5-15 seconds with no indication of progress.

**Suggestion:** Support `"stream": true` in the OpenAI-compatible endpoint. Even if the underlying provider doesn't stream, intello could send a heartbeat or progress event to prevent client timeouts.

### 4. Rate Limit Exhaustion Not Surfaced
**Symptom:** When all free-tier providers are exhausted, the endpoint either hangs or returns a generic error. The caller has no way to know "all providers are rate-limited, try again in X minutes."

**Suggestion:** Return HTTP 429 with `Retry-After` header when all providers are exhausted. The current behavior of silently degrading to a hang is the worst possible outcome for API consumers.

### 5. Cache Not Working for Structured Prompts
**Symptom:** Identical prompts (same query parser system prompt + user query) are not cached. Each search re-calls the LLM even for the same query.

**Suggestion:** The cache key should include the system prompt hash + user message. For SizeMy's use case, the same "parse this furniture query" prompt with the same user input should return a cached result.

## Workarounds Implemented in SizeMy
1. `asyncio.wait_for(prompt_json(...), timeout=15)` on every LLM call
2. Regex-based local query parser as fallback (no LLM needed)
3. Results returned sorted by confidence when ranker times out
4. Hash-based pseudo-embeddings instead of LLM embeddings (avoids embed endpoint)
5. Playwright-based dimension backfill as alternative to LLM extraction
