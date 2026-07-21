"""Twilio WhatsApp bot — forwards messages to EasyRecon ask pipeline."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from rag.db import DEFAULT_DB_PATH
from rag.reports import daily_report, format_whatsapp_report
from rag.sql_agent import ask_safe

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv(
    "TWILIO_WHATSAPP_FROM",
    "whatsapp:+14155238886",  # Twilio sandbox default
)
WHATSAPP_PHARMACY_NAME = os.getenv("WHATSAPP_PHARMACY_NAME", "Bismillah Medical Store")
WHATSAPP_MAX_REPLY_LEN = 4000

REPORT_KEYWORDS = frozenset({"report", "daily", "hisaab", "hisab", "subah"})
HELP_KEYWORDS = frozenset({"help", "menu", "start", "hi", "hello", "salam", "assalam"})


def is_whatsapp_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM)


def _client():
    if not is_whatsapp_configured():
        raise RuntimeError(
            "Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN in .env"
        )
    from twilio.rest import Client

    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def normalize_whatsapp_address(raw: str) -> str:
    """Ensure whatsapp:+92... format."""
    raw = raw.strip()
    if raw.startswith("whatsapp:"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "92" + digits[1:]
    elif not digits.startswith("92") and len(digits) == 10:
        digits = "92" + digits
    return f"whatsapp:+{digits}"


def session_id_from_phone(from_address: str) -> str:
    digits = re.sub(r"\D", "", from_address)
    return f"wa-{digits[-15:]}"


def send_whatsapp(to_address: str, body: str) -> dict[str, Any]:
    client = _client()
    to_addr = normalize_whatsapp_address(to_address)
    from_addr = TWILIO_WHATSAPP_FROM
    if not from_addr.startswith("whatsapp:"):
        from_addr = f"whatsapp:{from_addr}"

    text = body.strip()
    if len(text) > WHATSAPP_MAX_REPLY_LEN:
        text = text[: WHATSAPP_MAX_REPLY_LEN - 20] + "\n...(truncated)"

    msg = client.messages.create(body=text, from_=from_addr, to=to_addr)
    return {"sid": msg.sid, "status": msg.status}


def help_message() -> str:
    return (
        f"*EasyRecon* — {WHATSAPP_PHARMACY_NAME}\n\n"
        "Apni pharmacy ke business sawal yahan likhein (Roman Urdu / English).\n\n"
        "Examples:\n"
        "• Aaj cash short kyun hai?\n"
        "• Panadol pari hai?\n"
        "• Pichle mahine kitni sales?\n"
        "• Top 5 medicines\n\n"
        "Commands:\n"
        "• *report* — aaj ki reconciliation (instant)\n"
        "• *help* — yeh message\n\n"
        "_Demo data: sample store. Production mein aap ka POS connect hoga._"
    )


def _handle_report() -> str:
    if not DEFAULT_DB_PATH.exists():
        return "Database nahi mila. Pehle sample data generate karein."
    return format_whatsapp_report(daily_report())


def _handle_question(question: str, from_address: str) -> str:
    if not DEFAULT_DB_PATH.exists():
        return "Database nahi mila. Server setup incomplete hai."

    session_id = session_id_from_phone(from_address)
    result = ask_safe(
        question,
        session_id=session_id,
        pharmacy_name=WHATSAPP_PHARMACY_NAME,
    )

    if result.get("error") and not result.get("answer"):
        err = result["error"]
        if "groq" in err.lower() or "api key" in err.lower():
            return "Groq API issue — server admin se contact karein."
        if "ollama" in err.lower() or "connect" in err.lower():
            return "AI server abhi available nahi. Thori der baad try karein."
        return f"Error: {err[:200]}"

    return result.get("answer") or "Koi jawab generate nahi ho saka."


def _wrap_tables_for_whatsapp(text: str) -> str:
    """WhatsApp renders monospace blocks; wrap markdown tables for readability."""
    if "|" not in text or "---" not in text:
        return text.replace("**", "*")
    parts = []
    in_table = False
    for line in text.split("\n"):
        if line.strip().startswith("|"):
            if not in_table:
                parts.append("```")
                in_table = True
            parts.append(line)
        else:
            if in_table:
                parts.append("```")
                in_table = False
            parts.append(line.replace("**", "*"))
    if in_table:
        parts.append("```")
    return "\n".join(parts)


def process_incoming_message(from_address: str, body: str) -> None:
    """Run in background — may take 10–30s for AI questions."""
    text = (body or "").strip()
    if not text:
        send_whatsapp(from_address, help_message())
        return

    key = text.lower().split()[0].strip("*.,!?")

    try:
        if key in REPORT_KEYWORDS:
            reply = _handle_report()
        elif key in HELP_KEYWORDS and len(text.split()) <= 2:
            reply = help_message()
        else:
            send_whatsapp(from_address, "Soch raha hoon... (10–30 sec lag sakte hain)")
            reply = _handle_question(text, from_address)

        send_whatsapp(from_address, _wrap_tables_for_whatsapp(reply))
    except Exception as exc:
        logger.exception("WhatsApp handler failed")
        try:
            send_whatsapp(
                from_address,
                f"Internal error. Admin check karein.\n{type(exc).__name__}",
            )
        except Exception:
            logger.exception("Failed to send error reply")
