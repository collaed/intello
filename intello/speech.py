"""Speech services — Piper TTS (local) + Groq Whisper STT (cloud)."""
import os
import subprocess
import tempfile
from pathlib import Path

PIPER_BIN = "/opt/piper/piper"
VOICES_DIR = Path("/opt/piper/voices")

VOICE_MAP = {
    "en": "en_US-lessac-medium",
    "en_US": "en_US-lessac-medium",
    "fr": "fr_FR-siwis-medium",
    "fr_FR": "fr_FR-siwis-medium",
}


def get_available_voices() -> list[dict]:
    """List installed Piper voices."""
    voices = []
    if VOICES_DIR.exists():
        for f in VOICES_DIR.glob("*.onnx"):
            name = f.stem
            lang = name.split("-")[0] + "_" + name.split("-")[1] if "-" in name else name
            voices.append({"id": name, "language": lang, "path": str(f)})
    return voices


def tts_available() -> bool:
    return os.path.exists(PIPER_BIN)


def synthesize(text: str, language: str = "en", output_format: str = "wav") -> bytes | None:
    """Convert text to speech using Piper. Returns WAV bytes."""
    voice_name = VOICE_MAP.get(language, VOICE_MAP.get("en"))
    voice_path = VOICES_DIR / f"{voice_name}.onnx"

    if not voice_path.exists() or not tts_available():
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = f.name

    try:
        proc = subprocess.run(
            [PIPER_BIN, "--model", str(voice_path), "--output_file", out_path],
            input=text.encode("utf-8"),
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            return None

        with open(out_path, "rb") as f:
            return f.read()
    except (subprocess.TimeoutExpired, Exception):
        return None
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


async def transcribe_groq(audio_bytes: bytes, filename: str = "audio.wav",
                           language: str = "") -> dict:
    """Transcribe audio using Groq's free Whisper API."""
    import json

    # Find Groq API key
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        try:
            keys_file = os.environ.get("KEYS_FILE", "/data/api_keys.json")
            if os.path.exists(keys_file):
                with open(keys_file) as f:
                    keys = json.load(f)
                api_key = keys.get("GROQ_API_KEY")
        except Exception:
            pass

    if not api_key:
        return {"error": "No GROQ_API_KEY available"}

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

    with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name

    try:
        with open(tmp, "rb") as af:
            kwargs = {"model": "whisper-large-v3-turbo", "file": af}
            if language:
                kwargs["language"] = language
            transcript = await client.audio.transcriptions.create(**kwargs)
        return {"text": transcript.text, "provider": "groq", "model": "whisper-large-v3-turbo"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        os.unlink(tmp)
