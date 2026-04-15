# L'Intello — Requirements Specification

## Functional Requirements

### FR-01: Multi-LLM Routing
- Support 10+ LLM providers simultaneously
- Classify prompts by task type (code, math, creative, analysis, vision, general, long_context)
- Score and rank providers by task fit, cost, rate limits, and learned performance
- Prioritize free-tier models; require confirmation for paid models
- Fall back through ranked alternatives on failure

### FR-02: Processing Modes
- **Fast**: single best model, lowest latency
- **Deep**: parallel drafts from 2-3 diverse models → independent cross-review → synthesis
- **Debate**: models take positions → challenge each other → judge delivers verdict
- **Chain**: auto-decompose complex prompts into sub-tasks → route each to specialist → synthesize
- **Auto**: classify complexity and select appropriate mode

### FR-03: Conversation Memory
- Persist messages per conversation in SQLite
- Prepend conversation context to new prompts
- Auto-compress old messages (>15) via cheap model summarization
- List and resume past conversations

### FR-04: Semantic Cache
- Store responses with sentence-transformer embeddings
- Exact match by prompt hash
- Semantic match by cosine similarity (threshold 0.75)
- 7-day TTL, per-task-type isolation

### FR-05: Cross-Session Learning
- Track model success/failure/latency per task type
- Accept user ratings (1-5 stars)
- Adjust routing scores based on learned performance

### FR-06: Tool Use
- Web search (DuckDuckGo)
- Calculator (safe math eval)
- Sandboxed Python execution (max 20 lines, restricted builtins)
- LLMs can invoke tools via structured JSON in responses

### FR-07: Anti-Hallucination Guardrails
- Detect hedging language, unsourced claims, self-contradictions
- Confidence score 0-100%
- Auto-reroute to different model if confidence < 40%
- Word count verification against targets

### FR-08: Literary Engine
- Ingest documents: TXT, MD, PDF, EPUB
- Line-level indexing with chapter detection
- Character extraction via spaCy NER
- Pacing analysis: tension scoring, dialogue ratio, readability (textstat)
- Narrative thread tracking: detect open questions, track resolution
- Surgical edit proposals with apply/reject workflow
- Version history

### FR-09: Writing Tools
- Show-not-tell transformation
- Five-sense description generation
- Tone shift rewriting
- Brainstorm (plot, character, twist, setting, dialogue)
- Shrink ray (logline, blurb, synopsis, outline, pitch)
- First draft generation from scene description
- 3 parallel AI beta readers (casual, craft, market)

### FR-10: Writing Workflow
- Project briefs: genre, style, target words, character arcs, themes, POV, setting, audience
- Auto-populate project fields from text via LLM
- Adaptive next-step: outline → enrich → expand → polish
- Horizontal (expand text) and vertical (enrich structure) modes
- Budget control (1%/10%/50%/100%)
- Resumable across sessions
- Dynamic craft reference injection (randomized per call)

### FR-11: Version Reconstruction
- Ingest multiple version files
- Parse sections and detect cross-version references
- Reconstruct complete document from latest content per section
- Follow reference chains ("unchanged since vN")
- Flag gaps and confidence levels
- LLM smoothing of transitions

### FR-12: OCR
- Single image OCR (Tesseract)
- PDF OCR with searchable PDF output (OCRmyPDF)
- Multi-engine escalation: Tesseract → OCR.space → Gemini Vision
- Async jobs for large documents
- 9 languages: eng, fra, deu, spa, ita, por, nld, rus, osd

### FR-13: Google Drive Integration
- OAuth authentication for private files
- Folder browsing with navigation
- Multi-file selection across directories
- Batch download and ingestion

### FR-14: OpenAI-Compatible API
- `POST /v1/chat/completions` — standard chat format
- `POST /v1/chat/completions/stream` — SSE streaming
- `GET /v1/models` — list available models
- Drop-in replacement for OpenAI/Ollama clients

### FR-15: Export
- HTML export: editable, with pacing SVG, thread bars, annotated text
- DOCX export: chapter headings, paragraphs
- Backup: tar.gz of all databases

## Non-Functional Requirements

### NFR-01: Performance
- Response time < 2s for cached queries
- Support 10+ concurrent users
- Streaming for real-time token delivery

### NFR-02: Cost Optimization
- Free-tier models prioritized
- Rate limit tracking with daily quotas
- Cost estimation before paid model use
- Semantic cache to avoid redundant LLM calls

### NFR-03: Security
- Cookie-based authentication
- Bearer token for API clients
- Premium model access restricted by user
- Docker internal network trusted (no auth)
- Sandboxed Python execution

### NFR-04: Reliability
- Automatic fallback on provider failure
- Graceful degradation when no providers available
- Persistent storage in Docker volumes
- One-click backup

### NFR-05: Extensibility
- New providers added by editing research.py + backends.py + keys.py
- Webhook system for external integrations
- Scheduled tasks for automation
- Prompt templates for common operations
