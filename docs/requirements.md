# L'Intello — Feature Specification: Requirements

## 1. System Metrics

| Metric | Value |
|--------|-------|
| Python modules | 27 |
| Functions/classes | 265 |
| HTTP routes | 72 |
| LLM providers | 29 (20 free, 9 paid) |
| SQLite tables | 19 across 6 databases |
| Flat file stores | 2 (api_keys.json, usage.json) |
| HTML pages | 4 (chat, literary, corkboard, gdrive) |
| Lines of Python | ~6,100 |
| Lines of HTML/JS | ~1,500 |
| Automated tests | 36 (12 whitebox + 6 greybox + 18 blackbox) |

## 2. Core Type Definitions

### Tier (Enum)
`FREE` | `PAID`

### TaskType (Enum)
`CODE` | `CREATIVE` | `ANALYSIS` | `MATH` | `GENERAL` | `VISION` | `LONG_CONTEXT`

### LLMProvider (Dataclass)
`name: str, model_id: str, provider: str, tier: Tier, context_window: int, strengths: list[TaskType], cost_per_1k_input: float, cost_per_1k_output: float, env_key: str, api_key: Optional[str], available: bool, daily_limit: int, notes: str`

### RoutingPlan (Dataclass)
`prompt: str, task_type: TaskType, estimated_tokens: int, primary: Optional[LLMProvider], fallbacks: list[LLMProvider], degraded: bool, missing_keys: list[str], estimated_cost: float, reasoning: str`

### LLMResponse (Dataclass)
`provider_name: str, model_id: str, content: str, input_tokens: int, output_tokens: int, cost: float, degraded: bool`

### PipelineResult (Dataclass)
`draft_responses: list[LLMResponse], reviews: list[LLMResponse], final: Optional[LLMResponse], total_cost: float, steps_log: list[str]`

### DebateResult (Dataclass)
`positions: list[dict], challenges: list[dict], verdict: dict, total_cost: float, log: list[str]`

---

## 3. Requirements (EARS Notation)

### ROUTE: Multi-LLM Routing

**ROUTE-01** `router.classify_task()`
While the system receives a user prompt, the system shall classify it into one of 7 task types (CODE, MATH, VISION, CREATIVE, ANALYSIS, LONG_CONTEXT, GENERAL) using word-boundary keyword matching against 5 signal lists.

**ROUTE-02** `router._score()`
When scoring a provider for a task, the system shall assign: +50 for task-strength match, +30 for FREE tier, +20 if tokens fit context window, minus cost×100, minus rate-limit penalty, plus learned-performance bonus.

**ROUTE-03** `router.build_plan()`
When building a routing plan, the system shall rank all available providers by score, select the highest as primary, and assign the next 3 as fallbacks.

**ROUTE-04** `router.build_plan()`
When prefer_free is true and free providers are available, the system shall exclude paid providers from the candidate set.

**ROUTE-05** `router._score()`
If a provider's remaining daily quota is 0, the system shall apply a -1000 score penalty. If <10% remaining, -40. If <30% remaining, -15.

**ROUTE-06** `router._score()`
When scoring a provider, the system shall add a bonus/penalty from `memory.get_score_bonus()` based on historical success rate and user ratings for that model+task combination.

**ROUTE-07** `router.build_plan()`
When the selected primary provider is PAID tier, the system shall include estimated cost in the routing plan reasoning.

**ROUTE-08** `web.api_prompt()`
If the primary provider is PAID and confirm_paid is false, the system shall return `needs_confirmation: true` without executing.

**ROUTE-09** `router.build_plan()`
If no providers are available (all keys missing or exhausted), the system shall set `degraded: true` and list all missing env keys.

### EXEC: LLM Execution

**EXEC-01** `backends._BACKENDS`
The system shall support 13 named backends: openai, anthropic, google, google_cloud, groq, mistral, deepseek, xai, cohere, openrouter, cloudflare, nanogpt, ollama.

**EXEC-02** `backends.SYSTEM_DEFAULT`
Unless overridden, the system shall inject a "brutally honest" system prompt on every LLM call.

**EXEC-03** `backends.execute()`
Before calling any backend, the system shall check `ratelimit.remaining()` and return a degraded response if quota is 0.

**EXEC-04** `backends.execute()`
After a successful backend call, the system shall call `ratelimit.record_usage()` to increment the daily counter.

**EXEC-05** `backends.execute()`
If a backend call raises any exception, the system shall catch it and return an LLMResponse with `degraded=True` and the error message as content.

