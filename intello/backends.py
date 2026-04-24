"""LLM execution backends."""
import os
from .models import LLMProvider, LLMResponse

SYSTEM_DEFAULT = (
    "You are a brutally honest AI assistant. You never sugarcoat, hedge, or add "
    "unnecessary caveats. You give direct, frank assessments. If something is bad, "
    "you say so plainly. If the user is wrong, you correct them without apology. "
    "You prioritize truth and clarity over politeness."
)


def _msgs(prompt: str, system: str | None = None) -> list[dict]:
    s = system or SYSTEM_DEFAULT
    return [{"role": "system", "content": s}, {"role": "user", "content": prompt}]


async def _call_openai(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=provider.api_key)
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    cost = (inp / 1000) * provider.cost_per_1k_input + (out / 1000) * provider.cost_per_1k_output
    return LLMResponse(provider.name, provider.model_id, c, inp, out, cost)


async def _call_anthropic(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=provider.api_key)
    resp = await client.messages.create(
        model=provider.model_id, max_tokens=max_tokens,
        system=system or SYSTEM_DEFAULT,
        messages=[{"role": "user", "content": prompt}],
    )
    c = resp.content[0].text if resp.content else ""
    inp, out = resp.usage.input_tokens, resp.usage.output_tokens
    cost = (inp / 1000) * provider.cost_per_1k_input + (out / 1000) * provider.cost_per_1k_output
    return LLMResponse(provider.name, provider.model_id, c, inp, out, cost)


async def _call_google(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    import google.generativeai as genai
    genai.configure(api_key=provider.api_key)
    model = genai.GenerativeModel(provider.model_id,
                                  system_instruction=system or SYSTEM_DEFAULT)
    resp = await model.generate_content_async(
        prompt, generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
    )
    c = resp.text if resp.text else ""
    inp = getattr(resp.usage_metadata, "prompt_token_count", 0) or 0
    out = getattr(resp.usage_metadata, "candidates_token_count", 0) or 0
    cost = (inp / 1000) * provider.cost_per_1k_input + (out / 1000) * provider.cost_per_1k_output
    return LLMResponse(provider.name, provider.model_id, c, inp, out, cost)


async def _call_groq(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=provider.api_key, base_url="https://api.groq.com/openai/v1")
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    return LLMResponse(provider.name, provider.model_id, c, inp, out, 0.0)


async def _call_mistral(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=provider.api_key, base_url="https://api.mistral.ai/v1")
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    return LLMResponse(provider.name, provider.model_id, c, inp, out, 0.0)


async def _call_deepseek(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=provider.api_key, base_url="https://api.deepseek.com")
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    cost = (inp / 1000) * provider.cost_per_1k_input + (out / 1000) * provider.cost_per_1k_output
    return LLMResponse(provider.name, provider.model_id, c, inp, out, cost)


async def _call_xai(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=provider.api_key, base_url="https://api.x.ai/v1")
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    cost = (inp / 1000) * provider.cost_per_1k_input + (out / 1000) * provider.cost_per_1k_output
    return LLMResponse(provider.name, provider.model_id, c, inp, out, cost)


async def _call_cohere(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    import httpx
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post("https://api.cohere.com/v2/chat",
            headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
            json={"model": provider.model_id, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system or SYSTEM_DEFAULT},
                               {"role": "user", "content": prompt}]})
        data = resp.json()
    c = data.get("message", {}).get("content", [{}])[0].get("text", "")
    u = data.get("usage", {}).get("tokens", {})
    inp = u.get("input_tokens", 0)
    out = u.get("output_tokens", 0)
    return LLMResponse(provider.name, provider.model_id, c, inp, out, 0.0)


async def _call_openrouter(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=provider.api_key, base_url="https://openrouter.ai/api/v1",
                         default_headers={"HTTP-Referer": os.environ.get("INTELLO_URL", "https://github.com/collaed/intello"),
                                          "X-Title": "AI Router"})
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    return LLMResponse(provider.name, provider.model_id, c, inp, out, 0.0)


async def _call_cloudflare(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    import httpx, os
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{provider.model_id}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url,
            headers={"Authorization": f"Bearer {provider.api_key}"},
            json={"messages": _msgs(prompt, system), "max_tokens": max_tokens})
        data = resp.json()
    c = data.get("result", {}).get("response", "")
    return LLMResponse(provider.name, provider.model_id, c, 0, 0, 0.0)


async def _call_nanogpt(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=provider.api_key, base_url="https://nano-gpt.com/api")
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    cost = (inp / 1000) * provider.cost_per_1k_input + (out / 1000) * provider.cost_per_1k_output
    return LLMResponse(provider.name, provider.model_id, c, inp, out, cost)


async def _call_ollama(provider: LLMProvider, prompt: str, max_tokens: int, system: str | None = None) -> LLMResponse:
    from openai import AsyncOpenAI
    base_url = provider.api_key or "http://localhost:11434/v1"
    client = AsyncOpenAI(api_key="ollama", base_url=base_url)
    resp = await client.chat.completions.create(
        model=provider.model_id, messages=_msgs(prompt, system), max_tokens=max_tokens,
    )
    c = resp.choices[0].message.content or ""
    u = resp.usage
    inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
    return LLMResponse(provider.name, provider.model_id, c, inp, out, 0.0)


_BACKENDS = {
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "google": _call_google,
    "google_cloud": _call_google,
    "groq": _call_groq,
    "mistral": _call_mistral,
    "deepseek": _call_deepseek,
    "xai": _call_xai,
    "cohere": _call_cohere,
    "openrouter": _call_openrouter,
    "cloudflare": _call_cloudflare,
    "nanogpt": _call_nanogpt,
    "ollama": _call_ollama,
}
async def execute(provider: LLMProvider, prompt: str, max_tokens: int = 4096,
                  system: str | None = None, timeout: int = 30) -> LLMResponse:
    """Execute a prompt against a provider, with timeout and fallback error handling."""
    import asyncio
    from . import ratelimit

    rem = ratelimit.remaining(provider.model_id, provider.daily_limit)
    if rem == 0:
        return LLMResponse(provider.name, provider.model_id,
                           f"[Rate limit exhausted for today (0/{provider.daily_limit})]", degraded=True)

    backend = _BACKENDS.get(provider.provider)
    if not backend:
        return LLMResponse(provider.name, provider.model_id,
                           f"[No backend for provider: {provider.provider}]", degraded=True)
    try:
        result = await asyncio.wait_for(
            backend(provider, prompt, max_tokens, system),
            timeout=timeout
        )
        ratelimit.record_usage(provider.model_id)
        return result
    except asyncio.TimeoutError:
        return LLMResponse(provider.name, provider.model_id,
                           f"[Timeout after {timeout}s]", degraded=True)
    except Exception as e:
        return LLMResponse(provider.name, provider.model_id,
                           f"[Error: {e}]", degraded=True)
