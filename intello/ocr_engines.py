"""Multi-engine OCR — escalates from fast/free to accurate/smart based on confidence."""
import base64
import os
import httpx

# Engine priority: Tesseract (fast) → OCR.space (free API) → Gemini Vision (LLM-based)
# Each engine is tried only if the previous one's confidence is below threshold.

CONFIDENCE_THRESHOLD = 70.0  # Below this, try next engine


async def ocr_space(image_path: str, language: str = "eng") -> dict:
    """OCR via OCR.space free API (25K pages/month, no key needed for basic)."""
    lang_map = {"eng": "eng", "fra": "fre", "deu": "ger", "spa": "spa",
                "ita": "ita", "por": "por", "nld": "dut", "rus": "rus"}
    ocr_lang = lang_map.get(language, "eng")

    with open(image_path, "rb") as f:
        img_data = f.read()

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://api.ocr.space/parse/image",
            data={"language": ocr_lang, "isOverlayRequired": "true",
                  "OCREngine": "2"},  # Engine 2 is better for most text
            files={"file": ("image.png", img_data, "image/png")})

    if r.status_code != 200:
        return {"text": "", "confidence": 0, "engine": "ocr.space", "error": f"HTTP {r.status_code}"}

    data = r.json()
    results = data.get("ParsedResults", [{}])
    if not results:
        return {"text": "", "confidence": 0, "engine": "ocr.space", "error": "No results"}

    text = results[0].get("ParsedText", "")
    # OCR.space doesn't give a confidence score directly, estimate from exit code
    exit_code = results[0].get("FileParseExitCode", -1)
    confidence = 85.0 if exit_code == 1 and text.strip() else 30.0

    return {"text": text.strip(), "confidence": confidence, "engine": "ocr.space"}


async def gemini_vision_ocr(image_path: str, language: str = "eng") -> dict:
    """OCR via Gemini Vision — LLM-based, understands layout and context."""
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY_2")
    if not api_key:
        # Try saved keys
        try:
            import json
            keys_file = os.environ.get("KEYS_FILE", "/data/api_keys.json")
            if os.path.exists(keys_file):
                with open(keys_file) as f:
                    keys = json.load(f)
                api_key = keys.get("GOOGLE_API_KEY") or keys.get("GOOGLE_API_KEY_2")
        except Exception:
            pass

    if not api_key:
        return {"text": "", "confidence": 0, "engine": "gemini", "error": "No Google API key"}

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    lang_names = {"eng": "English", "fra": "French", "deu": "German", "spa": "Spanish",
                  "ita": "Italian", "por": "Portuguese", "nld": "Dutch", "rus": "Russian"}
    lang_name = lang_names.get(language, "English")

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [
                    {"text": f"Extract ALL text from this image. The text is in {lang_name}. "
                             f"Return ONLY the extracted text, preserving line breaks and formatting. "
                             f"Do not add commentary."},
                    {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                ]}],
            })

    if r.status_code != 200:
        return {"text": "", "confidence": 0, "engine": "gemini", "error": f"HTTP {r.status_code}"}

    data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return {"text": text.strip(), "confidence": 92.0, "engine": "gemini"}
    except (KeyError, IndexError):
        return {"text": "", "confidence": 0, "engine": "gemini", "error": "Parse failed"}


async def smart_ocr(image_path: str, language: str = "eng", quality: str = "auto") -> dict:
    """
    Multi-engine OCR with automatic escalation.
    quality: "fast" (Tesseract only), "auto" (escalate on low confidence), "best" (Gemini directly)
    """
    from . import ocr as ocr_local

    if quality == "best":
        result = await gemini_vision_ocr(image_path, language)
        if result["confidence"] > 0:
            return result
        # Fall back to local
        return ocr_local.ocr_image(image_path, language) | {"engine": "tesseract"}

    # Start with Tesseract (fastest, free, local)
    result = ocr_local.ocr_image(image_path, language)
    result["engine"] = "tesseract"

    if quality == "fast" or result["confidence"] >= CONFIDENCE_THRESHOLD:
        return result

    # Escalate to OCR.space (free cloud API)
    cloud_result = await ocr_space(image_path, language)
    if cloud_result["confidence"] > result["confidence"]:
        result = cloud_result

    if result["confidence"] >= CONFIDENCE_THRESHOLD:
        return result

    # Escalate to Gemini Vision (LLM-based, best accuracy)
    gemini_result = await gemini_vision_ocr(image_path, language)
    if gemini_result["confidence"] > result["confidence"]:
        result = gemini_result

    return result