**EXEC-06** `backends._call_ollama()`
When the Ollama provider is configured, the system shall use the `api_key` field as the base URL (defaulting to `http://localhost:11434/v1`).

### MODE: Processing Modes

**MODE-01** `web.api_prompt()`
When mode is "fast" or auto selects fast, the system shall execute against the primary provider, falling through the fallback chain on degraded responses.

**MODE-02** `pipeline.run_deep()`
When mode is "deep", the system shall: (1) send the prompt to 2-3 diverse providers in parallel, (2) send all drafts to an independent reviewer, (3) send drafts+review to a synthesizer for the final answer.

**MODE-03** `debate.run_debate()`
When mode is "debate", the system shall: (1) get initial positions from 3 models, (2) have each model challenge the others' positions, (3) have an independent judge deliver a verdict with dissenting opinions.

**MODE-04** `chains.analyze_complexity()` + `chains.execute_chain()`
When mode is "auto" and the prompt is complex, the system shall decompose it into up to 4 sub-tasks via a fast LLM, route each sub-task to the best specialist, pass context between steps, and synthesize a final answer.

**MODE-05** `web.api_prompt()`
When mode is "auto", the system shall select "deep" for prompts with >500 estimated tokens or task types analysis/code/long_context, and attempt chain decomposition for complex multi-step prompts.

### CACHE: Semantic Cache

**CACHE-01** `cache.get_cached()`
When checking the cache, the system shall first attempt an exact match by SHA-256 hash of the normalized (lowercased, whitespace-collapsed) prompt.

**CACHE-02** `cache.get_cached()`
If no exact match is found, the system shall compute a sentence-transformer embedding (all-MiniLM-L6-v2) and compare against up to 200 recent entries of the same task type using cosine similarity with threshold ≥ 0.75.

**CACHE-03** `cache.store()`
When storing a response, the system shall persist the prompt, response, provider, model, cost, embedding, and timestamp.

**CACHE-04** `cache.get_cached()`
The system shall not return cache entries older than 168 hours (7 days).

**CACHE-05** `cache.get_cached()`
On each cache hit, the system shall increment the `hits` counter for that entry.

### MEM: Conversation Memory

**MEM-01** `memory.add_message()`
When a message is sent or received, the system shall persist it in SQLite with conversation_id, role, content, model, cost, and timestamp.

**MEM-02** `memory.build_context()`
When building context for a new prompt, the system shall prepend the conversation summary (if any) followed by the last N messages (default 10).

**MEM-03** `web._compress_context()`
If a conversation exceeds 15 messages, the system shall asynchronously summarize older messages using a cheap/fast model (groq, cloudflare, or mistral) and store the summary.

**MEM-04** `memory.get_prefs()` / `memory.set_prefs()`
The system shall persist per-user preferences: preferred_models, tone, default_mode, custom_system_prompt.

**MEM-05** `memory.record_model_result()` / `memory.get_score_bonus()`
The system shall track per-model per-task-type: uses, failures, avg_latency, rating. After ≥3 data points, it shall compute a score bonus: -20×failure_rate + (rating-3)×5.

### TOOL: Tool Use

**TOOL-01** `tools._web_search()`
When the LLM invokes web_search, the system shall query DuckDuckGo HTML, parse up to 5 results with titles and snippets, and return them as text.

**TOOL-02** `tools._calculator()`
When the LLM invokes calculator, the system shall evaluate the expression using Python eval with restricted builtins (math functions only, no file/network access).

