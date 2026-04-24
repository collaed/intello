# L'Intello — Migration from AI Router

## What changed

**AI Router** has been renamed to **L'Intello** (`intello`) and upgraded with proper NLP frameworks and OCR services.

## New coordinates

| What | Old | New |
|------|-----|-----|
| GitHub repo | `github.com/collaed/airouter` | `github.com/collaed/intello` |
| Docker container | `airouter` | `intello` |
| Docker volume | `airouter_airouter-data` | `intello_intello-data` |
| Python package | `airouter/` | `intello/` |
| Web UI | `your-domain.com/intello/` | `your-domain.com/intello/` |
| Internal URL | `http://airouter:8000` | `http://intello:8000` |
| Cookie name | `airouter_token` | `intello_token` |

## Services

### LLM Routing
- 28 models across 13 providers (OpenAI, Gemini, Groq, Mistral, DeepSeek, Cohere, OpenRouter, Cloudflare, NanoGPT, x.ai, Ollama)
- OpenAI-compatible API at `/v1/chat/completions`
- Modes: Fast, Deep (cross-review), Debate, Chain, Auto
- Semantic cache with sentence-transformer embeddings
- Cross-session learning from user feedback

### OCR Service
- **Engine**: Tesseract + OCRmyPDF
- **Languages**: English, French, German, Spanish, Italian, Portuguese, Dutch, Russian
- **Endpoints**:
  - `POST /api/v1/ocr` — single image OCR (returns text + bounding boxes + confidence)
  - `POST /api/v1/ocr/pdf` — PDF OCR (returns per-page text or searchable PDF)
  - `POST /api/v1/ocr/jobs` — async job for large PDFs (200+ pages)
  - `GET /api/v1/ocr/jobs/{id}` — check job progress
  - `GET /api/v1/ocr/jobs/{id}/result` — download result
- **Fallback**: when Tesseract confidence is low, Surya ML-based OCR can be added (planned)

### Literary Analysis
- Document ingestion: **.txt, .md, .pdf, .epub** supported
- **spaCy NER** for character extraction (replaces hand-rolled regex)
- **textstat** for readability metrics (Flesch-Kincaid, etc.)
- **sentence-transformers** for semantic cache (replaces Jaccard similarity)
- **pymupdf** for PDF text extraction
- Pacing analysis, narrative thread tracking, surgical edits
- Writing tools: show-not-tell, 5-sense describe, tone shift, brainstorm, beta readers
- Workflow engine with horizontal/vertical modes

### Status / Health
```
GET /api/v1/status
{
  "available": true,
  "total_available": 24,
  "free_available": 19,
  "ocr": {
    "available": true,
    "engine": "tesseract+ocrmypdf",
    "languages": ["eng", "fra", "deu", "spa", "ita", "por", "nld", "rus"]
  }
}
```

## For API clients (External clients, etc.)

Update your configuration:

```
# Old
AIROUTER_URL=http://airouter:8000

# New
INTELLO_URL=http://intello:8000
```

The API is unchanged:
- `POST /v1/chat/completions` — OpenAI-compatible chat
- `GET /v1/models` — list available models
- `GET /api/v1/status` — health check (now includes OCR status)
- `POST /api/v1/ocr` — image OCR
- `POST /api/v1/ocr/pdf` — PDF OCR

Authentication:
- Docker internal network (172.x.x.x): no auth required
- External: Bearer token, cookie login, or Basic auth

## NLP Framework Upgrades

| Component | Before (hand-rolled) | After (framework) |
|-----------|---------------------|-------------------|
| Character extraction | Capitalized word frequency + stopword list | **spaCy NER** (PERSON entities, multi-word names) |
| Sentence segmentation | `re.split(r'[.!?]+')` | **spaCy** sentence boundary detection |
| Semantic cache | Jaccard word overlap (0.56 for similar prompts) | **sentence-transformers** cosine similarity (0.95+) |
| Readability metrics | Word count / sentence count | **textstat** (Flesch-Kincaid, Dale-Chall, etc.) |
| PDF ingestion | Not supported | **pymupdf** (text + metadata extraction) |
| EPUB ingestion | Not supported | **zipfile + HTML parser** |

## Decommissioning airouter

Once all clients are updated:

```bash
cd /opt/apps/airouter
docker compose down
# Optional: docker volume rm airouter_airouter-data
```

## Why the rename?

"AI Router" described what it did in March 2026 — route prompts to LLMs. Since then it grew into a literary analysis engine, writing toolkit, OCR service, and external clients backend. "L'Intello" (French slang for "the brainy one") better reflects what it is: a smart backend that handles any AI task.
