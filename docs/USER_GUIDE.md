# L'Intello — User Guide

## Table of Contents

1. [Chat Interface](#chat-interface)
2. [Literary Analysis](#literary-analysis)
3. [Writing Tools](#writing-tools)
4. [Writing Workflow](#writing-workflow)
5. [Version Reconstruction](#version-reconstruction)
6. [OCR](#ocr)
7. [Corkboard](#corkboard)
8. [Google Drive](#google-drive)
9. [Scheduled Tasks](#scheduled-tasks)
10. [API Reference](#api-reference)

---

## Chat Interface

**URL**: `/` (main page)

The chat works like ChatGPT but routes to the best model automatically.

### Modes

| Mode | What it does | When to use |
|------|-------------|-------------|
| ⚡ Auto | Picks the right mode based on complexity | Default — use this |
| 🏃 Fast | Single best model | Quick questions |
| 🔬 Deep | 3 models draft → cross-review → synthesize | Important analysis, code review |
| ⚔️ Debate | Models argue and challenge each other | Controversial topics, decision-making |

### Streaming
Check the **Stream** checkbox for real-time token display. Works with Groq, OpenAI, Mistral, DeepSeek.

### Conversations
- Click **💬** in the sidebar to see past conversations
- Click any conversation to resume it
- Click **+ New chat** to start fresh
- Context from previous messages is automatically included

### File Attachment
- Click **📎** to attach a file (any text file, code, CSV)
- Click **🔗** for Google Drive URLs
- The file content is prepended to your prompt

### Feedback
After each response, click ⭐ to rate it (1-5). This trains the routing engine to prefer better models for your tasks.

---

## Literary Analysis

**URL**: `/literary`

Upload any document and get instant structural analysis.

### Ingestion
- **Supported formats**: .txt, .md, .pdf, .epub
- Drag & drop or click the upload area
- Or paste text directly

### What you see after ingestion

**Left sidebar:**
- **📖 Structure** — chapters with line ranges. Click to navigate.
- **👤 Characters** — auto-detected via NER. Shows mention count.
- **📊 Pacing** — color-coded tension bars. 🟢 low, 🟡 medium, 🔴 high.
- **✏️ Pending Edits** — AI-suggested edits. Accept or reject each one.

**Main area:**
- **🧵 Narrative Threads** — colored horizontal bars showing open questions/mysteries. Hover for details. Click to jump to the source line.
- **📝 Text** — line-numbered text with dialogue highlighting and chapter headers.
- **Writing tools toolbar** — above the text viewer.

### Running Analysis
Click **🔬 Analyze** to run a deep multi-model analysis. This takes 30-60 seconds and produces:
- Structure assessment
- Pacing critique
- Prose quality feedback
- Specific edit suggestions (auto-added to Pending Edits)

### Export
- **📄 Export HTML** — rich editable report with pacing SVG, thread visualization, annotated text. Print to PDF or save.
- **DOCX** — via `/api/literary/{doc_id}/export/docx`

---

## Writing Tools

Available in the literary page toolbar:

| Tool | What it does |
|------|-------------|
| 👁️ **Show** | Converts "telling" prose to "showing" (actions, senses, behavior) |
| 🌸 **Describe** | Generates sight, sound, smell, touch, taste + metaphor for any element |
| 🎭 **Tone** | Rewrites a passage in a different tone (darker, funnier, more intimate...) |
| 💡 **Brainstorm** | Generates 5 ideas: plot, character, twist, setting, or dialogue |
| 🔍 **Shrink** | Compresses text into logline, blurb, synopsis, outline, or pitch |
| 📄 **Draft** | Generates ~1000 words of prose from a scene description |
| 📖 **Beta Read** | 3 AI readers (casual, craft expert, literary agent) review simultaneously |

### How to use
1. Select text in the viewer (or type in the input box)
2. Click a tool button
3. Fill in any extra fields (tone name, brainstorm category, etc.)
4. Click "Run"
5. Result appears in the purple output panel

---

## Writing Workflow

The workflow engine guides you from blank page to finished manuscript.

### Project Brief
Fill in at the top of the literary page:
- **Title, Genre** (fiction, non-fiction, screenplay, poetry, academic, technical)
- **Brief** — what the project is about
- **Target style** — e.g. "Hemingway", "noir", "lyrical"
- **Target word count** — e.g. 80,000
- **Key milestones** — one per line (plot beats, chapter goals)

### Auto-Populate
Click **🪄 Auto-fill Project** after uploading a document. An LLM reads your text and fills in: genre, style, intent, tone, POV, setting, audience, character arcs, themes.

### Workflow Panel
When a document is linked to a project, the workflow panel appears:

- **Phase indicator**: OUTLINE → ENRICH → EXPAND → POLISH
- **Next Step button**: label changes based on what's needed next
- **Mode toggle**: ↔️ Horizontal (expand text) vs ↕️ Vertical (enrich structure)
- **Budget control**: 1% / 10% / 50% / 100% of daily credits
- **Word progress bar**: current words vs target

### Horizontal vs Vertical

| Mode | What it does | When to use |
|------|-------------|-------------|
| ↔️ Horizontal | Writes new prose, advances the story | When you need more words |
| ↕️ Vertical | Adds subplots, side characters, foreshadowing, sensory detail | When structure needs depth |

### Resuming
Progress is saved automatically. Close the browser, come back tomorrow, and the workflow picks up where you left off.

---

## Version Reconstruction

**URL**: `/gdrive` (for file selection) + API endpoints

For projects with scattered version files (v1, v3, v21, v35...) where later versions reference earlier ones.

### Workflow
1. **Create a reconstruction project**: POST `/api/reconstruct/projects`
2. **Ingest version files**: upload individually or use the Drive browser to batch-select
3. **Rebuild**: POST `/api/reconstruct/{id}/rebuild`
4. **Review**: each section shows which version it came from and confidence level
5. **Smooth**: POST `/api/reconstruct/{id}/smooth` — LLM fixes transitions
6. **Export**: GET `/api/reconstruct/{id}/text`

### How it handles references
When a version says "unchanged since v21" or "see v23 for this section", the engine:
1. Detects the reference pattern
2. Finds version 21/23 in the ingested files
3. Pulls the actual content from that version
4. Marks the section with "medium" confidence

### Confidence levels
- **High**: latest version has full content
- **Medium**: content pulled via reference chain
- **Low**: best available, no definitive version found

---

## OCR

### Single Image
```
POST /api/v1/ocr
file: image.png
language: eng
quality: auto  (fast | auto | best)
```

### PDF
```
POST /api/v1/ocr/pdf
file: scanned.pdf
output: searchable_pdf  (or json, text)
```

### Quality Modes
| Mode | Engine | Speed | Accuracy |
|------|--------|-------|----------|
| fast | Tesseract only | ~1s/page | Good for clean text |
| auto | Tesseract → OCR.space → Gemini | Varies | Escalates on low confidence |
| best | Gemini Vision directly | ~5s/page | Best for complex layouts |

### Async Jobs (large PDFs)
```
POST /api/v1/ocr/jobs  → returns job_id
GET /api/v1/ocr/jobs/{id}  → check progress
GET /api/v1/ocr/jobs/{id}/result  → download result
```

---

## Corkboard

**URL**: `/corkboard`

Visual visual board for organizing scenes.

- Select a document from the dropdown
- Chapters appear as index cards
- **Drag and drop** to reorder
- **Click** a card's synopsis area to edit it
- Cards show status badges (draft/revised/final)

---

## Google Drive

**URL**: `/gdrive`

Browse your Google Drive, select files across multiple folders, and batch-ingest them.

1. Navigate folders (double-click to enter)
2. Click files to select (checkmarks appear)
3. Navigate to other folders — selections persist
4. Select a reconstruction project from the dropdown
5. Click "Ingest N files"

Requires Google Drive OAuth — set up via `/api/gdrive/auth`.

---

## Scheduled Tasks

Create recurring AI tasks:

```
POST /api/scheduler/tasks
name: "Daily news summary"
prompt: "Summarize today's top AI news"
schedule: daily  (hourly | daily | weekly)
```

Tasks run automatically in the background. View results:
```
GET /api/scheduler/tasks
```

---

## API Reference

### Chat (OpenAI-compatible)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/chat/completions` | Standard chat |
| POST | `/v1/chat/completions/stream` | SSE streaming |
| GET | `/v1/models` | List models |

### Status
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/status` | Health + providers + OCR |
| GET | `/api/providers` | Detailed provider list |
| GET | `/api/usage/history` | Rate limit history |
| GET | `/api/cache/stats` | Cache statistics |
| GET | `/api/learning` | Model performance data |
| GET | `/api/templates` | Prompt templates |
| GET | `/api/backup` | Download full backup |

### Chat & Memory
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/prompt` | Main chat (with routing, tools, guardrails) |
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/{id}` | Get conversation messages |
| GET/POST | `/api/prefs` | User preferences |
| POST | `/api/feedback` | Rate a model response |

### Literary
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/literary/ingest` | Upload document |
| GET | `/api/literary/documents` | List documents |
| GET | `/api/literary/{id}` | Document details (structure, pacing, chars, threads) |
| GET | `/api/literary/{id}/lines` | Get text lines |
| GET | `/api/literary/{id}/edits` | Pending edits |
| POST | `/api/literary/{id}/analyze` | Run deep analysis |
| POST | `/api/literary/{id}/iterate` | Chunk-by-chunk analysis |
| POST | `/api/literary/{id}/append` | Append text |
| POST | `/api/literary/{id}/edit/{eid}/apply` | Apply edit |
| POST | `/api/literary/{id}/edit/{eid}/reject` | Reject edit |
| GET | `/api/literary/{id}/export` | HTML export |
| GET | `/api/literary/{id}/export/docx` | DOCX export |
| POST | `/api/literary/compare` | Compare two documents |

### Projects
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/literary/projects` | List/create projects |
| GET/POST | `/api/literary/projects/{id}` | Get/update project |
| POST | `/api/literary/projects/{id}/auto-populate` | Auto-fill from text |
| GET | `/api/literary/workflow/{id}` | Workflow state |
| POST | `/api/literary/workflow/{id}/next` | Execute next step |

### Writing Tools
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/tools/transform` | Show/describe/tone/brainstorm/shrink/draft |
| POST | `/api/tools/beta-read` | 3 AI beta readers |

### Reconstruction
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/reconstruct/projects` | List/create |
| POST | `/api/reconstruct/{id}/ingest` | Upload version file |
| POST | `/api/reconstruct/{id}/ingest-gdrive` | Batch ingest from Drive |
| GET | `/api/reconstruct/{id}/versions` | List versions |
| POST | `/api/reconstruct/{id}/rebuild` | Reconstruct document |
| GET | `/api/reconstruct/{id}/text` | Get reconstructed text |
| POST | `/api/reconstruct/{id}/smooth` | LLM smooth transitions |

### OCR
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/ocr` | Single image OCR |
| POST | `/api/v1/ocr/pdf` | PDF OCR |
| POST | `/api/v1/ocr/jobs` | Async OCR job |
| GET | `/api/v1/ocr/jobs/{id}` | Job status |
| GET | `/api/v1/ocr/jobs/{id}/result` | Job result |

### Google Drive
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/gdrive/status` | Auth status |
| GET | `/api/gdrive/auth` | Start OAuth |
| GET | `/api/gdrive/browse` | List folder contents |
| POST | `/api/gdrive/batch` | Fetch multiple files |

### Integrations
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/image/generate` | Image generation |
| POST | `/api/v1/voice/transcribe` | Speech-to-text |
| GET/POST | `/api/scheduler/tasks` | Scheduled tasks |
| POST | `/api/scheduler/run` | Run due tasks now |
| GET/POST | `/api/webhooks` | Webhook management |
| POST | `/api/webhooks/{id}/trigger` | Trigger webhook |
| POST | `/api/key` | Add API key at runtime |
