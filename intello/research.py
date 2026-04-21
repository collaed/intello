"""Market research module — probes reference sites to understand the LLM landscape."""
import httpx
from bs4 import BeautifulSoup

from .models import LLMProvider, TaskType, Tier

# Curated baseline knowledge (updated by live probing)
BASELINE_PROVIDERS: list[LLMProvider] = [
    # --- FREE TIER ---
    LLMProvider("GPT-4o Mini", "gpt-4o-mini", "openai", Tier.FREE, 128_000,
                [TaskType.GENERAL, TaskType.CODE, TaskType.ANALYSIS],
                0.00015, 0.0006, "OPENAI_API_KEY",
                notes="Free tier via OpenAI playground / low-cost API", daily_limit=200),
    LLMProvider("Gemini 2.0 Flash", "gemini-2.0-flash", "google", Tier.FREE, 1_000_000,
                [TaskType.GENERAL, TaskType.LONG_CONTEXT, TaskType.VISION, TaskType.CODE],
                0.0, 0.0, "GOOGLE_API_KEY",
                notes="Free tier via Google AI Studio", daily_limit=1500),
    LLMProvider("Gemini 2.5 Pro (free)", "gemini-2.5-pro-preview-03-25", "google", Tier.FREE, 1_000_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS, TaskType.LONG_CONTEXT],
                0.0, 0.0, "GOOGLE_API_KEY",
                notes="Free tier via Google AI Studio, rate-limited", daily_limit=50),
    LLMProvider("Gemini 2.0 Flash (B)", "gemini-2.0-flash", "google", Tier.FREE, 1_000_000,
                [TaskType.GENERAL, TaskType.LONG_CONTEXT, TaskType.VISION, TaskType.CODE],
                0.0, 0.0, "GOOGLE_API_KEY_2",
                notes="Second API key, doubles Gemini quota", daily_limit=1500),
    LLMProvider("Gemini 2.5 Flash", "gemini-2.5-flash", "google", Tier.FREE, 1_000_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS, TaskType.LONG_CONTEXT, TaskType.GENERAL],
                0.0, 0.0, "GOOGLE_API_KEY_2",
                notes="Thinking model, 1M context, great for deep analysis", daily_limit=500),
    LLMProvider("Llama 3.3 70B (Groq)", "llama-3.3-70b-versatile", "groq", Tier.FREE, 128_000,
                [TaskType.GENERAL, TaskType.CODE, TaskType.CREATIVE],
                0.0, 0.0, "GROQ_API_KEY",
                notes="Free tier on Groq, very fast inference", daily_limit=1000),
    LLMProvider("Mixtral 8x7B (Groq)", "mixtral-8x7b-32768", "groq", Tier.FREE, 32_768,
                [TaskType.GENERAL, TaskType.CODE],
                0.0, 0.0, "GROQ_API_KEY",
                notes="Free tier on Groq", daily_limit=1000),
    LLMProvider("Mistral Small (free)", "mistral-small-latest", "mistral", Tier.FREE, 32_000,
                [TaskType.GENERAL, TaskType.CODE],
                0.0, 0.0, "MISTRAL_API_KEY",
                notes="Free tier on Mistral platform", daily_limit=1000),
    LLMProvider("Qwen3 32B (Groq)", "qwen/qwen3-32b", "groq", Tier.FREE, 128_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS, TaskType.CREATIVE],
                0.0, 0.0, "GROQ_API_KEY",
                notes="Reasoning model on Groq, strong at analysis", daily_limit=1000),
    LLMProvider("Kimi K2 (Groq)", "moonshotai/kimi-k2-instruct", "groq", Tier.FREE, 128_000,
                [TaskType.CODE, TaskType.ANALYSIS, TaskType.GENERAL],
                0.0, 0.0, "GROQ_API_KEY",
                notes="Moonshot Kimi K2 on Groq, strong reasoning", daily_limit=1000),
    LLMProvider("Llama 4 Scout (Groq)", "meta-llama/llama-4-scout-17b-16e-instruct", "groq", Tier.FREE, 128_000,
                [TaskType.GENERAL, TaskType.CODE, TaskType.CREATIVE],
                0.0, 0.0, "GROQ_API_KEY",
                notes="Llama 4 on Groq, MoE architecture", daily_limit=1000),
    LLMProvider("DeepSeek V3", "deepseek-chat", "deepseek", Tier.FREE, 64_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS],
                0.00014, 0.00028, "DEEPSEEK_API_KEY",
                notes="Very cheap, near-free for moderate usage", daily_limit=500),
    LLMProvider("Command A (Cohere)", "command-a-vision-07-2025", "cohere", Tier.FREE, 128_000,
                [TaskType.ANALYSIS, TaskType.LONG_CONTEXT, TaskType.GENERAL, TaskType.CREATIVE, TaskType.VISION],
                0.0, 0.0, "COHERE_API_KEY",
                notes="Free tier, strong at RAG and document analysis", daily_limit=1000),
    # --- OpenRouter (free models via meta-provider) ---
    LLMProvider("Llama 3.3 70B (OR)", "meta-llama/llama-3.3-70b-instruct:free", "openrouter", Tier.FREE, 65_536,
                [TaskType.GENERAL, TaskType.CODE, TaskType.CREATIVE],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter", daily_limit=200),
    LLMProvider("Hermes 3 405B (OR)", "nousresearch/hermes-3-llama-3.1-405b:free", "openrouter", Tier.FREE, 131_072,
                [TaskType.GENERAL, TaskType.CODE, TaskType.ANALYSIS, TaskType.CREATIVE],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, largest open model", daily_limit=200),
    LLMProvider("Qwen3 Coder (OR)", "qwen/qwen3-coder:free", "openrouter", Tier.FREE, 262_000,
                [TaskType.CODE, TaskType.MATH],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, code specialist, 262K context", daily_limit=200),
    LLMProvider("Nemotron 120B (OR)", "nvidia/nemotron-3-super-120b-a12b:free", "openrouter", Tier.FREE, 262_144,
                [TaskType.CODE, TaskType.ANALYSIS, TaskType.MATH, TaskType.GENERAL],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, NVIDIA 120B MoE", daily_limit=200),
    LLMProvider("Gemma 4 31B (OR)", "google/gemma-4-31b-it:free", "openrouter", Tier.FREE, 262_144,
                [TaskType.GENERAL, TaskType.CODE, TaskType.CREATIVE],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, Google Gemma 4", daily_limit=200),
    LLMProvider("MiniMax M2.5 (OR)", "minimax/minimax-m2.5:free", "openrouter", Tier.FREE, 196_608,
                [TaskType.GENERAL, TaskType.CREATIVE, TaskType.ANALYSIS],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, 196K context", daily_limit=200),
    LLMProvider("GPT-OSS 120B (OR)", "openai/gpt-oss-120b:free", "openrouter", Tier.FREE, 131_072,
                [TaskType.GENERAL, TaskType.CODE, TaskType.ANALYSIS],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, OpenAI open-source 120B", daily_limit=200),
    LLMProvider("GLM 4.5 Air (OR)", "z-ai/glm-4.5-air:free", "openrouter", Tier.FREE, 131_072,
                [TaskType.GENERAL, TaskType.CODE, TaskType.CREATIVE],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, Zhipu GLM", daily_limit=200),
    LLMProvider("DeepSeek R1 (OR)", "deepseek/deepseek-r1:free", "openrouter", Tier.FREE, 64_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS],
                0.0, 0.0, "OPENROUTER_API_KEY",
                notes="Free via OpenRouter, reasoning model", daily_limit=200),
    # --- Cloudflare Workers AI (free 10k req/day) ---
    LLMProvider("Llama 3.3 70B (CF)", "@cf/meta/llama-3.3-70b-instruct-fp8-fast", "cloudflare", Tier.FREE, 32_000,
                [TaskType.GENERAL, TaskType.CODE, TaskType.CREATIVE],
                0.0, 0.0, "CLOUDFLARE_API_KEY",
                notes="Free via Cloudflare Workers AI", daily_limit=10000),
    LLMProvider("DeepSeek R1 32B (CF)", "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b", "cloudflare", Tier.FREE, 32_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS],
                0.0, 0.0, "CLOUDFLARE_API_KEY",
                notes="Free via Cloudflare Workers AI, reasoning", daily_limit=10000),
    LLMProvider("Qwen 2.5 Coder 32B (CF)", "@cf/qwen/qwen2.5-coder-32b-instruct", "cloudflare", Tier.FREE, 32_000,
                [TaskType.CODE, TaskType.MATH],
                0.0, 0.0, "CLOUDFLARE_API_KEY",
                notes="Free via Cloudflare Workers AI, code specialist", daily_limit=10000),
    # --- NanoGPT (meta-provider, pay-per-use, very cheap) ---
    LLMProvider("GPT-5 Nano (NanoGPT)", "openai/gpt-5-nano", "nanogpt", Tier.PAID, 400_000,
                [TaskType.GENERAL, TaskType.CODE, TaskType.ANALYSIS],
                0.00005, 0.0004, "NANOGPT_API_KEY",
                notes="GPT-5 nano via NanoGPT, extremely cheap"),
    LLMProvider("Claude Sonnet 4.5 (NanoGPT)", "claude-sonnet-4-5-20250929", "nanogpt", Tier.PAID, 200_000,
                [TaskType.CODE, TaskType.ANALYSIS, TaskType.CREATIVE],
                0.003, 0.015, "NANOGPT_API_KEY",
                notes="Claude Sonnet 4.5 via NanoGPT"),
    LLMProvider("Gemini 2.5 Flash Lite (NanoGPT)", "gemini-2.5-flash-lite", "nanogpt", Tier.PAID, 1_000_000,
                [TaskType.GENERAL, TaskType.LONG_CONTEXT, TaskType.CODE],
                0.0001, 0.0004, "NANOGPT_API_KEY",
                notes="Gemini 2.5 Flash Lite via NanoGPT, very cheap"),
    # --- Ollama (local, free) ---
    LLMProvider("Ollama (local)", "llama3.2", "ollama", Tier.FREE, 128_000,
                [TaskType.GENERAL, TaskType.CODE, TaskType.ANALYSIS, TaskType.CREATIVE],
                0.0, 0.0, "OLLAMA_URL",
                notes="Local LLM via Ollama, set OLLAMA_URL to http://host:11434/v1"),
    # --- PAID TIER (unlimited) ---
    LLMProvider("GPT-4o", "gpt-4o", "openai", Tier.PAID, 128_000,
                [TaskType.GENERAL, TaskType.CODE, TaskType.ANALYSIS, TaskType.VISION],
                0.0025, 0.01, "OPENAI_API_KEY"),
    LLMProvider("Claude 3.5 Sonnet", "claude-3-5-sonnet-20241022", "anthropic", Tier.PAID, 200_000,
                [TaskType.CODE, TaskType.ANALYSIS, TaskType.CREATIVE],
                0.003, 0.015, "ANTHROPIC_API_KEY"),
    LLMProvider("Claude 3 Haiku", "claude-3-haiku-20240307", "anthropic", Tier.PAID, 200_000,
                [TaskType.GENERAL, TaskType.CODE],
                0.00025, 0.00125, "ANTHROPIC_API_KEY"),
    LLMProvider("Gemini 2.5 Pro (paid)", "gemini-2.5-pro-preview-03-25", "google_cloud", Tier.PAID, 1_000_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS, TaskType.LONG_CONTEXT],
                0.00125, 0.01, "GOOGLE_CLOUD_API_KEY",
                notes="Usage-based via Google Cloud Vertex AI"),
    LLMProvider("Grok 4-1 Fast", "grok-4-1-fast", "xai", Tier.PAID, 131_072,
                [TaskType.GENERAL, TaskType.CODE, TaskType.ANALYSIS, TaskType.CREATIVE],
                0.003, 0.012, "XAI_API_KEY",
                notes="x.ai credit-based"),
    # --- PREMIUM (pay-as-you-go, user-restricted) ---
    LLMProvider("Gemini 2.5 Pro (paid)", "gemini-2.5-pro", "google", Tier.PAID, 1_000_000,
                [TaskType.CODE, TaskType.MATH, TaskType.ANALYSIS, TaskType.LONG_CONTEXT, TaskType.CREATIVE],
                0.00125, 0.01, "GOOGLE_API_KEY",
                notes="Premium: pay-as-you-go, admin only"),
]

REFERENCE_URLS = [
    "https://artificialanalysis.ai/leaderboards/models",
    "https://huggingface.co/spaces/lmsys/chatbot-arena-leaderboard",
]


async def probe_reference_sites() -> dict:
    """Fetch headlines/snippets from reference sites for market context."""
    findings: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for url in REFERENCE_URLS:
            try:
                resp = await client.get(url, headers={"User-Agent": "AIRouter/1.0"})
                soup = BeautifulSoup(resp.text, "html.parser")
                # Extract text snippets (titles, headings, table cells)
                texts = []
                for tag in soup.find_all(["h1", "h2", "h3", "th", "td", "title"], limit=60):
                    t = tag.get_text(strip=True)
                    if t and len(t) > 2:
                        texts.append(t)
                findings[url] = " | ".join(texts[:40])
            except Exception as e:
                findings[url] = f"[probe failed: {e}]"
    return findings


def get_providers() -> list[LLMProvider]:
    """Return a copy of baseline providers."""
    import copy
    return copy.deepcopy(BASELINE_PROVIDERS)
