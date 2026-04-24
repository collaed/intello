"""API key discovery, validation, and encrypted persistence."""
import base64
import hashlib
import json
import os
import asyncio
from typing import Optional

import httpx

from .models import LLMProvider
from intello.log import log

KEYS_FILE = os.environ.get("KEYS_FILE", "/data/api_keys.json")
KEYS_FILE_ENC = os.environ.get("KEYS_FILE_ENC", "/data/api_keys.enc")


def _get_cipher():
    """Get Fernet cipher from INTELLO_TOKEN. Returns None if cryptography not installed."""
    try:
        from cryptography.fernet import Fernet
        token = os.environ.get("INTELLO_TOKEN", "default-change-me")
        # Derive a 32-byte key from the token
        key = base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest())
        return Fernet(key)
    except ImportError:
        return None


def _load_saved_keys() -> dict[str, str]:
    """Load persisted keys — tries encrypted file first, falls back to plain JSON."""
    # Try encrypted
    cipher = _get_cipher()
    if cipher and os.path.exists(KEYS_FILE_ENC):
        try:
            with open(KEYS_FILE_ENC, "rb") as f:
                decrypted = cipher.decrypt(f.read())
            return json.loads(decrypted)
        except Exception:
            log.warning("Suppressed exception", exc_info=True)
    # Fall back to plain JSON (migrate on next save)
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE) as f:
                return json.load(f)
        except Exception:
            log.warning("Suppressed exception", exc_info=True)
    return {}


def _save_keys(keys: dict[str, str]) -> None:
    """Persist keys — encrypted if cryptography available, plain JSON as fallback."""
    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    cipher = _get_cipher()
    if cipher:
        encrypted = cipher.encrypt(json.dumps(keys).encode())
        with open(KEYS_FILE_ENC, "wb") as f:
            f.write(encrypted)
        # Remove plain file if it exists (migration)
        if os.path.exists(KEYS_FILE):
            os.unlink(KEYS_FILE)
    else:
        with open(KEYS_FILE, "w") as f:
            json.dump(keys, f)


def discover_keys(providers: list[LLMProvider]) -> list[LLMProvider]:
    """Populate api_key from saved keys, then environment variables (env wins)."""
    saved = _load_saved_keys()
    for p in providers:
        if p.env_key:
            p.api_key = os.environ.get(p.env_key) or saved.get(p.env_key)
            p.available = bool(p.api_key)
    return providers


async def _validate_openai(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_anthropic(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post("https://api.anthropic.com/v1/messages",
                         headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                  "content-type": "application/json"},
                         json={"model": "claude-3-haiku-20240307", "max_tokens": 1,
                               "messages": [{"role": "user", "content": "hi"}]})
        return r.status_code in (200, 429)  # 429 = valid key, rate limited


async def _validate_google(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
        return r.status_code == 200


async def _validate_groq(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.groq.com/openai/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_mistral(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.mistral.ai/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_deepseek(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.deepseek.com/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_xai(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.x.ai/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_cohere(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.cohere.com/v2/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_openrouter(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://openrouter.ai/api/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_cloudflare(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.cloudflare.com/client/v4/user/tokens/verify",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200 and r.json().get("success", False)


async def _validate_nanogpt(key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://nano-gpt.com/api/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
        return r.status_code == 200


async def _validate_ollama(key: str) -> bool:
    url = key if key.startswith("http") else "http://localhost:11434"
    async with httpx.AsyncClient(timeout=5) as c:
        try:
            r = await c.get(f"{url}/api/tags")
            return r.status_code == 200
        except Exception:
            return False


_VALIDATORS = {
    "openai": _validate_openai,
    "anthropic": _validate_anthropic,
    "google": _validate_google,
    "google_cloud": _validate_google,
    "groq": _validate_groq,
    "mistral": _validate_mistral,
    "deepseek": _validate_deepseek,
    "xai": _validate_xai,
    "cohere": _validate_cohere,
    "openrouter": _validate_openrouter,
    "cloudflare": _validate_cloudflare,
    "nanogpt": _validate_nanogpt,
    "ollama": _validate_ollama,
}


async def validate_keys(providers: list[LLMProvider]) -> list[LLMProvider]:
    """Validate discovered API keys against their endpoints."""
    seen: dict[str, bool] = {}

    async def _check(p: LLMProvider):
        if not p.api_key:
            return
        cache_key = f"{p.provider}:{p.api_key}"
        if cache_key in seen:
            p.available = seen[cache_key]
            return
        validator = _VALIDATORS.get(p.provider)
        if validator:
            try:
                ok = await validator(p.api_key)
            except Exception:
                ok = False
            p.available = ok
            seen[cache_key] = ok

    await asyncio.gather(*[_check(p) for p in providers])
    return providers


def add_key(providers: list[LLMProvider], env_key: str, value: str) -> None:
    """Manually inject an API key at runtime and persist it."""
    os.environ[env_key] = value
    for p in providers:
        if p.env_key == env_key:
            p.api_key = value
            p.available = True
    # Persist
    saved = _load_saved_keys()
    saved[env_key] = value
    _save_keys(saved)
