# L'Intello

*The brainy one* — a smart AI backend for multi-LLM routing, literary analysis, writing tools, OCR, and document reconstruction.

## Quick Start

```bash
git clone https://github.com/collaed/intello.git
cd intello
cp .env.example .env    # Add your API keys
docker compose up -d    # → http://localhost:8000
```

Get a free Groq key at https://console.groq.com — that's enough to start.

## What it does

### 🤖 Multi-LLM Routing
29 models across 13 providers. Ask a question → L'Intello picks the best free model, falls back on failure, caches responses, and learns from your feedback.

### 📚 Literary Analysis
Upload a novel (TXT/PDF/EPUB) → get chapter structure, character tracking (spaCy NER), pacing curves, narrative thread visualization, and AI-powered edit suggestions.

### ✍️ Writing Tools
Show-not-tell, 5-sense describe, tone shift, brainstorm, shrink ray, first draft generator, 3 AI beta readers in parallel.

### 🔄 Writing Workflow
Project briefs → adaptive next-step → horizontal (expand) / vertical (enrich) modes → word count tracking → resumable across sessions.

### 📄 OCR
Tesseract → OCR.space → Gemini Vision auto-escalation. Single images, PDFs, async jobs for large books. 9 languages.

### 🔗 Version Reconstruction
Upload 50+ scattered version files → detect cross-references → rebuild complete document → LLM-smooth transitions.

### 🔌 OpenAI-Compatible API
Drop-in replacement at `/v1/chat/completions`. Works with any OpenAI SDK client, Ollama, audiobookshelf.

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/GETTING_STARTED.md) | First steps for new users |
| [User Guide](docs/USER_GUIDE.md) | Complete feature guide + API reference |
| [Admin Setup](docs/ADMIN_SETUP.md) | Installation, configuration, deployment |
| [User Stories](docs/USER_STORIES.md) | 40+ user stories covering all features |
| [Requirements](docs/REQUIREMENTS.md) | Functional and non-functional requirements |
| [Migration](MIGRATION.md) | Migration from AI Router |

## Architecture

```
intello/
├── web.py              FastAPI app — 70+ routes, auth, all endpoints
├── backends.py         LLM execution (14 providers)
├── router.py           Task classification + scoring
├── pipeline.py         Deep mode (draft → review → synthesis)
├── debate.py           Multi-model adversarial debate
├── chains.py           Prompt chaining / task decomposition
├── literary.py         Document ingestion, structure, pacing, edits
├── workflow.py         Writing workflow engine
├── writing_tools.py    Sudowrite-style transformations
├── craft.py            Dynamic literary reference engine
├── reconstruct.py      Version reconstruction from scattered files
├── nlp.py              spaCy NER + linguistic analysis
├── cache.py            Semantic cache (sentence-transformers)
├── memory.py           Conversation memory + learning
├── guardrails.py       Anti-hallucination + word count
├── tools.py            Web search, calculator, Python eval
├── ocr.py              Tesseract + OCRmyPDF
├── ocr_engines.py      Multi-engine OCR escalation
├── imagegen.py         Image generation routing
├── scheduler.py        Recurring tasks
├── webhooks.py         External integrations
├── gdrive.py           Google Drive OAuth + browsing
├── keys.py             API key management
├── ratelimit.py        Daily quota tracking
├── models.py           Data models
├── research.py         Provider catalog (29 models)
└── static/
    ├── index.html      Chat UI (ChatGPT-style)
    ├── literary.html   Literary analysis page
    ├── corkboard.html  Scrivener-style scene board
    └── gdrive.html     Google Drive file browser
```

## Stats

- **6,100+ lines** of Python
- **1,500+ lines** of HTML/JS
- **70+ API routes**
- **29 LLM providers** (20 free, 41,850 free requests/day)
- **36 automated tests** (whitebox + greybox + blackbox)

## License

Private project.