**TOOL-03** `tools._python_eval()`
When the LLM invokes python_eval, the system shall execute the code in a sandbox with: max 20 lines, 10 forbidden patterns (import os, import sys, import subprocess, open(, __import__, exec(, eval(, compile(, globals, locals), and a restricted builtins whitelist (print, range, len, str, int, float, list, dict, sorted, enumerate, zip, map, sum, min, max, abs, round, type, isinstance + math, json, re).

**TOOL-04** `tools.detect_tool_call()`
The system shall detect tool invocations in LLM responses by parsing ```tool JSON code blocks or bare `{"tool": "..."}` JSON patterns.

**TOOL-05** `web.api_prompt()`
When a tool call is detected, the system shall execute the tool, append the result to the prompt, and re-query the same provider for a final answer.

### GUARD: Guardrails

**GUARD-01** `guardrails.check_confidence()`
The system shall scan responses for 8 hedging patterns (e.g., "I'm not sure", "I don't have access to") and deduct up to 0.3 from confidence per pattern type.

**GUARD-02** `guardrails.check_confidence()`
The system shall scan for 3 fabrication patterns (unsourced "according to a study", specific statistics without citation, "research shows" without link) and deduct up to 0.3.

**GUARD-03** `guardrails.check_confidence()`
The system shall detect possible self-contradictions by checking if a sentence contains "not" plus significant words (>4 chars) from a preceding sentence, deducting 0.15 per instance.

**GUARD-04** `guardrails.check_confidence()`
The system shall return a confidence score (0.0-1.0), list of issues, `needs_review` flag (score < 0.6), and `needs_reroute` flag (score < 0.4).

**GUARD-05** `web.api_prompt()`
If confidence < 0.4 and alternative providers exist, the system shall re-execute the prompt on a different model and use the higher-confidence result.

**GUARD-06** `guardrails.check_word_count()`
When a target word count is specified, the system shall count actual words (stripping markdown/code blocks) and report whether the result is within 15% tolerance.

### LIT: Literary Engine

**LIT-01** `literary.ingest_document()` / `ingest_pdf()` / `ingest_epub()`
The system shall ingest documents in TXT, MD, PDF (via pymupdf), and EPUB (via zipfile HTML extraction) formats.

**LIT-02** `literary.ingest_document()`
The system shall store every line with doc_id + line_num as primary key, along with chapter assignment.

**LIT-03** `literary.ingest_document()`
The system shall detect chapter boundaries using 4 regex patterns: `^Chapter/CHAPTER/Part/PART/Act/ACT + number`, `^Chapter/Part/Act + word`, `^\d+\.\s+\w`, `^#{1,3}\s+`.

**LIT-04** `literary.ingest_document()`
The system shall split documents into chunks of ~2000 tokens, breaking at chapter boundaries when possible.

**LIT-05** `nlp.extract_characters()` via `literary.extract_characters()`
The system shall extract character names using spaCy NER (PERSON entities), merge name variants (e.g., "Sarah" and "Sarah Chen"), and require ≥2 mentions.

**LIT-06** `literary.ingest_document()`
The system shall compute per-line pacing metrics: sentence length, word length, dialogue detection (regex for quotation marks and dialogue starters), tension scoring (27 action keywords + short-sentence bonus + textstat Flesch reading ease).

**LIT-07** `literary.extract_threads()`
The system shall detect narrative threads using 20 mystery signal patterns (who/why/what/how questions, secret, mystery, hiding, wonder, strange, threat, promise, clue) and track resolution using 9 resolution patterns (revealed, turns out, finally knew, the truth, confessed, solved, at last).

**LIT-08** `literary.propose_edit()`
The system shall store edit proposals with: doc_id, edit_type, start_line, end_line, original text, replacement text, reason, model, status (pending/applied/rejected).

**LIT-09** `literary.apply_edit()`
When applying an edit, the system shall delete old lines in range, shift subsequent line numbers, insert new lines, and record the change in the versions table.

**LIT-10** `web.api_literary_export()`
The system shall generate a standalone HTML report with: pacing SVG polyline with colored dots, thread SVG bars with tooltips, contenteditable text spans, line numbers, chapter links, edit annotations, print/save buttons.

**LIT-11** `web.api_literary_export_docx()`
The system shall generate a DOCX file with chapter headings (Heading 1) and paragraph text using python-docx.

**LIT-12** `web.api_literary_compare()`
The system shall compare two documents returning: word count diff, chapter count diff, characters added/removed/common, average tension comparison.

**LIT-13** `web.api_literary_append()`
When text is appended to a document, the system shall concatenate it with the existing text and re-ingest the full document.

### WRITE: Writing Tools

**WRITE-01** `writing_tools.show_not_tell()`
The system shall generate a prompt that instructs the LLM to replace emotional labels with physical actions, sensory details, and behavior.

**WRITE-02** `writing_tools.describe_senses()`
The system shall generate a prompt requesting descriptions for sight, sound, smell, touch, taste, and one metaphor.

**WRITE-03** `writing_tools.tone_shift()`
The system shall generate a prompt to rewrite a passage in a specified target tone while preserving events and meaning.

**WRITE-04** `writing_tools.brainstorm()`
The system shall generate prompts for 5 brainstorm categories: plot, character, twist, setting, dialogue.

**WRITE-05** `writing_tools.shrink_ray()`
The system shall generate prompts for 5 compression formats: logline (25-35 words), blurb (100-150 words), synopsis (300-500 words), outline (one sentence per chapter), pitch (3 sentences).

**WRITE-06** `writing_tools.first_draft()`
The system shall generate a prompt to write ~1000 words of prose from a scene description, starting in medias res and ending with a hook.

**WRITE-07** `writing_tools.beta_reader_prompt()` + `web.api_tool_beta_read()`
The system shall run 3 beta readers in parallel on different models with personas: casual (entertainment focus), craft (workshop instructor), market (literary agent).

### WORK: Writing Workflow

**WORK-01** `literary.create_project()`
The system shall persist projects with 16 fields: title, genre, brief, target_words, style, steps, detected_style, detected_intent, character_arcs, themes, setting, tone, pov, audience, iteration_state, timestamps.

**WORK-02** `web.api_literary_auto_populate()`
When auto-populate is triggered, the system shall send document samples to a fast LLM and parse the JSON response to fill all project fields.

**WORK-03** `workflow.get_workflow_state()`
The system shall compute the current phase: "outline" (no structure), "enrich" (structure exists but <5 steps or <2 character arcs), "expand" (structure rich, steps remaining), "polish" (≥90% of target words).

**WORK-04** `workflow.build_horizontal_prompt()`
In horizontal mode, the system shall generate prompts to write the next section of prose, continuing from the last 2000 characters of existing text.

**WORK-05** `workflow.build_vertical_prompt()`
In vertical mode, the system shall generate prompts to add subplots, side characters, foreshadowing, sensory details, or (for non-fiction) tangential topics, case studies, counterarguments.

**WORK-06** `web.api_workflow_next()`
The system shall select model quality based on budget_pct: ≤5% uses groq/cloudflare, ≤25% uses groq/mistral/deepseek, higher uses best available.

**WORK-07** `workflow.mark_step_complete()`
When a workflow step is completed, the system shall record it in iteration_state.completed_steps and persist to the project.

**WORK-08** `craft.get_relevant_techniques()`
The system shall select 2-3 techniques per matched category from a bank of 50+ craft techniques (6 fiction categories, 4 non-fiction categories), randomized per call.

**WORK-09** `web.api_literary_iterate()`
The system shall process one chunk per call, save progress in iteration_state, and resume from the last completed chunk on subsequent calls.

### RECON: Version Reconstruction

**RECON-01** `reconstruct.ingest_version()`
The system shall parse each version file into sections using 5 header patterns and extract the version number from filename or content.

**RECON-02** `reconstruct.find_references()`
The system shall detect cross-version references using 6 regex patterns matching "unchanged since vN", "see vN", "as in vN", "(vN)", "→ vN".

**RECON-03** `reconstruct.reconstruct()`
The system shall reconstruct by: (1) using latest version with actual content (>50 chars, not a reference), (2) following reference chains to pull from referenced version, (3) falling back to best available.

**RECON-04** `reconstruct.reconstruct()`
The system shall assign confidence: "high" (latest has content), "medium" (via reference chain), "low" (best available, no definitive version).

**RECON-05** `web.api_recon_smooth()`
The system shall use an LLM to review transitions between sections from different versions and suggest edits for consistency.

**RECON-06** `web.api_recon_ingest_gdrive()`
The system shall accept a list of Google Drive file IDs, batch-fetch their content, and ingest each as a version file.

### OCR: Optical Character Recognition

**OCR-01** `ocr.ocr_image()`
The system shall OCR a single image using Tesseract, returning text, per-block bounding boxes, and average confidence score.

**OCR-02** `ocr.ocr_pdf_to_text()` / `ocr.ocr_pdf_searchable()`
The system shall OCR PDFs either as per-page text extraction (via pdf2image + Tesseract) or as searchable PDF output (via OCRmyPDF).

**OCR-03** `ocr_engines.smart_ocr()`
When quality is "auto", the system shall: (1) try Tesseract, (2) if confidence < 70%, try OCR.space free API, (3) if still < 70%, try Gemini Vision.

**OCR-04** `ocr_engines.smart_ocr()`
When quality is "fast", the system shall use Tesseract only. When "best", the system shall use Gemini Vision directly.

**OCR-05** `ocr.create_job()` / `ocr.run_job()`
For large PDFs, the system shall create an async job, process in the background via asyncio.create_task, and allow status polling and result download.

**OCR-06** `ocr.get_languages()`
The system shall support 9 Tesseract languages: eng, fra, deu, spa, ita, por, nld, rus, osd.

### GDRIVE: Google Drive Integration

**GDRIVE-01** `gdrive.get_oauth_url()` / `gdrive.exchange_code()`
The system shall support OAuth 2.0 authentication with Google Drive, storing tokens at /data/gdrive_token.json.

**GDRIVE-02** `gdrive.fetch_public()`
The system shall fetch public Google Drive files by extracting file ID from sharing URLs and downloading via direct link.

**GDRIVE-03** `gdrive.fetch_private()`
The system shall fetch private files via the Drive API, exporting Google Docs as text, Sheets as CSV, and downloading binary files as UTF-8.

**GDRIVE-04** `gdrive.list_folder()`
The system shall list folder contents with pagination, returning id, name, mimeType, size, modifiedTime, sorted by folder-first then name.

**GDRIVE-05** `gdrive.batch_fetch()`
The system shall fetch multiple files by ID in sequence, returning content or error per file, capped at 100KB per file.

### API: OpenAI-Compatible

**API-01** `web.openai_chat_completions()`
The system shall accept POST /v1/chat/completions with standard OpenAI message format, route via build_plan, check cache, execute with fallbacks, and return OpenAI-format response with x_intello metadata.

**API-02** `web.openai_chat_stream()`
The system shall accept POST /v1/chat/completions/stream and return SSE events with `data: {"content": "..."}` chunks for providers supporting OpenAI-compatible streaming (openai, groq, mistral, deepseek, openrouter, xai).

**API-03** `web.openai_models()`
The system shall return GET /v1/models with all available providers in OpenAI list format.

**API-04** `web.api_status()`
The system shall return GET /api/v1/status with: available flag, provider list with availability, total/free counts, OCR engine status with languages.

### INT: Integrations

**INT-01** `webhooks.py` + `web.api_webhook_trigger()`
The system shall support webhook CRUD and trigger execution, logging each trigger with payload and result.

**INT-02** `scheduler.py` + `web._scheduler_loop()`
The system shall support scheduled tasks (hourly/daily/weekly) with a background loop checking every 60 seconds, storing last 10 results per task.

**INT-03** `imagegen.generate_image()`
The system shall route image generation to DALL-E (if OpenAI key available) or generate a detailed text description via Gemini.

**INT-04** `web.api_voice_transcribe()`
The system shall transcribe audio files via Groq's Whisper API (whisper-large-v3-turbo model).

**INT-05** `web.PROMPT_TEMPLATES`
The system shall provide 7 prompt templates: analyze_pacing, character_check, show_not_tell, tighten_prose, expand_scene, blurb, chapter_summary.

**INT-06** `web.api_backup()`
The system shall generate a tar.gz archive of all data files (api_keys.json, usage.json, memory.db, cache.db, literary.db, scheduler.db, webhooks.db, versions.db).

### AUTH: Authentication & Authorization

**AUTH-01** `AuthMiddleware`
Requests from Docker internal network (IP starting with "172." or "127.0.0.1") shall bypass all authentication.

**AUTH-02** `AuthMiddleware`
Requests with a valid `X-Auth-User` header (set by Caddy forward_auth) shall be authenticated.

**AUTH-03** `AuthMiddleware`
Requests with `Authorization: Bearer <token>` matching INTELLO_TOKEN shall be authenticated.

**AUTH-04** `AuthMiddleware`
Requests with `Authorization: Basic <base64>` matching a USERS entry shall be authenticated.

**AUTH-05** `AuthMiddleware`
Requests with `intello_token` cookie matching TOKEN shall be authenticated.

**AUTH-06** `AuthMiddleware`
Requests with `?token=<value>` query parameter matching TOKEN shall be authenticated.

**AUTH-07** `AuthMiddleware`
The `/login` endpoint shall be accessible without authentication.

**AUTH-08** `AuthMiddleware`
Unauthenticated GET requests to `/` or `/literary` shall receive the login page HTML.

**AUTH-09** `AuthMiddleware`
All other unauthenticated requests shall receive HTTP 401 with WWW-Authenticate header.

**AUTH-10** `web.filter_providers_for_user()`
Non-premium users shall not see or use models whose model_id contains any string in PREMIUM_MODELS (gemini-2.5-pro, claude-sonnet-4-5, gpt-4o, grok-4-1-fast).

**AUTH-11** `web.login()`
Successful login shall set an `intello_token` cookie with HttpOnly, 30-day max-age, SameSite=lax, path=/.

---

## 4. Edge Cases (from 116 error handling paths)

### Provider Failures
- All providers exhausted → degraded mode with missing_keys list
- Individual provider timeout/error → catch Exception, return degraded LLMResponse, try next fallback
- Rate limit hit mid-request → return degraded with quota message
- Anthropic returns 429 → treated as valid key (rate limited, not invalid)

### Input Validation
- Empty prompt → "No user message" error (API endpoint)
- Document text < 50 chars → "Content too short" error
- No file_ids in batch request → "No file_ids provided" error
- Unknown tool name → "Unknown tool: {name}" error
- Python code > 20 lines → "Error: code too long" error
- Forbidden Python operation → "Error: forbidden operation: {f}" error

### Data Integrity
- JSON decode failure in chain decomposition → fall back to non-chain mode
- JSON decode failure in auto-populate → "Could not auto-populate" error
- JSON decode failure in project steps → split by newlines as fallback
- Missing project_id column in old DB → ALTER TABLE migration
- Missing embedding column in old cache DB → ALTER TABLE migration
- spaCy model not installed → auto-download via spacy.cli.download

### OCR Failures
- Tesseract timeout (>60s) → return empty text with "Timeout" error
- OCR.space HTTP error → return with confidence 0 and error message
- Gemini Vision HTTP error → return with confidence 0 and error message
- Gemini Vision parse failure → return with "Parse failed" error
- No Google API key for Gemini Vision → return with "No Google API key" error

### Google Drive
- Not authenticated → "Not authenticated with Google Drive" error
- File ID parse failure → "[Could not parse file ID from: {url}]"
- HTTP fetch failure → "[Failed to fetch: HTTP {status}]"
- Individual file error in batch → error recorded per-file, others continue

### Reconstruction
- No versions ingested → "No versions ingested" error
- Section has reference but referenced version not found → use best available with "low" confidence
- Section content < 50 chars → treated as reference/stub, not real content

---

## 5. Security Constraints

### Authentication Layers (evaluated in order)
1. **Docker network trust**: 172.x.x.x and 127.0.0.1 bypass all auth
2. **Forward proxy header**: X-Auth-User from Caddy trusted without verification
3. **Bearer token**: Compared against INTELLO_TOKEN env var (default: "your-token-here")
4. **Basic auth**: Username/password compared against hardcoded USERS dict
5. **Cookie**: intello_token cookie compared against TOKEN
6. **Query param**: ?token= compared against TOKEN

### Python Sandbox (tools._python_eval)
- Max 20 lines of code
- 10 forbidden string patterns: import os, import sys, import subprocess, open(, __import__, exec(, eval(, compile(, globals, locals
- Restricted __builtins__: only print, range, len, str, int, float, list, dict, sorted, enumerate, zip, map, sum, min, max, abs, round, type, isinstance
- Allowed modules: math, json, re only
- stdout captured via contextlib.redirect_stdout

### Premium Model Access
- PREMIUM_MODELS set: gemini-2.5-pro, claude-sonnet-4-5, gpt-4o, grok-4-1-fast
- PREMIUM_USERS set: {"ecb"}
- filter_providers_for_user() strips premium models for non-premium users
- Applied in both /api/prompt and /v1/chat/completions

### Webhook Security
- webhooks.WEBHOOK_SECRET available for HMAC verification
- webhooks.verify_signature() implements HMAC-SHA256
- Note: trigger endpoint does NOT enforce signature verification (technical debt)

### Data Protection
- API keys persisted in /data/api_keys.json (plaintext, Docker volume)
- OAuth tokens persisted in /data/gdrive_token.json
- All SQLite databases use WAL mode for concurrent access safety
- Cookie set with HttpOnly (no JS access), SameSite=lax

---

## 6. Non-Functional Requirements

**NFR-01 Cost Optimization**: Free-tier models prioritized (+30 score). 20 free providers with 41,850 combined daily requests. Semantic cache avoids redundant LLM calls. Budget control (1/10/50/100%) in workflow.

**NFR-02 Reliability**: Automatic fallback chain (up to 3 alternatives). Graceful degradation when no providers available. All backend calls wrapped in try/except. Rate limit pre-check prevents wasted calls.

**NFR-03 Persistence**: 7 SQLite databases + 2 JSON files in Docker volume. WAL mode for concurrent access. Schema migration for column additions.

**NFR-04 Extensibility**: New provider = edit research.py (add LLMProvider), backends.py (add _call_X function + _BACKENDS entry), keys.py (add _validate_X + _VALIDATORS entry). 3 files, ~30 lines.

**NFR-05 Testability**: 36 automated tests covering unit (12), integration (6), and HTTP API (18) levels. Run via `python3 tests/run_all.py`.
