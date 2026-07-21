"""WhatsApp webhook routes (Twilio)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Response

from rag.whatsapp_bot import is_whatsapp_configured, process_incoming_message

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/status")
def whatsapp_status() -> dict:
    return {
        "configured": is_whatsapp_configured(),
        "provider": "twilio",
        "webhook_path": "/whatsapp/webhook",
        "setup": (
            "1. Twilio account + WhatsApp Sandbox\n"
            "2. ngrok http 8000\n"
            "3. Set sandbox webhook to https://YOUR-NGROK/whatsapp/webhook\n"
            "4. Join sandbox from your phone (Twilio console shows code)"
        ),
    }


@router.post("/webhook")
async def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(default=""),
    To: str = Form(default=""),
) -> Response:
    if not is_whatsapp_configured():
        raise HTTPException(
            503,
            "WhatsApp not configured. Add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to .env",
        )

    background_tasks.add_task(process_incoming_message, From, Body)
    return Response(status_code=200, content="", media_type="text/plain")
