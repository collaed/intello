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
    """Convert text to speech using Piper (local). Returns WAV bytes."""
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


GROQ_VOICES = ["tara", "leah", "jess", "leo", "dan", "mara", "troy", "austin", "hannah"]


def synthesize_kokoro(text: str) -> bytes | None:
    """TTS via Kokoro — 82M params, CPU, high quality English. Apache 2.0."""
    try:
        from kokoro import KPipeline
        import soundfile as sf
        import io
        import numpy as np

        pipe = KPipeline(lang_code="a")  # 'a' = American English
        audio_segments = []
        for _, _, audio in pipe(text[:10000]):
            audio_segments.append(audio)

        if not audio_segments:
            return None

        full_audio = np.concatenate(audio_segments)
        buf = io.BytesIO()
        sf.write(buf, full_audio, 24000, format="WAV")
        return buf.getvalue()
    except ImportError:
        return None
    except Exception:
        return None


async def synthesize_groq(text: str, voice: str = "tara") -> bytes | None:
    """Convert text to speech using Groq Orpheus (cloud, high quality, expressive).
    Supports vocal directions: [cheerful] [sad] [whisper] [laughing] [surprised]
    """
    import json

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
        return None

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

    try:
        response = await client.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            voice=voice,
            input=text,
            response_format="wav",
        )
        return response.content
    except Exception:
        return None



async def synthesize_voxtral(text: str, voice_id: str = "") -> bytes | None:
    """TTS via Mistral Voxtral — high quality, 9 languages including French.
    Cost: $0.016 per 1,000 characters."""
    import json, base64, httpx

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        try:
            keys_file = os.environ.get("KEYS_FILE", "/data/api_keys.json")
            if os.path.exists(keys_file):
                with open(keys_file) as f:
                    keys = json.load(f)
                api_key = keys.get("MISTRAL_API_KEY")
        except Exception:
            pass

    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            body = {
                "model": "voxtral-mini-tts-2603",
                "input": text[:5000],  # cap at 5K chars per request
                "response_format": "wav",
            }
            if voice_id:
                body["voice_id"] = voice_id

            r = await client.post("https://api.mistral.ai/v1/audio/speech",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body)

            if r.status_code != 200:
                return None

            data = r.json()
            audio_b64 = data.get("audio_data", "")
            if audio_b64:
                return base64.b64decode(audio_b64)
    except Exception:
        pass
    return None

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
