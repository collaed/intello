"""Speech routes — TTS (Piper/Kokoro/Groq/Voxtral) + STT (Groq Whisper)."""
import asyncio
import os

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

from intello import speech
from intello import costs
from intello import jobs as jobsys

router = APIRouter(prefix="/api/v1/voice", tags=["speech"])


def _get_user(request):
    from intello.web import _get_user as gu
    return gu(request) if request else "anonymous"


@router.post("/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str = Form(""),
    async_mode: bool = Form(False),
):
    """Speech-to-text via Groq Whisper. async_mode=true for long audio."""
    audio_bytes = await file.read()

    if async_mode:
        job_id = jobsys.create_job("stt", f"Transcribe {file.filename} ({len(audio_bytes)//1024}KB)")
        asyncio.create_task(jobsys.run_async(job_id,
            speech.transcribe_groq(audio_bytes, file.filename or "audio.wav", language)))
        return {"job_id": job_id, "status": "queued",
                "poll": f"/api/jobs/{job_id}", "result": f"/api/jobs/{job_id}/result"}

    return await speech.transcribe_groq(audio_bytes, file.filename or "audio.wav", language)


@router.post("/synthesize")
async def voice_synthesize(
    text: str = Form(...),
    language: str = Form("en"),
    voice: str = Form(""),
    engine: str = Form("auto"),
    project_id: str = Form(""),
    async_mode: bool = Form(False),
    request: Request = None,
):
    """TTS. engine: auto|groq|voxtral|kokoro|piper. async_mode=true for long text."""
    user = _get_user(request)

    if engine == "auto":
        engine = "voxtral" if language.startswith("fr") else "groq"

    if async_mode:
        job_id = jobsys.create_job("tts", f"TTS {language} {len(text)} chars ({engine})")

        async def _run_tts():
            eng = engine
            audio = None
            used_engine = eng

            if eng == "voxtral":
                est = costs.estimate_tts_cost(text, "voxtral")
                if costs.check_budget(est, "global")["allowed"]:
                    audio = await speech.synthesize_voxtral(text, voice)
                    if audio:
                        costs.record_cost("tts", "voxtral", len(text), "characters",
                                          est, f"TTS async {language}", project_id, user)
                if not audio:
                    eng = "groq"

            if eng == "groq":
                audio = await speech.synthesize_groq(text, voice or "tara")
                used_engine = "groq"
                if not audio:
                    eng = "kokoro"

            if eng == "kokoro":
                audio = speech.synthesize_kokoro(text)
                used_engine = "kokoro"
                if not audio:
                    eng = "piper"

            if eng == "piper" and speech.tts_available():
                audio = speech.synthesize(text, language)
                used_engine = "piper"

            if audio:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir="/data") as f:
                    f.write(audio)
                    return {"audio_path": f.name, "engine": used_engine,
                            "size_bytes": len(audio), "language": language}
            return {"error": "TTS failed"}

        asyncio.create_task(jobsys.run_async(job_id, _run_tts()))
        return {"job_id": job_id, "status": "queued",
                "poll": f"/api/jobs/{job_id}", "result": f"/api/jobs/{job_id}/result"}

    # Sync mode
    if engine == "voxtral":
        est_cost = costs.estimate_tts_cost(text, "voxtral")
        if not costs.check_budget(est_cost, "global")["allowed"]:
            engine = "groq"
        else:
            audio = await speech.synthesize_voxtral(text, voice)
            if audio:
                costs.record_cost("tts", "voxtral", len(text), "characters",
                                  est_cost, f"TTS {language} {len(text)} chars", project_id, user)
                return Response(audio, media_type="audio/wav",
                                headers={"Content-Disposition": "attachment; filename=speech_voxtral.wav",
                                         "X-Cost-USD": str(round(est_cost, 6))})
            engine = "groq"

    if engine == "groq":
        audio = await speech.synthesize_groq(text, voice or "tara")
        if audio:
            return Response(audio, media_type="audio/wav",
                            headers={"Content-Disposition": "attachment; filename=speech_groq.wav"})
        engine = "kokoro"

    if engine == "kokoro":
        audio = speech.synthesize_kokoro(text)
        if audio:
            return Response(audio, media_type="audio/wav",
                            headers={"Content-Disposition": "attachment; filename=speech_kokoro.wav"})
        engine = "piper"

    if engine == "piper":
        if not speech.tts_available():
            return {"error": "Piper TTS not installed"}
        audio = speech.synthesize(text, language)
        if audio:
            return Response(audio, media_type="audio/wav",
                            headers={"Content-Disposition": f"attachment; filename=speech_{language}.wav"})

    return {"error": f"TTS failed (engine={engine}, language={language})"}


@router.get("/voices")
async def voice_list():
    """List available TTS voices and engines."""
    return {
        "engines": {
            "groq_orpheus": {
                "quality": "excellent", "cost": "free",
                "languages": ["en"], "voices": speech.GROQ_VOICES,
                "expressive_tags": ["[cheerful]", "[sad]", "[whisper]", "[laughing]"],
            },
            "voxtral": {
                "quality": "excellent", "cost": "$0.016/1K chars",
                "languages": ["en", "fr", "de", "es", "it", "pt", "nl", "ru", "ar"],
            },
            "kokoro": {
                "quality": "very good", "cost": "free (local, CPU)",
                "languages": ["en"],
            },
            "piper": {
                "quality": "good", "cost": "free (local)",
                "languages": ["en", "fr"],
                "voices": [v["id"] for v in speech.get_available_voices()],
            },
        },
        "stt": {"provider": "groq", "model": "whisper-large-v3-turbo",
                "daily_limit": "28,800 seconds"},
    }
