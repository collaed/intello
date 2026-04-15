"""Image generation routing — routes to providers with image gen capability."""


def build_image_prompt(description: str, style: str = "") -> str:
    return f"{description}{f', style: {style}' if style else ''}"


async def generate_image(description: str, providers: list, style: str = "") -> dict:
    """Generate an image using the best available provider."""
    import httpx, os, json, base64

    # Try Gemini (free, has image understanding)
    for p in providers:
        if p.available and p.provider == "google":
            api_key = p.api_key
            try:
                async with httpx.AsyncClient(timeout=60) as c:
                    r = await c.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                        json={"contents": [{"parts": [{"text": f"Generate a detailed description of this image concept that an artist could paint: {description}. {f'Style: {style}' if style else ''}"}]}]})
                    data = r.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return {"type": "description", "content": text, "provider": p.name,
                            "note": "Image description generated (text-to-image requires DALL-E or similar)"}
            except Exception:
                continue

    # Try OpenAI DALL-E
    for p in providers:
        if p.available and p.provider == "openai":
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=p.api_key)
                result = await client.images.generate(
                    model="dall-e-3", prompt=build_image_prompt(description, style),
                    size="1024x1024", n=1)
                return {"type": "image_url", "url": result.data[0].url,
                        "provider": p.name, "revised_prompt": result.data[0].revised_prompt}
            except Exception as e:
                return {"type": "error", "error": str(e), "provider": p.name}

    return {"type": "error", "error": "No image generation providers available"}
