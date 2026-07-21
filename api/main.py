"""EasyRecon API — pharmacy reconciliation assistant."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Load .env if present
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from rag.db import DEFAULT_DB_PATH, get_schema_summary
from rag.llm import health_check
from rag.memory import (
    get_or_create_pharmacy_session,
    load_corrections,
    load_session,
    new_session_id,
    reset_pharmacy_session,
    session_for_api,
)
from rag.reports import daily_report, format_whatsapp_report
from rag.speech import SpeechError, speech_status, synthesize_speech, transcribe_audio
from rag.speech_options import list_speech_options
from rag.learning import learning_stats
from rag.sql_agent import ask_safe
from rag.whatsapp_bot import is_whatsapp_configured
from api.whatsapp import router as whatsapp_router

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="EasyRecon",
    description="Pharmacy business assistant — Groq intent/answers + local Qwen SQL",
    version="0.4.0",
)

app.include_router(whatsapp_router)

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Aaj cash short kyun hai?"])
    session_id: Optional[str] = Field(None, description="Per-pharmacy session for chat memory")
    pharmacy_name: Optional[str] = Field(None, examples=["Bismillah Medical Store"])
    model: Optional[str] = Field(None, description="Ollama model override for SQL/answers")


class AskResponse(BaseModel):
    question: str
    answer: Optional[str] = None
    sql: Optional[str] = None
    row_count: Optional[int] = None
    rows: Optional[list] = None
    error: Optional[str] = None
    off_topic: bool = False
    corrected: bool = False
    intent: Optional[dict] = None
    session_id: Optional[str] = None
    elapsed_ms: Optional[int] = None
    answer_source: Optional[str] = None


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: Optional[str] = Field(None, description="edge-tts voice id, e.g. ur-PK-UzmaNeural")


@app.get("/")
def root():
    index = WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    demo = WEB_DIR / "demo.html"
    if demo.exists():
        return FileResponse(demo)
    return {
        "service": "EasyRecon",
        "demo": "/demo",
        "endpoints": ["/health", "/ask", "/demo", "/speech/transcribe", "/speech/speak", "/report/whatsapp", "/whatsapp/webhook", "/whatsapp/status"],
    }


@app.get("/demo")
def demo_page():
    path = WEB_DIR / "demo.html"
    if not path.exists():
        raise HTTPException(404, "Demo page not found")
    return FileResponse(path)


@app.get("/health")
def health() -> dict:
    llm = health_check()
    return {
        "status": "ok" if llm.get("intent_ready") and llm.get("ollama_ready") else "degraded",
        "database": str(DEFAULT_DB_PATH),
        "database_exists": DEFAULT_DB_PATH.exists(),
        "llm": llm,
        "learned_corrections": len(load_corrections()),
        "whatsapp": {"configured": is_whatsapp_configured()},
        "speech": speech_status(),
    }


@app.post("/session/new")
def create_session(pharmacy_name: str = "Bismillah Medical Store") -> dict:
    session = reset_pharmacy_session(pharmacy_name)
    return session_for_api(session)


@app.get("/session/pharmacy")
def pharmacy_session(pharmacy_name: str = "Bismillah Medical Store") -> dict:
    """Get or create the active chat session for this pharmacy (survives page refresh)."""
    session = get_or_create_pharmacy_session(pharmacy_name)
    return session_for_api(session)


@app.post("/session/pharmacy/reset")
def pharmacy_session_reset(pharmacy_name: str = "Bismillah Medical Store") -> dict:
    """Start a fresh chat for this pharmacy."""
    session = reset_pharmacy_session(pharmacy_name)
    return session_for_api(session)


@app.get("/session/{session_id}")
def get_session(session_id: str) -> dict:
    return session_for_api(load_session(session_id))


@app.get("/schema")
def schema() -> dict:
    if not DEFAULT_DB_PATH.exists():
        raise HTTPException(404, "Database not found. Run scripts/generate_pharmacy_db.py")
    return {"schema": get_schema_summary()}


@app.get("/memory")
def memory() -> dict:
    return {"learned_corrections": load_corrections()}


@app.get("/speech/status")
def speech_status_endpoint() -> dict:
    return speech_status()


@app.get("/speech/options")
def speech_options_endpoint() -> dict:
    """STT/TTS provider catalog — swap via .env without code changes."""
    return list_speech_options()


@app.get("/learning")
def learning_endpoint() -> dict:
    return learning_stats()


@app.post("/speech/transcribe")
async def speech_transcribe(file: UploadFile = File(...)) -> dict:
    """Speech-to-text — Azure ur-PK by default; Groq/local Whisper fallback."""
    try:
        raw = await file.read()
        content_type = file.content_type or "audio/webm"
        filename = file.filename or "audio.webm"
        text = transcribe_audio(raw, filename=filename, content_type=content_type)
        provider = speech_status().get("stt_provider", "local_whisper")
        return {"text": text, "provider": provider}
    except SpeechError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/speech/speak")
def speech_speak(body: SpeakRequest) -> Response:
    """Text-to-speech — local pyttsx3 by default; edge-tts if SPEECH_TTS_PROVIDER=edge."""
    try:
        audio, media_type = synthesize_speech(body.text, voice=body.voice)
        return Response(content=audio, media_type=media_type)
    except SpeechError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(body: AskRequest) -> AskResponse:
    if not DEFAULT_DB_PATH.exists():
        raise HTTPException(404, "Database not found. Run scripts/generate_pharmacy_db.py")

    if body.pharmacy_name and not body.session_id:
        session_id = get_or_create_pharmacy_session(body.pharmacy_name)["session_id"]
    else:
        session_id = body.session_id or new_session_id()
    result = ask_safe(
        body.question,
        model=body.model,
        session_id=session_id,
        pharmacy_name=body.pharmacy_name,
    )
    if result.get("error") and not result.get("answer"):
        err = result["error"]
        if "invalid_api_key" in err.lower() or "invalid api key" in err.lower():
            raise HTTPException(
                401,
                "Groq API key invalid. Get a free key at https://console.groq.com "
                "— must start with gsk_ — then update .env and restart the server.",
            )
        raise HTTPException(503, err)

    return AskResponse(
        question=result["question"],
        answer=result.get("answer"),
        sql=result.get("sql"),
        row_count=result.get("row_count"),
        rows=result.get("rows"),
        error=result.get("error"),
        off_topic=bool(result.get("off_topic")),
        corrected=bool(result.get("corrected")),
        intent=result.get("intent"),
        session_id=session_id,
        elapsed_ms=result.get("elapsed_ms"),
        answer_source=result.get("answer_source"),
    )


@app.get("/report")
def report_endpoint() -> dict:
    if not DEFAULT_DB_PATH.exists():
        raise HTTPException(404, "Database not found.")
    return daily_report()


@app.get("/report/whatsapp")
def report_whatsapp() -> dict:
    if not DEFAULT_DB_PATH.exists():
        raise HTTPException(404, "Database not found.")
    report = daily_report()
    return {"text": format_whatsapp_report(report), "summary": report["summary"]}


def main() -> None:
    import uvicorn

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("api.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
